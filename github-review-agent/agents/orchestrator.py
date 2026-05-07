"""
Orchestration Agent — entry point for the review pipeline.
Receives the parsed PR diff + RAG context, routes work to sub-agents,
and collects their results into a unified output.
"""


def run_orchestrator(diff: list[dict], rag_context: str) -> list[dict]:
    """
    Orchestrate the full review for a PR.

    Args:
        diff: Parsed diff from diff_parser.parse_diff()
        rag_context: Relevant codebase context retrieved from the RAG pipeline

    Returns:
        List of raw review findings from sub-agents
    """
    # TODO: A2.1 — implement orchestration logic using LangChain ChatOllama
    pass
