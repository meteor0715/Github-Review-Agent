from fastapi import APIRouter, Request, HTTPException
from app.diff_parser import parse_diff

router = APIRouter()


@router.post("/webhook")
async def webhook(request: Request):
    """
    Receives GitHub webhook events.
    Validates signature, filters PR events, and triggers the review pipeline.
    """
    # TODO: A3.3 — verify HMAC SHA-256 webhook signature
    # TODO: B3.3 — filter only opened / synchronize / reopened events
    # TODO: A4.1 — trigger full pipeline: diff parser → RAG → orchestrator → formatter → comment poster
    payload = await request.json()
    return {"received": True}
