"""
Code Analysis Agent — analyses a PR diff for bugs, security issues, and code quality problems.

Tools:
  - analyze_bugs     : detect logic errors and null pointer issues
  - analyze_security : flag hardcoded secrets, SQL injection, XSS
  - analyze_quality  : check code smells, naming conventions, complexity
"""


def analyze_bugs(code_snippet: str) -> list[dict]:
    """Detect logic errors and null pointer issues in the given code snippet."""
    # TODO: A2.3 — implement using LangChain tool + ChatOllama
    pass


def analyze_security(code_snippet: str) -> list[dict]:
    """Flag hardcoded secrets, SQL injection vectors, and XSS vulnerabilities."""
    # TODO: A2.3 — implement using LangChain tool + ChatOllama
    pass


def analyze_quality(code_snippet: str) -> list[dict]:
    """Check code smells, naming conventions, and cyclomatic complexity."""
    # TODO: A2.3 — implement using LangChain tool + ChatOllama
    pass


def run_code_analysis_agent(diff: list[dict], context: str) -> list[dict]:
    """
    Run all analysis tools over the diff and return findings.

    Returns:
        List of findings: [{file, line, severity, category, message, suggestion}]
    """
    # TODO: A2.3 — wire tools together with LangChain agent executor
    pass
