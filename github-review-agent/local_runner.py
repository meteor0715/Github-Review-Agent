"""
Local Runner — CLI tool to manually trigger a code review on any PR URL.
Useful for demos and testing without needing a live webhook.

Usage:
    python local_runner.py --pr https://github.com/owner/repo/pull/42
"""
import argparse


def run_review_for_pr(pr_url: str) -> None:
    """
    Fetch the diff for the given PR URL and run the full review pipeline.

    Args:
        pr_url: Full GitHub PR URL, e.g. https://github.com/owner/repo/pull/42
    """
    # TODO: A5.1 — parse owner/repo/pr_number from URL
    # TODO: A5.1 — fetch diff via GitHub API using github_client.auth
    # TODO: A5.1 — run diff_parser → RAG retriever → orchestrator → formatter → comment_poster
    pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manually trigger an AI PR review")
    parser.add_argument("--pr", required=True, help="Full GitHub PR URL")
    args = parser.parse_args()
    run_review_for_pr(args.pr)
