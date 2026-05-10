"""
Webhook Handler — receives GitHub App webhook events and triggers the review pipeline.

What is a webhook?
-------------------
A webhook is GitHub calling YOUR server when something happens.
It's the opposite of polling (you repeatedly asking GitHub "anything new?").

Webhooks are:
  - Event-driven: GitHub calls you exactly when a PR is opened/updated
  - Efficient: no wasted requests checking for events that haven't happened
  - Standard: used by GitHub, Stripe, Slack, Twilio — every major platform

The danger of webhooks:
------------------------
Anyone on the internet could POST to your /webhook endpoint pretending to be GitHub.
GitHub prevents this with an HMAC-SHA256 signature:
  - GitHub hashes the request body using your webhook secret as the key
  - Sends the hash in the X-Hub-Signature-256 header
  - You compute the same hash and compare — if they match, it's really GitHub

This is called "webhook signature verification" and is security-critical.
Without it, an attacker could trigger fake PR reviews or worse.

Interview note: "We verify webhook authenticity using HMAC-SHA256 signature
verification. The webhook secret is an HMAC key shared only between our server
and GitHub. We use hmac.compare_digest() instead of == to prevent timing attacks."

What is a timing attack?
------------------------
If you use == to compare strings, Python stops at the first mismatch.
An attacker can measure how long the comparison took — longer = more matching chars.
hmac.compare_digest() always takes the same time regardless of where mismatch is.
"""

import hashlib
import hmac
import json
import os
import time
import structlog
from fastapi import APIRouter, Request, HTTPException
from dotenv import load_dotenv

from app.diff_parser import parse_diff
from rag.retriever import retrieve_context
from agents.orchestrator import run_orchestrator
from github_client.auth import generate_jwt, get_installation_token
from github_client.comment_poster import post_review_comments
from github_client.status_updater import set_commit_status

load_dotenv()
log = structlog.get_logger()
router = APIRouter()

# How many times to retry when the LLM or GitHub API returns an error
MAX_RETRIES = 2
# Seconds to wait between retries (doubles each time — exponential back-off)
RETRY_BACKOFF = 2

# PR events that should trigger a review
TRIGGER_EVENTS = {"opened", "synchronize", "reopened"}


def _verify_signature(payload_bytes: bytes, signature_header: str) -> bool:
    """
    Verify GitHub's HMAC-SHA256 webhook signature.

    Args:
        payload_bytes: Raw request body bytes (MUST be raw bytes, not parsed JSON —
                       parsing then re-serialising could change byte order and break the hash)
        signature_header: Value of X-Hub-Signature-256 header from GitHub
                          Format: "sha256=<hex_digest>"

    Returns:
        True if signature is valid, False otherwise
    """
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        log.warning("webhook.signature.no_secret_configured")
        return False

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected_sig = signature_header[7:]  # strip "sha256=" prefix

    # Compute HMAC-SHA256 of the raw payload using the webhook secret
    mac = hmac.new(secret.encode(), payload_bytes, hashlib.sha256)
    computed_sig = mac.hexdigest()

    # compare_digest prevents timing attacks (always runs in constant time)
    return hmac.compare_digest(computed_sig, expected_sig)


def parse_pr_payload(payload: dict) -> dict | None:
    """
    Extract the relevant fields from a GitHub pull_request webhook payload.

    The full GitHub payload is large (100+ fields). We extract only what
    we need to run the pipeline.

    Args:
        payload: Parsed JSON body from the webhook POST

    Returns:
        Dict with extracted fields, or None if this isn't a PR event we handle
    """
    action = payload.get("action")
    if action not in TRIGGER_EVENTS:
        log.info("webhook.pr_action.skipped", action=action)
        return None

    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {})
    installation = payload.get("installation", {})

    return {
        "action": action,
        "pr_number": pr.get("number"),
        "pr_title": pr.get("title"),
        "base_sha": pr.get("base", {}).get("sha"),
        "head_sha": pr.get("head", {}).get("sha"),
        "diff_url": pr.get("diff_url"),          # URL to fetch the raw diff
        "repo_full_name": repo.get("full_name"), # "owner/repo"
        "installation_id": str(installation.get("id", "")),
    }


@router.post("/webhook")
async def webhook(request: Request):
    """
    Main webhook endpoint. GitHub POSTs here for all subscribed events.

    Flow:
      1. Read raw body bytes (needed for signature verification)
      2. Verify HMAC-SHA256 signature
      3. Check it's a pull_request event (not push/issue/etc.)
      4. Extract PR details
      5. Filter by action (opened/synchronize/reopened only)
      6. Trigger the review pipeline (in a later milestone — wired in M4)

    Why async?
    ----------
    FastAPI is built on asyncio. Marking the function `async` means FastAPI
    can handle other requests while this one is waiting for I/O (GitHub API,
    Ollama, ChromaDB). Without async, one slow request blocks the whole server.
    This is similar to async/await in C# — same concept, different syntax.
    """
    # Step 1: Read raw bytes FIRST — before any parsing
    # If we called request.json(), the body stream would be consumed and
    # we couldn't read it again for signature verification
    payload_bytes = await request.body()

    # Step 2: Verify signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(payload_bytes, signature):
        log.warning("webhook.signature.invalid")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Step 3: Check event type
    event_type = request.headers.get("X-GitHub-Event", "")
    if event_type != "pull_request":
        log.info("webhook.event.ignored", event_type=event_type)
        return {"status": "ignored", "reason": f"event type '{event_type}' not handled"}

    # Step 4: Parse payload
    payload = json.loads(payload_bytes)
    pr_data = parse_pr_payload(payload)

    if pr_data is None:
        return {"status": "ignored", "reason": "PR action not in trigger list"}

    log.info(
        "webhook.pr.received",
        repo=pr_data["repo_full_name"],
        pr=pr_data["pr_number"],
        action=pr_data["action"],
    )

    # ── Step 5: Run the full review pipeline ─────────────────────────────────
    # We run this asynchronously from the webhook handler's perspective —
    # we return 202 Accepted immediately and do the heavy work here.
    # In production you'd push to a task queue (Celery, ARQ).  For local dev
    # the synchronous call is fine because smee.io doesn't time out.

    repo    = pr_data["repo_full_name"]
    pr_num  = pr_data["pr_number"]
    sha     = pr_data["head_sha"]
    inst_id = pr_data["installation_id"]

    # 5a: Get a GitHub installation token so we can call the API
    try:
        jwt_token = generate_jwt()
        token     = get_installation_token(inst_id, jwt_token)
    except Exception as exc:
        log.error("pipeline.auth.failed", error=str(exc))
        raise HTTPException(status_code=500, detail="GitHub auth failed")

    # 5b: Signal to GitHub that the review is starting
    set_commit_status(token, repo, sha, "pending",
                      description="AI Review in progress…")
    log.info("pipeline.status.pending", repo=repo, pr=pr_num)

    try:
        # 5c: Fetch the raw diff from GitHub
        import httpx
        diff_url = pr_data["diff_url"]
        diff_response = _fetch_with_retry(diff_url, token)
        raw_diff = diff_response.text

        # 5d: Parse the diff into structured per-file data
        parsed_diff = parse_diff(raw_diff)
        log.info("pipeline.diff.parsed", files=len(parsed_diff))

        # 5e: Retrieve relevant codebase context via RAG
        try:
            rag_context = retrieve_context(raw_diff)
            log.info("pipeline.rag.done",
                     context_chars=len(rag_context) if rag_context else 0)
        except Exception as exc:
            # RAG failure is non-fatal — we continue without context
            log.warning("pipeline.rag.failed", error=str(exc))
            rag_context = ""

        # 5f: Run the orchestrator (analysis → format → summary)
        result = run_orchestrator(parsed_diff, rag_context)
        summary  = result["summary"]
        comments = result["comments"]
        log.info("pipeline.orchestrator.done",
                 comments=len(comments), summary_chars=len(summary))

        # 5g: Post the review to GitHub
        if comments or summary:
            post_review_comments(token, repo, pr_num, comments, summary, sha)
            log.info("pipeline.review.posted", repo=repo, pr=pr_num)

        # 5h: Set final commit status
        high_count = sum(
            1 for c in comments
            if "🔴" in c.get("body", "") or "[HIGH]" in c.get("body", "")
        )
        if high_count > 0:
            desc  = f"AI Review complete — {high_count} HIGH issue(s) found"
            state = "failure"
        else:
            desc  = f"AI Review complete — {len(comments)} finding(s), 0 HIGH"
            state = "success"

        set_commit_status(token, repo, sha, state, description=desc)
        log.info("pipeline.status.final", state=state, repo=repo, pr=pr_num)

        return {
            "status": "accepted",
            "pr": pr_num,
            "repo": repo,
            "action": pr_data["action"],
            "comments_posted": len(comments),
            "review_state": state,
        }

    except Exception as exc:
        log.error("pipeline.failed", error=str(exc), repo=repo, pr=pr_num)
        set_commit_status(token, repo, sha, "error",
                          description="AI Review failed — check server logs")
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}")


def _fetch_with_retry(url: str, token: str, retries: int = MAX_RETRIES) -> "httpx.Response":
    """
    Fetch a URL with exponential back-off retry logic.

    Why retry?
    ----------
    - GitHub API occasionally returns 5xx transient errors
    - Network blips can cause connection errors
    - Ollama can time out under load

    Exponential back-off: wait 2s, then 4s, then give up.
    This prevents hammering a struggling service.

    Args:
        url:     The URL to GET (e.g. PR diff URL from GitHub)
        token:   GitHub installation token for Authorization header
        retries: Number of retries remaining

    Returns:
        httpx.Response on success

    Raises:
        httpx.HTTPStatusError: if all retries are exhausted
    """
    import httpx
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3.diff",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    for attempt in range(retries + 1):
        try:
            response = httpx.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            if attempt == retries:
                log.error("fetch.failed_all_retries", url=url, error=str(exc))
                raise
            wait = RETRY_BACKOFF ** attempt
            log.warning("fetch.retrying", attempt=attempt + 1,
                        wait_seconds=wait, error=str(exc))
            time.sleep(wait)

