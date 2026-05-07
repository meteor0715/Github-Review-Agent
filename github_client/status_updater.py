"""
PR Status Updater — sets the commit status on a PR
(pending → success / failure) with a short summary message.
"""


def set_commit_status(
    token: str,
    repo_full_name: str,
    sha: str,
    state: str,
    description: str = "",
    context: str = "ai-review-agent",
) -> None:
    """
    Set the GitHub commit status for a given SHA.

    Args:
        token: Installation access token
        repo_full_name: e.g. "owner/repo"
        sha: The commit SHA to update status on
        state: One of "pending", "success", "failure", "error"
        description: Short human-readable status message (max 140 chars)
        context: Status context label shown on GitHub
    """
    # TODO: B3.2 — POST to /repos/{owner}/{repo}/statuses/{sha}
    pass
