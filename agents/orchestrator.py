"""
Orchestration Agent — the entry point and coordinator for the full review pipeline.

What does an orchestrator do?
------------------------------
In a multi-agent system, the orchestrator is the "manager". It:
  1. Receives the input (PR diff + RAG context)
  2. Decides the order to call sub-agents
  3. Passes output from one agent as input to the next
  4. Returns the final combined result

Why not just call everything from webhook_handler.py directly?
--------------------------------------------------------------
Separation of concerns. The webhook handler should only care about HTTP
(receiving the request, sending a response). The orchestrator handles
the BUSINESS LOGIC of what to do with the diff. This makes each part
independently testable and replaceable.

This pattern is called the Orchestrator Pattern (or sometimes the Saga Pattern
when dealing with distributed systems). Interviewers love this distinction.

Data flow:
  PR diff (list[dict])
    + RAG context (str)
        │
        ▼
  run_code_analysis_agent()   ← finds bugs, security issues, quality problems
        │
        ▼ raw findings (list[dict])
        │
        ▼
  format_review_comments()    ← converts findings to GitHub API shape
        │
        ▼ comments (list[dict])
        │
        ▼
  build_review_summary()      ← generates human-readable overall summary
        │
        ▼
  Returns: {"summary": str, "comments": list[dict]}
"""

import structlog
from agents.code_analysis_agent import run_code_analysis_agent
from agents.formatter_agent import format_review_comments, build_review_summary

log = structlog.get_logger()


def run_orchestrator(diff: list[dict], rag_context: str = "") -> dict:
    """
    Coordinate the full PR review pipeline.

    Args:
        diff: Parsed diff from diff_parser.parse_diff()
              Each item: {"filename": str, "added_lines": str, "hunks": list}
        rag_context: Relevant existing code retrieved from ChromaDB by the RAG pipeline.
                     Gives agents extra context about the codebase so they understand
                     what existing patterns/conventions look like.

    Returns:
        {
            "summary": str,         ← top-level PR review body (markdown)
            "comments": list[dict]  ← inline comments for GitHub Review API
        }
    """
    log.info("orchestrator.start", files_in_diff=len(diff))

    # Step 1: Analyse the diff using the Code Analysis Agent
    # This runs bug, security, and quality checks on every added file
    log.info("orchestrator.analysis.start")
    findings = run_code_analysis_agent(diff, context=rag_context)
    log.info("orchestrator.analysis.done", total_findings=len(findings))

    # Step 2: Format raw findings into GitHub review comment objects
    # This shapes findings into the exact structure the GitHub API expects
    log.info("orchestrator.formatting.start")
    comments = format_review_comments(findings)
    log.info("orchestrator.formatting.done", total_comments=len(comments))

    # Step 3: Build an overall review summary using the LLM
    # This is the top-level message the PR author sees first
    log.info("orchestrator.summary.start")
    summary = build_review_summary(findings)
    log.info("orchestrator.summary.done")

    return {
        "summary": summary,
        "comments": comments,
    }
