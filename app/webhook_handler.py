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
import os
import structlog
from fastapi import APIRouter, Request, HTTPException
from dotenv import load_dotenv

from app.diff_parser import parse_diff

load_dotenv()
log = structlog.get_logger()
router = APIRouter()

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
    import json
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

    # Step 5: Trigger pipeline (wired fully in Milestone 4)
    # For now we return the extracted PR data so you can verify parsing works
    # TODO: M4 — call run_orchestrator and post comments
    return {
        "status": "accepted",
        "pr": pr_data["pr_number"],
        "repo": pr_data["repo_full_name"],
        "action": pr_data["action"],
    }

