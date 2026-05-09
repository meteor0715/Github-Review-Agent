"""
Comment Poster — posts inline review comments on a GitHub PR.

GitHub Review API vs regular Comment API:
------------------------------------------
GitHub has two different ways to comment on a PR:

1. Issue Comments API (POST /issues/{number}/comments):
   - Posts a comment at the bottom of the PR conversation
   - No ability to attach to a specific line

2. Pull Request Review API (POST /pulls/{number}/reviews) ← we use this
   - Posts a full review with an overall summary body
   - Supports INLINE comments attached to specific files and line numbers
   - Shows up as a proper code review (with green/red review status)

Why "reviews" instead of just "comments"?
------------------------------------------
Inline comments attached to specific lines are the standard for code review tools
(this is how GitHub's own "Review changes" button works, how Copilot posts comments,
how SonarQube GitHub integration works). It's a much better UX for the PR author.

Review "event" types:
  APPROVE  → approves the PR (green checkmark)
  REQUEST_CHANGES → blocks merge until changes are made
  COMMENT  → neutral review, no merge block ← we use this (non-blocking)

We use COMMENT so the bot doesn't block PRs — it's advisory, not mandatory.
"""

import httpx

GITHUB_API_URL = "https://api.github.com"


def post_review_comments(
    token: str,
    repo_full_name: str,
    pr_number: int,
    comments: list[dict],
    summary: str = "",
    commit_sha: str = "",
) -> dict:
    """
    Submit a PR review with inline comments using the GitHub Review API.

    Args:
        token: Installation access token from github_client.auth
        repo_full_name: Repository in "owner/repo" format e.g. "sanmro/my-project"
        pr_number: Pull request number (integer)
        comments: List of comment dicts from formatter_agent.format_review_comments()
                  Each dict must have: path, line, side, body
        summary: Top-level review body (markdown). Shown at the top of the review.
        commit_sha: The HEAD commit SHA of the PR. GitHub requires this to anchor
                    inline comments to a specific version of the code.
                    Comes from the webhook payload (pr_data["head_sha"]).

    Returns:
        GitHub API response dict containing the created review

    Raises:
        httpx.HTTPStatusError: On GitHub API errors (invalid token, wrong line number, etc.)
    """
    url = f"{GITHUB_API_URL}/repos/{repo_full_name}/pulls/{pr_number}/reviews"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # GitHub expects inline comments in this exact shape
    # We pass through the comments from the formatter as-is since the formatter
    # already shapes them correctly (path, line, side, body)
    body = {
        "commit_id": commit_sha,
        "body": summary,
        "event": "COMMENT",      # non-blocking advisory review
        "comments": comments,
    }

    response = httpx.post(url, json=body, headers=headers)
    response.raise_for_status()
    return response.json()

