"""
Review Formatter Agent — converts raw analysis findings into GitHub-ready
inline review comment objects.

Why a separate formatter agent?
--------------------------------
Single Responsibility Principle: the code_analysis_agent should only think
about FINDING problems. How those problems are PRESENTED to a human (formatting,
severity icons, markdown, GitHub API shape) is a separate concern.

This also makes it easy to change the output format (e.g. support GitLab later)
without touching any analysis logic.
"""

from agents.llm_factory import get_llm
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import json
import re


# Severity → emoji mapping for readable PR comments
_SEVERITY_ICON = {
    "HIGH": "🔴",
    "MEDIUM": "🟡",
    "LOW": "🔵",
}

# Category → label
_CATEGORY_LABEL = {
    "bug": "Bug",
    "security": "Security",
    "quality": "Code Quality",
}


def _build_comment_body(finding: dict) -> str:
    """
    Build a nicely formatted markdown string for a single GitHub review comment.

    GitHub PR review comments support full Markdown — headers, bold, code blocks.
    We use that to make reviews visually clear and scannable.

    Example output:
        🔴 **[HIGH — Security]**
        Hardcoded API key detected in source code.

        **Suggestion:** Move to environment variable: `os.getenv('API_KEY')`
    """
    icon = _SEVERITY_ICON.get(finding.get("severity", "LOW"), "🔵")
    severity = finding.get("severity", "LOW")
    category = _CATEGORY_LABEL.get(finding.get("category", "quality"), "Review")
    message = finding.get("message", "")
    suggestion = finding.get("suggestion", "")

    body = f"{icon} **[{severity} — {category}]**\n{message}"
    if suggestion:
        body += f"\n\n**Suggestion:** {suggestion}"
    return body


def format_review_comments(findings: list[dict]) -> list[dict]:
    """
    Transform raw findings into GitHub Pull Request Review API comment objects.

    GitHub Review API shape:
    POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews
    Body: {
        "body": "Overall summary",
        "event": "COMMENT",
        "comments": [
            {
                "path": "src/app.py",   ← file path relative to repo root
                "line": 42,             ← line number in the NEW file (right side)
                "side": "RIGHT",        ← RIGHT = new file, LEFT = old file
                "body": "markdown text" ← the comment content
            }
        ]
    }

    Why "RIGHT" side?
    -----------------
    A diff has two sides: LEFT (old code being removed) and RIGHT (new code being added).
    We always comment on RIGHT because we're reviewing the NEW code that was just added.

    Args:
        findings: Output from run_code_analysis_agent()

    Returns:
        List of GitHub comment dicts ready to be sent to the GitHub Review API.
    """
    comments = []

    for finding in findings:
        line = finding.get("line", 0)

        # GitHub API requires line >= 1. If LLM returned 0 or unknown, default to 1.
        # This means the comment appears at the top of the file — acceptable fallback.
        if not isinstance(line, int) or line < 1:
            line = 1

        comment = {
            "path": finding.get("file", "unknown"),
            "line": line,
            "side": "RIGHT",
            "body": _build_comment_body(finding),
        }
        comments.append(comment)

    return comments


def build_review_summary(findings: list[dict]) -> str:
    """
    Build the top-level PR review summary body using the LLM.

    This is the overall comment that appears at the top of the review
    before the inline comments. It gives the reviewer a high-level overview.

    We use the LLM here (vs hardcoding) because a natural language summary
    reads much better than a templated list of counts.

    Args:
        findings: All findings from run_code_analysis_agent()

    Returns:
        Markdown string for the top-level review body.
    """
    if not findings:
        return "✅ **AI Review Complete** — No issues found in this pull request."

    # Summarise counts for the LLM prompt
    high = sum(1 for f in findings if f.get("severity") == "HIGH")
    medium = sum(1 for f in findings if f.get("severity") == "MEDIUM")
    low = sum(1 for f in findings if f.get("severity") == "LOW")

    issues_text = "\n".join(
        f"- [{f.get('severity')}][{f.get('category')}] {f.get('file')}:{f.get('line', '?')} — {f.get('message')}"
        for f in findings
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a helpful AI code review assistant.
Write a concise pull request review summary in Markdown (3-5 sentences).
Mention the number and types of issues found. Be constructive and professional.
Start with an emoji status indicator: 🔴 if HIGH issues exist, 🟡 if only MEDIUM/LOW."""),
        ("human", f"Issues found ({high} HIGH, {medium} MEDIUM, {low} LOW):\n\n{issues_text}"),
    ])

    chain = prompt | get_llm(temperature=0.3) | StrOutputParser()
    return chain.invoke({})
