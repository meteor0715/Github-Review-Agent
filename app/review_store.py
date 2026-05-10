"""
Review store — shared in-memory storage for recent review results.

Kept in its own module to avoid circular imports between main.py and webhook_handler.py.
Both files import from here; neither imports from the other.
"""
import time
from collections import deque

# Keep last 10 reviews in memory.
# deque with maxlen automatically discards the oldest when full.
# This is a simple in-memory store — fine for local dev/demo.
# A production system would use a database (PostgreSQL, SQLite).
_recent_reviews: deque = deque(maxlen=10)


def record_review(
    repo: str,
    pr: int,
    comments: int,
    state: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """
    Store a completed review result so the dashboard can display it.

    Args:
        repo:          Repository in "owner/repo" format
        pr:            PR number
        comments:      Number of inline comments posted
        state:         "success", "failure", or "error"
        model:         Ollama model name used (e.g. "llama3")
        input_tokens:  Approximate input tokens consumed (if available)
        output_tokens: Approximate output tokens generated (if available)
    """
    _recent_reviews.appendleft({
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "repo": repo,
        "pr": pr,
        "comments": comments,
        "state": state,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    })


def get_recent_reviews() -> list[dict]:
    """Return the last N reviews as a plain list."""
    return list(_recent_reviews)
