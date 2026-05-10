"""
Local Runner — CLI tool to manually trigger a code review on any PR URL.

Why this tool exists
---------------------
During development and demos, you don't want to push real commits just to
trigger a webhook. This script lets you point at any PR URL and run the full
review pipeline locally — without smee.io, without a live webhook.

Useful for:
  - Demoing the agent to interviewers on any public PR
  - Debugging a specific PR that produced bad output
  - Running the pipeline manually to verify a config change

Usage:
    python local_runner.py --repo owner/repo --pr 42
    python local_runner.py --repo torvalds/linux --pr 1234 --dry-run
    python local_runner.py --repo owner/repo --pr 42 --index-repo /path/to/code
"""

import argparse
import sys
import os
import re

import structlog
from dotenv import load_dotenv

load_dotenv()
log = structlog.get_logger()


def _parse_pr_url(url: str) -> tuple[str, int]:
    """
    Parse a full GitHub PR URL into (repo_full_name, pr_number).

    Accepts both:
      https://github.com/owner/repo/pull/42
      owner/repo  +  42  (via --repo / --pr flags)
    """
    match = re.match(
        r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)", url
    )
    if not match:
        raise ValueError(
            f"Cannot parse PR URL: {url!r}\n"
            "Expected format: https://github.com/owner/repo/pull/42"
        )
    return match.group(1), int(match.group(2))


def run_review_for_pr(
    repo_full_name: str,
    pr_number: int,
    dry_run: bool = False,
    index_repo_path: str | None = None,
) -> dict:
    """
    Fetch the diff for the given PR and run the full review pipeline.

    Steps:
      1. Authenticate as GitHub App (JWT → installation token)
      2. Optionally index a local repo into ChromaDB for RAG context
      3. Fetch the PR diff from GitHub API
      4. Parse the diff into structured per-file data
      5. Retrieve RAG context from ChromaDB
      6. Run orchestrator (analysis → format → summary)
      7. Post review comments to GitHub (unless --dry-run)
      8. Update commit status

    Args:
        repo_full_name: "owner/repo" string
        pr_number:      PR number (integer)
        dry_run:        If True, print results but don't POST to GitHub
        index_repo_path: Optional local path to index into ChromaDB before review

    Returns:
        Dict with "summary", "comments", "state"
    """
    import httpx

    from github_client.auth import generate_jwt, get_installation_token
    from github_client.comment_poster import post_review_comments
    from github_client.status_updater import set_commit_status
    from app.diff_parser import parse_diff
    from agents.orchestrator import run_orchestrator

    # ── Step 0: optionally index a local repo for RAG context ─────────────────
    if index_repo_path:
        log.info("local_runner.indexing", path=index_repo_path)
        from rag.indexer import index_repository
        count = index_repository(index_repo_path)
        log.info("local_runner.indexing.done", chunks=count)

    # ── Step 1: authenticate ───────────────────────────────────────────────────
    log.info("local_runner.auth.start", repo=repo_full_name, pr=pr_number)
    jwt_token = generate_jwt()

    # Find the installation ID for this repo via the GitHub API
    owner = repo_full_name.split("/")[0]
    install_resp = httpx.get(
        f"https://api.github.com/repos/{repo_full_name}/installation",
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=15,
    )
    install_resp.raise_for_status()
    installation_id = str(install_resp.json()["id"])
    token = get_installation_token(installation_id, jwt_token)
    log.info("local_runner.auth.done")

    api_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # ── Step 2: fetch PR metadata (head SHA) ───────────────────────────────────
    pr_resp = httpx.get(
        f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}",
        headers=api_headers,
        timeout=15,
    )
    pr_resp.raise_for_status()
    pr_meta = pr_resp.json()
    head_sha = pr_meta["head"]["sha"]
    log.info("local_runner.pr_meta.fetched", sha=head_sha[:8])

    # ── Step 3: set pending status ─────────────────────────────────────────────
    if not dry_run:
        set_commit_status(token, repo_full_name, head_sha, "pending",
                          description="AI Review in progress (local runner)…")

    # ── Step 4: fetch diff ─────────────────────────────────────────────────────
    diff_resp = httpx.get(
        f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}",
        headers={**api_headers, "Accept": "application/vnd.github.v3.diff"},
        timeout=30,
    )
    diff_resp.raise_for_status()
    raw_diff = diff_resp.text
    log.info("local_runner.diff.fetched", chars=len(raw_diff))

    # ── Step 5: parse diff ─────────────────────────────────────────────────────
    parsed_diff = parse_diff(raw_diff)
    log.info("local_runner.diff.parsed", files=len(parsed_diff))

    # ── Step 6: RAG context ────────────────────────────────────────────────────
    try:
        from rag.retriever import retrieve_context
        rag_context = retrieve_context(raw_diff)
        log.info("local_runner.rag.done", chars=len(rag_context))
    except Exception as exc:
        log.warning("local_runner.rag.failed", error=str(exc))
        rag_context = ""

    # ── Step 7: run orchestrator ───────────────────────────────────────────────
    log.info("local_runner.orchestrator.start")
    result = run_orchestrator(parsed_diff, rag_context)
    summary = result["summary"]
    comments = result["comments"]
    log.info("local_runner.orchestrator.done",
             comments=len(comments), has_summary=bool(summary))

    # ── Step 8: print findings ─────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"AI Review — {repo_full_name} PR #{pr_number}")
    print(f"{'='*60}")
    print(f"\n📋 SUMMARY\n{summary or 'No summary generated.'}")
    print(f"\n💬 INLINE COMMENTS ({len(comments)} total)")
    for i, c in enumerate(comments, 1):
        print(f"\n  [{i}] {c.get('path', '?')} line {c.get('line', '?')}")
        print(f"      {c.get('body', '')[:200]}")
    print(f"\n{'='*60}")

    # ── Step 9: post to GitHub (unless dry-run) ────────────────────────────────
    if dry_run:
        print("\n⚠️  DRY RUN — nothing posted to GitHub")
        return {"summary": summary, "comments": comments, "state": "dry-run"}

    if comments or summary:
        post_review_comments(token, repo_full_name, pr_number,
                             comments, summary, head_sha)
        log.info("local_runner.review.posted")

    high_count = sum(1 for c in comments if "🔴" in c.get("body", ""))
    state = "failure" if high_count > 0 else "success"
    desc = (f"AI Review complete — {high_count} HIGH issue(s) found"
            if high_count else
            f"AI Review complete — {len(comments)} finding(s), 0 HIGH")
    set_commit_status(token, repo_full_name, head_sha, state, description=desc)
    log.info("local_runner.done", state=state)

    return {"summary": summary, "comments": comments, "state": state}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Manually trigger an AI PR review without a live webhook",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python local_runner.py --repo owner/repo --pr 42
  python local_runner.py --repo owner/repo --pr 42 --dry-run
  python local_runner.py --repo owner/repo --pr 42 --index-repo /path/to/codebase
  python local_runner.py --url https://github.com/owner/repo/pull/42
        """,
    )
    parser.add_argument("--repo", help="Repo in owner/repo format")
    parser.add_argument("--pr", type=int, help="PR number")
    parser.add_argument("--url", help="Full GitHub PR URL (alternative to --repo + --pr)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print results without posting to GitHub")
    parser.add_argument("--index-repo", metavar="PATH",
                        help="Index a local repo path into ChromaDB before reviewing")
    args = parser.parse_args()

    if args.url:
        repo, pr_num = _parse_pr_url(args.url)
    elif args.repo and args.pr:
        repo, pr_num = args.repo, args.pr
    else:
        parser.error("Provide either --url or both --repo and --pr")

    try:
        run_review_for_pr(repo, pr_num,
                          dry_run=args.dry_run,
                          index_repo_path=args.index_repo)
    except Exception as exc:
        log.error("local_runner.error", error=str(exc))
        print(f"\n❌ Error: {exc}", file=sys.stderr)
        sys.exit(1)
