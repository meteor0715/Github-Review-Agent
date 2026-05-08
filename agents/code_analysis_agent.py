"""
Code Analysis Agent — analyses a PR diff for bugs, security issues, and code quality.

Architecture decision — Why direct LLM chains instead of a full AgentExecutor loop?
-------------------------------------------------------------------------------------
LangChain has two main patterns:

1. AgentExecutor (ReAct loop):
   LLM decides WHICH tool to call → calls it → looks at result → decides next tool → repeat
   Good for: open-ended tasks where you don't know the steps upfront
   Bad for:  local models (Llama3 can loop or hallucinate tool calls under load)

2. Direct chains (what we use here):
   We call each analysis (bugs, security, quality) as a separate, focused LLM prompt.
   The LLM just has to answer ONE question at a time and return JSON.
   Good for: predictable, structured output — exactly what code review needs.
   More reliable with smaller local models.

This pattern is called LCEL (LangChain Expression Language) — chaining prompt | llm | parser.

Each "tool" is a function that:
  1. Builds a focused prompt about ONE type of problem
  2. Calls the LLM
  3. Parses the JSON response into a structured list of findings
"""

import json
import re
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from agents.llm_factory import get_llm


# ─── Prompt templates ────────────────────────────────────────────────────────
# We use few-shot examples (the JSON structure in the prompt) so the model
# knows EXACTLY what format to return. Without examples, LLMs often add
# prose around the JSON, which breaks parsing.

_BUG_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert code reviewer specialising in finding bugs.
Analyse the provided code diff and identify logic errors, null/None reference issues,
off-by-one errors, unhandled exceptions, or incorrect condition checks.

Return ONLY a JSON array. Each item must have these exact keys:
  "line"       - the line number where the issue is (integer, use 0 if unknown)
  "severity"   - one of: "HIGH", "MEDIUM", "LOW"
  "message"    - a short description of the bug
  "suggestion" - a concrete fix suggestion

If no bugs found, return an empty array: []

Example output:
[
  {{"line": 12, "severity": "HIGH", "message": "Variable `user` may be None before .id is accessed", "suggestion": "Add a null check: if user is None: return"}}
]"""),
    ("human", "Code diff to review:\n\n{code_snippet}"),
])

_SECURITY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert security code reviewer.
Analyse the provided code diff and identify security vulnerabilities such as:
hardcoded secrets/passwords/API keys, SQL injection, XSS vulnerabilities,
insecure deserialization, missing input validation, path traversal, or
exposed sensitive data in logs.

Return ONLY a JSON array. Each item must have these exact keys:
  "line"       - the line number where the issue is (integer, use 0 if unknown)
  "severity"   - one of: "HIGH", "MEDIUM", "LOW"
  "message"    - a short description of the vulnerability
  "suggestion" - a concrete fix suggestion

If no security issues found, return an empty array: []

Example output:
[
  {{"line": 5, "severity": "HIGH", "message": "Hardcoded API key detected in source code", "suggestion": "Move to environment variable: os.getenv('API_KEY')"}}
]"""),
    ("human", "Code diff to review:\n\n{code_snippet}"),
])

_QUALITY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert code quality reviewer.
Analyse the provided code diff and identify code quality issues such as:
overly long functions, poor variable naming, missing docstrings on public functions,
code duplication, magic numbers, deeply nested logic, or violation of single responsibility.

Return ONLY a JSON array. Each item must have these exact keys:
  "line"       - the line number where the issue is (integer, use 0 if unknown)
  "severity"   - one of: "MEDIUM", "LOW"  (quality issues are never HIGH)
  "message"    - a short description of the quality issue
  "suggestion" - a concrete improvement suggestion

If no quality issues found, return an empty array: []

Example output:
[
  {{"line": 20, "severity": "LOW", "message": "Function `process` has no docstring", "suggestion": "Add a docstring explaining what the function does and its parameters"}}
]"""),
    ("human", "Code diff to review:\n\n{code_snippet}"),
])


# ─── JSON parser helper ───────────────────────────────────────────────────────

def _parse_json_response(raw: str) -> list[dict]:
    """
    Extract and parse a JSON array from LLM output.

    Why not just json.loads(raw)?
    LLMs often wrap the JSON in markdown code blocks like:
      ```json
      [{"line": 5, ...}]
      ```
    This function strips that wrapper before parsing.
    """
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

    # Find the first '[' and last ']' to extract the array
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1:
        return []  # LLM returned no array — treat as no findings

    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return []  # Malformed JSON — safe fallback to no findings


# ─── Analysis functions ───────────────────────────────────────────────────────

def analyze_bugs(code_snippet: str) -> list[dict]:
    """
    Detect logic errors and null pointer issues in the given code snippet.

    Uses LCEL chain: prompt | llm | string_parser
    The string parser just extracts the text content from the LLM message object.
    We then parse the JSON ourselves.

    Args:
        code_snippet: Raw code string (typically one file's diff content)

    Returns:
        List of findings dicts with keys: line, severity, message, suggestion
    """
    chain = _BUG_PROMPT | get_llm() | StrOutputParser()
    raw = chain.invoke({"code_snippet": code_snippet})
    findings = _parse_json_response(raw)
    return [{"category": "bug", **f} for f in findings]


def analyze_security(code_snippet: str) -> list[dict]:
    """
    Flag hardcoded secrets, SQL injection vectors, and XSS vulnerabilities.

    Args:
        code_snippet: Raw code string

    Returns:
        List of findings dicts with keys: line, severity, category, message, suggestion
    """
    chain = _SECURITY_PROMPT | get_llm() | StrOutputParser()
    raw = chain.invoke({"code_snippet": code_snippet})
    findings = _parse_json_response(raw)
    return [{"category": "security", **f} for f in findings]


def analyze_quality(code_snippet: str) -> list[dict]:
    """
    Check code smells, naming conventions, and cyclomatic complexity.

    Args:
        code_snippet: Raw code string

    Returns:
        List of findings dicts with keys: line, severity, category, message, suggestion
    """
    chain = _QUALITY_PROMPT | get_llm() | StrOutputParser()
    raw = chain.invoke({"code_snippet": code_snippet})
    findings = _parse_json_response(raw)
    return [{"category": "quality", **f} for f in findings]


# ─── Main entry point ─────────────────────────────────────────────────────────

def run_code_analysis_agent(diff: list[dict], context: str = "") -> list[dict]:
    """
    Run all three analysis tools over every file in the diff.

    Why iterate file by file instead of passing the whole diff?
    -----------------------------------------------------------
    LLMs have a context window limit (e.g. Llama3 = 8k tokens).
    A large PR diff could exceed this. By splitting per file, we keep
    each LLM call focused and within token limits.
    Also, per-file analysis means findings can carry accurate file names.

    Args:
        diff: Parsed diff from diff_parser.parse_diff()
              Format: [{"filename": str, "hunks": [...], "added_lines": str}]
        context: RAG-retrieved codebase context (injected by orchestrator)

    Returns:
        All findings across all files and all three analysis categories.
        Format: [{file, line, severity, category, message, suggestion}]
    """
    all_findings = []

    for file_diff in diff:
        filename = file_diff.get("filename", "unknown")
        # We analyse the added lines only (lines starting with '+' in the diff)
        # Reviewing removed lines for bugs isn't useful — they're being deleted
        added_code = file_diff.get("added_lines", "")

        if not added_code.strip():
            continue  # Skip files with no added lines (e.g. pure deletions)

        # Build the snippet — include filename for LLM context
        snippet = f"# File: {filename}\n{added_code}"
        if context:
            snippet = f"# Existing codebase context:\n{context}\n\n{snippet}"

        # Run all three analyses and tag each finding with its filename
        for finding in analyze_bugs(snippet):
            all_findings.append({"file": filename, **finding})

        for finding in analyze_security(snippet):
            all_findings.append({"file": filename, **finding})

        for finding in analyze_quality(snippet):
            all_findings.append({"file": filename, **finding})

    return all_findings
