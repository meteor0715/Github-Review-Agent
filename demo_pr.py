"""
Demo PR Creator — for interviewer demos and quick testing.

This script creates a real GitHub PR on a target repo that contains
deliberate security and code quality issues, then immediately runs
the full AI review pipeline against it.

It demonstrates the entire end-to-end flow in one command:
  create branch → push bad file → open PR → AI reviews it → print findings

Usage:
    # Dry run — create PR but only PRINT the review findings (don't post comments)
    python demo_pr.py --repo owner/AI-Review_Test --dry-run

    # Full demo — create PR and have the bot post real inline comments on it
    python demo_pr.py --repo owner/AI-Review_Test

    # Clean up demo PRs and branches afterwards
    python demo_pr.py --repo owner/AI-Review_Test --cleanup

Prerequisites:
    - Ollama running with llama3 and nomic-embed-text pulled
    - .env populated with GITHUB_APP_ID, GITHUB_WEBHOOK_SECRET, GITHUB_APP_PRIVATE_KEY_PATH
    - GitHub App installed on the target repo
"""

import argparse
import base64
import sys
import os
import time
import random
import string

import httpx
import structlog
from dotenv import load_dotenv

load_dotenv()
log = structlog.get_logger()

# ── Deliberately bad code injected into the demo PR ───────────────────────────
# This is the file we create on the branch. It contains:
#   1. SQL injection vulnerability (string formatting into a query)
#   2. Hardcoded secret / API key
#   3. No function docstrings (quality issue)
#   4. Broad exception swallowing (quality issue)
#   5. Unused import (quality issue)

DEMO_FILE_CONTENT = '''\
"""
user_service.py — handles user lookups and authentication.

NOTE: This file is intentionally written with several bad practices
for demo/testing purposes. The AI review bot should catch these.
"""

import sqlite3
import requests  # unused import

# Hardcoded credentials — never do this in real code
DATABASE_URL = "sqlite:///users.db"
API_SECRET_KEY = "sk-live-abc123supersecret9999"
ADMIN_PASSWORD = "admin1234"


def get_user_by_name(username):
    conn = sqlite3.connect("users.db")
    # SQL injection: never format user input directly into a query
    query = f"SELECT * FROM users WHERE username = \'{username}\'"
    cursor = conn.execute(query)
    return cursor.fetchone()


def authenticate(username, password):
    user = get_user_by_name(username)
    if user is None:
        return False
    # Comparing plain-text password — should use hashed comparison
    return user[2] == password


def delete_user(user_id):
    conn = sqlite3.connect("users.db")
    # Another SQL injection vulnerability
    conn.execute(f"DELETE FROM users WHERE id = {user_id}")
    conn.commit()


def call_external_api(endpoint):
    try:
        resp = requests.get(endpoint, headers={"Authorization": API_SECRET_KEY})
        return resp.json()
    except:
        # Swallowing all exceptions hides bugs
        pass


def process_users(user_list):
    results = []
    for i in range(len(user_list)):   # should use enumerate or direct iteration
        u = user_list[i]
        results.append({"id": i, "name": u})
    return results
'''


def _get_auth_headers(jwt_token: str) -> dict:
    return {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_installation_token(repo_full_name: str, jwt_token: str) -> str:
    """Exchange a JWT for a short-lived installation access token."""
    resp = httpx.get(
        f"https://api.github.com/repos/{repo_full_name}/installation",
        headers=_get_auth_headers(jwt_token),
        timeout=15,
    )
    resp.raise_for_status()
    installation_id = str(resp.json()["id"])

    from github_client.auth import get_installation_token
    return get_installation_token(installation_id, jwt_token)


def _get_default_branch_sha(repo_full_name: str, headers: dict) -> tuple[str, str]:
    """Return (default_branch_name, latest_commit_sha)."""
    resp = httpx.get(
        f"https://api.github.com/repos/{repo_full_name}",
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    default_branch = resp.json()["default_branch"]

    ref_resp = httpx.get(
        f"https://api.github.com/repos/{repo_full_name}/git/ref/heads/{default_branch}",
        headers=headers,
        timeout=15,
    )
    ref_resp.raise_for_status()
    sha = ref_resp.json()["object"]["sha"]
    return default_branch, sha


def create_demo_pr(repo_full_name: str) -> tuple[int, str, str]:
    """
    Create a branch with a deliberately bad Python file and open a PR.

    Returns:
        (pr_number, head_sha, branch_name)
    """
    from github_client.auth import generate_jwt

    jwt_token = generate_jwt()
    token = _get_installation_token(repo_full_name, jwt_token)
    headers = _get_auth_headers(token)

    # ── 1. Get base branch SHA ─────────────────────────────────────────────────
    default_branch, base_sha = _get_default_branch_sha(repo_full_name, headers)
    log.info("demo_pr.base", branch=default_branch, sha=base_sha[:8])

    # ── 2. Create demo branch ──────────────────────────────────────────────────
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    branch_name = f"demo/ai-review-test-{suffix}"

    branch_resp = httpx.post(
        f"https://api.github.com/repos/{repo_full_name}/git/refs",
        headers=headers,
        json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        timeout=15,
    )
    branch_resp.raise_for_status()
    log.info("demo_pr.branch.created", branch=branch_name)

    # ── 3. Push the bad file to the branch ────────────────────────────────────
    encoded_content = base64.b64encode(DEMO_FILE_CONTENT.encode()).decode()
    file_path = "src/user_service.py"

    # Check if the file already exists (needed for update vs create)
    existing_resp = httpx.get(
        f"https://api.github.com/repos/{repo_full_name}/contents/{file_path}",
        headers={**headers, "ref": branch_name},
        timeout=15,
    )
    file_payload: dict = {
        "message": "demo: add user_service.py with intentional security issues",
        "content": encoded_content,
        "branch": branch_name,
    }
    if existing_resp.status_code == 200:
        # File exists — need its SHA to update it
        file_payload["sha"] = existing_resp.json()["sha"]

    file_resp = httpx.put(
        f"https://api.github.com/repos/{repo_full_name}/contents/{file_path}",
        headers=headers,
        json=file_payload,
        timeout=15,
    )
    file_resp.raise_for_status()
    head_sha = file_resp.json()["commit"]["sha"]
    log.info("demo_pr.file.pushed", path=file_path, sha=head_sha[:8])

    # ── 4. Open the PR ─────────────────────────────────────────────────────────
    pr_resp = httpx.post(
        f"https://api.github.com/repos/{repo_full_name}/pulls",
        headers=headers,
        json={
            "title": "demo: user_service with deliberate security vulnerabilities",
            "body": (
                "## AI Review Demo PR\n\n"
                "This PR was created automatically by `demo_pr.py` to demonstrate "
                "the AI code review agent.\n\n"
                "**Intentional issues planted in `src/user_service.py`:**\n"
                "- 🔒 SQL injection (2x — string formatting into queries)\n"
                "- 🔒 Hardcoded API key and admin password\n"
                "- ✨ Bare `except:` swallowing all exceptions\n"
                "- ✨ Unused import (`requests` imported but not meaningfully used)\n"
                "- ✨ Manual index loop instead of `enumerate`\n\n"
                "_The bot should catch all of these._"
            ),
            "head": branch_name,
            "base": default_branch,
        },
        timeout=15,
    )
    pr_resp.raise_for_status()
    pr_number = pr_resp.json()["number"]
    pr_url = pr_resp.json()["html_url"]
    log.info("demo_pr.pr.created", pr=pr_number, url=pr_url)
    print(f"\n✅ Demo PR created: {pr_url}")

    return pr_number, head_sha, branch_name


def cleanup_demo_prs(repo_full_name: str) -> None:
    """
    Close any open demo PRs and delete their branches.
    Looks for PRs and branches matching the 'demo/ai-review-test-*' pattern.
    """
    from github_client.auth import generate_jwt

    jwt_token = generate_jwt()
    token = _get_installation_token(repo_full_name, jwt_token)
    headers = _get_auth_headers(token)

    # Close open demo PRs
    prs_resp = httpx.get(
        f"https://api.github.com/repos/{repo_full_name}/pulls",
        headers=headers,
        params={"state": "open", "per_page": 50},
        timeout=15,
    )
    prs_resp.raise_for_status()
    demo_prs = [p for p in prs_resp.json()
                if p["head"]["ref"].startswith("demo/ai-review-test-")]

    for pr in demo_prs:
        httpx.patch(
            f"https://api.github.com/repos/{repo_full_name}/pulls/{pr['number']}",
            headers=headers,
            json={"state": "closed"},
            timeout=10,
        )
        print(f"  Closed PR #{pr['number']}: {pr['title'][:60]}")

    # Delete demo branches
    refs_resp = httpx.get(
        f"https://api.github.com/repos/{repo_full_name}/git/matching-refs/heads/demo/ai-review-test-",
        headers=headers,
        timeout=15,
    )
    refs_resp.raise_for_status()
    for ref in refs_resp.json():
        branch = ref["ref"].replace("refs/heads/", "")
        httpx.delete(
            f"https://api.github.com/repos/{repo_full_name}/git/refs/heads/{branch}",
            headers=headers,
            timeout=10,
        )
        print(f"  Deleted branch: {branch}")

    print(f"\n✅ Cleanup complete — closed {len(demo_prs)} PR(s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create a demo PR with deliberate issues and run the AI review on it.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create PR, print review findings (don't post comments to GitHub)
  python demo_pr.py --repo owner/AI-Review_Test --dry-run

  # Full demo — create PR and post real inline comments
  python demo_pr.py --repo owner/AI-Review_Test

  # Clean up demo PRs and branches
  python demo_pr.py --repo owner/AI-Review_Test --cleanup
        """,
    )
    parser.add_argument("--repo", required=True,
                        help='Target repo in "owner/repo" format, e.g. meteor0715/AI-Review_Test')
    parser.add_argument("--dry-run", action="store_true",
                        help="Print review findings without posting comments to GitHub")
    parser.add_argument("--cleanup", action="store_true",
                        help="Close open demo PRs and delete demo branches, then exit")
    args = parser.parse_args()

    if args.cleanup:
        print(f"🧹 Cleaning up demo PRs on {args.repo}…")
        try:
            cleanup_demo_prs(args.repo)
        except Exception as exc:
            print(f"❌ Cleanup failed: {exc}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    print(f"🚀 Creating demo PR on {args.repo}…")
    print("   (Ollama must be running with llama3 + nomic-embed-text)")

    try:
        pr_number, head_sha, branch_name = create_demo_pr(args.repo)
    except Exception as exc:
        print(f"\n❌ Failed to create demo PR: {exc}", file=sys.stderr)
        log.error("demo_pr.create.failed", error=str(exc))
        sys.exit(1)

    # Small delay — GitHub needs a moment before the diff is available via API
    print("\n⏳ Waiting 3 seconds for GitHub to process the push…")
    time.sleep(3)

    print("\n🤖 Running AI review pipeline…")
    print("   (This takes 30–90 seconds depending on your Ollama model speed)\n")

    try:
        from local_runner import run_review_for_pr
        run_review_for_pr(args.repo, pr_number, dry_run=args.dry_run)
    except Exception as exc:
        print(f"\n❌ Review pipeline failed: {exc}", file=sys.stderr)
        log.error("demo_pr.review.failed", error=str(exc))
        sys.exit(1)

    if args.dry_run:
        print(f"\nℹ️  Branch '{branch_name}' and PR #{pr_number} left open.")
        print(f"   Run with --cleanup to remove them, or close manually on GitHub.")
    else:
        print(f"\n✅ Done! Check the PR on GitHub for inline comments.")
        print(f"   Run with --cleanup to close the PR and delete the branch.")
