"""
Review Formatter Agent — converts raw agent findings into structured
GitHub review comment objects (file path, line number, severity, suggestion).
"""


def format_review_comments(findings: list[dict]) -> list[dict]:
    """
    Transform raw findings from the Code Analysis Agent into GitHub-ready
    review comment objects.

    Args:
        findings: Raw list from code_analysis_agent.run_code_analysis_agent()

    Returns:
        List of comment dicts:
        [{
            "path": "src/foo.py",
            "line": 42,
            "side": "RIGHT",
            "body": "**[HIGH - Security]** Hardcoded secret detected. Use environment variables instead."
        }]
    """
    # TODO: A2.4 — implement formatter using LangChain ChatOllama + output parser
    pass
