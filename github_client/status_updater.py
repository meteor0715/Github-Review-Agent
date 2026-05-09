"""
PR Status Updater — sets commit status on a PR (pending → success / failure).

What is a commit status?
--------------------------
Every commit on GitHub can have a coloured status badge:
  ⏳ pending   → "AI Review in progress..."
  ✅ success   → "AI Review complete — 0 HIGH issues"
  ❌ failure   → "AI Review complete — 2 HIGH issues found"
  ⚠️  error    → "AI Review failed (unexpected error)"

These appear in the PR checks section and on the commits list.
They're set via the Commit Statuses API (not the Reviews API — separate thing).

Why set "pending" at the start?
---------------------------------
The LLM takes time to run. Setting "pending" immediately tells the PR author
"the bot is working" rather than leaving them wondering if the bot is broken.
This is standard practice for CI systems (tests start → pending, tests pass → success).

context field:
---------------
The "context" string is the name shown on the GitHub PR page under "Checks".
e.g. "ai-review-agent" appears as a named check the team can relies on.
If you use the same context string each time, GitHub tracks history per-context.
"""

import httpx

GITHUB_API_URL = "https://api.github.com"

# Valid states accepted by GitHub Commit Statuses API
VALID_STATES = {"pending", "success", "failure", "error"}


def set_commit_status(
    token: str,
    repo_full_name: str,
    sha: str,
    state: str,
    description: str = "",
    context: str = "ai-review-agent",
) -> dict:
    """
    Set the GitHub commit status for a given SHA.

    Args:
        token: Installation access token from github_client.auth
        repo_full_name: Repository in "owner/repo" format
        sha: The full commit SHA to set status on (from webhook head_sha)
        state: One of "pending", "success", "failure", "error"
        description: Short human-readable status message (max 140 chars).
                     Shown next to the status badge on the PR.
        context: Status context label — name of the check shown on GitHub.
                 Use the same string every time so GitHub tracks it as one check.

    Returns:
        GitHub API response dict

    Raises:
        ValueError: If state is not a valid GitHub status state
        httpx.HTTPStatusError: On GitHub API errors
    """
    if state not in VALID_STATES:
        raise ValueError(f"Invalid state '{state}'. Must be one of {VALID_STATES}")

    # Truncate description to GitHub's 140 char limit
    if len(description) > 140:
        description = description[:137] + "..."

    url = f"{GITHUB_API_URL}/repos/{repo_full_name}/statuses/{sha}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    body = {
        "state": state,
        "description": description,
        "context": context,
    }

    response = httpx.post(url, json=body, headers=headers)
    response.raise_for_status()
    return response.json()

