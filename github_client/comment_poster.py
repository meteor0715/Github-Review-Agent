"""
Comment Poster — posts inline review comments on a GitHub PR
using the GitHub Pull Request Review API.
"""


def post_review_comments(
    token: str,
    repo_full_name: str,
    pr_number: int,
    comments: list[dict],
    summary: str = "",
) -> None:
    """
    Submit a PR review with inline comments.

    Args:
        token: Installation access token from github_client.auth
        repo_full_name: e.g. "owner/repo"
        pr_number: Pull request number
        comments: List of comment dicts from formatter_agent.format_review_comments()
        summary: Overall review summary body text
    """
    # TODO: B3.1 — POST to /repos/{owner}/{repo}/pulls/{pr_number}/reviews
    pass
