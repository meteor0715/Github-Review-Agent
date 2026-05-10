# Challenges & How I Solved Them

Real problems encountered while building the AI GitHub Code Review Agent, and exactly how each one was diagnosed and fixed. These are the kinds of stories interviewers love — showing you can debug systems end-to-end.

---

## 1. LangChain Import Error — `langchain.text_splitter` Module Not Found

**What happened:**
After installing all dependencies and running tests, the RAG tests crashed immediately:

```
AttributeError: module 'rag' has no attribute 'indexer'
ModuleNotFoundError: No module named 'langchain.text_splitter'
```

**Why it happened:**
LangChain v0.2 split its monorepo into separate packages. `text_splitter` was moved out of the core `langchain` package into a new standalone package called `langchain-text-splitters`. Any code written targeting the old import path just broke silently on install.

**How I fixed it:**
Updated the import in `rag/indexer.py`:

```python
# Before (broken in langchain v0.2+)
from langchain.text_splitter import RecursiveCharacterTextSplitter

# After
from langchain_text_splitters import RecursiveCharacterTextSplitter
```

Added `langchain-text-splitters>=0.2.0` to `requirements.txt`.

**What I learned:**
Always pin major versions of fast-moving ML libraries. LangChain's package split is a good example of why `requirements.txt` should specify version ranges, not just package names.

---

## 2. Integration Tests Failing — Pydantic `ValidationError` When Mocking the LLM

**What happened:**
Unit tests for individual agents passed fine, but integration tests that wired everything together crashed with a cryptic pydantic error:

```
pydantic.v1.error_wrappers.ValidationError: 1 validation error for ChatOllama
```

This happened even though the LLM was mocked with `unittest.mock.MagicMock`.

**Why it happened:**
LangChain's LCEL pipe `|` operator validates types at chain construction time using Pydantic. When you mock `get_llm()` to return a plain `MagicMock`, LangChain's internal type checking rejects it because it doesn't satisfy the `BaseChatModel` interface that the pipe operator expects.

**How I fixed it:**
Instead of mocking the LLM layer (which triggers type validation), I moved the mock up one level — mocking `run_code_analysis_agent` and `build_review_summary` directly at the orchestrator level:

```python
# Broken: mocks LLM but fails pydantic validation in LCEL
with patch("agents.llm_factory.get_llm") as mock_llm:
    mock_llm.return_value = MagicMock()

# Fixed: mock the agent functions themselves, skip LLM entirely
with patch("agents.orchestrator.run_code_analysis_agent") as mock_agent:
    mock_agent.return_value = [{"severity": "HIGH", ...}]
```

**What I learned:**
When testing layered systems, mock at the boundary closest to your test's concern. Trying to mock too deep into a framework's internals often fights the framework's own validation logic.

---

## 3. Circular Import — `main.py` and `webhook_handler.py` Importing Each Other

**What happened:**
When FastAPI started, it crashed with:

```
ImportError: cannot import name 'record_review' from partially initialized module 'app.main'
```

**Why it happened:**
`main.py` imported `webhook_handler` (to register the router), and `webhook_handler` imported `review_store` state from `main.py`. Python's import system can't resolve circular dependencies — it partially initialises the first module, then fails when the second tries to import from it.

**How I fixed it:**
Extracted the shared state into its own module `app/review_store.py` — a thin file with just the `deque` buffer and two functions:

```
app/
  main.py           → imports review_store (to serve /reviews endpoint)
  webhook_handler.py → imports review_store (to record completed reviews)
  review_store.py   → standalone, imports nothing from app/
```

No circular dependency. Both main and webhook_handler can import from review_store freely.

**What I learned:**
Circular imports are usually a signal that two modules are too tightly coupled. The fix is almost always to extract the shared state or logic into a third module that neither of the original two owns.

---

## 4. Webhook Signature Mismatch — 401 on Every PR Event

**What happened:**
GitHub was sending webhooks but every request came back with a 401 and the logs showed:

```
[error] webhook.signature.invalid
```

**Why it happened:**
The `GITHUB_WEBHOOK_SECRET` in `.env` didn't match the secret configured in the GitHub App settings on GitHub.com. The webhook handler verifies every incoming request using HMAC-SHA256 — if the secrets don't match, the signature never validates.

**How I fixed it:**
Regenerated the webhook secret in GitHub App settings, then copied the exact same value into `.env`. Restarted the server. Signatures matched immediately.

**What I learned:**
Always treat the GitHub App settings page as the source of truth for webhook secrets. It's easy to think you're copy-pasting correctly but introduce invisible whitespace or a newline. I now validate by checking `echo -n "$GITHUB_WEBHOOK_SECRET" | wc -c` to confirm the character count matches.

---

## 5. GitHub App Not Receiving Events — No Webhooks Arriving at All

**What happened:**
The server was running, smee was connected, but opening a PR never triggered anything.

**Why it happened:**
I had registered the GitHub App but hadn't _installed_ it on the test repository. Registration and installation are two separate steps in GitHub's App model — registering creates the app globally, but it doesn't get permissions on any repo until you explicitly install it.

**How I fixed it:**
Went to GitHub App settings → **Install App** tab → selected the test repository → clicked Install. Webhooks started flowing immediately.

**What I learned:**
GitHub Apps have two distinct concepts: the App (global, defines permissions and webhook URL) and the Installation (per-repo, grants the app access). Many tutorials skip the installation step. Both steps are required before any webhook events fire.

---

## 6. GitHub Diff URL 302 Redirect — `httpx` Raising an Error

**What happened:**
The pipeline failed mid-run when trying to fetch the PR diff:

```
[error] pipeline.failed error='Too many redirects'
```

The URL `https://github.com/owner/repo/pull/N.diff` was returning a 302 redirect to `https://patch-diff.githubusercontent.com/...`.

**Why it happened:**
`httpx` — unlike `requests` — does **not** follow redirects by default. It raises an error instead. GitHub's diff URLs always redirect to a CDN, so every diff fetch was failing.

**How I fixed it:**
One-line fix in `_fetch_with_retry`:

```python
# Before
response = httpx.get(url, headers=headers, timeout=30)

# After
response = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
```

**What I learned:**
`httpx` and `requests` have different defaults for redirect behaviour — a common gotcha when migrating between them. Always check library defaults rather than assuming behaviour matches another library you know well.

---

## 7. GitHub Review API 422 — Inline Comment Line Numbers Invalid

**What happened:**
The full pipeline ran successfully (diff fetched, LLM analysis completed, summary generated) but the final step failed:

```
[error] pipeline.failed error="Client error '422 Unprocessable Entity' for url '.../pulls/6/reviews'"
```

**Why it happened:**
The GitHub Review API only accepts inline comments on lines that actually appear in the diff — specifically lines that were changed, or context lines immediately surrounding the change. The LLM was generating plausible-looking line numbers (e.g. line 42 of a file) that weren't part of the diff's reviewable range.

**How I fixed it:**
Added a fallback in `comment_poster.py`: if GitHub returns 422, retry the request with `"comments": []` (no inline comments) and instead append all findings to the review body text. The review still posts successfully, just without line-level anchoring:

```python
if response.status_code == 422 and comments:
    # Fallback: post as body-only review, no inline line comments
    fallback_payload = {
        "commit_id": commit_sha,
        "body": summary + formatted_findings,
        "event": "COMMENT",
        "comments": [],
    }
    response = httpx.post(url, json=fallback_payload, headers=headers)
```

**What I learned:**
The GitHub Review API is strict — it validates line numbers against the actual diff server-side. When integrating LLM output into external APIs, always build graceful fallbacks for cases where the LLM's output doesn't exactly match the API's constraints.

---

## 8. ChromaDB Container Unhealthy — Docker Health Check Failing

**What happened:**
`docker compose up` failed with:

```
✘ Container ai-review-chroma  Error  dependency chroma failed to start
dependency failed to start: container ai-review-chroma is unhealthy
```

**Why it happened:**
The health check in `docker-compose.yml` used `curl` to verify ChromaDB was responding:

```yaml
test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/heartbeat"]
```

The `chromadb/chroma` Docker image doesn't ship with `curl` — so the health check command itself failed on every attempt, causing Docker to mark the container unhealthy even though ChromaDB was running fine.

**How I fixed it:**
Removed the health check from the ChromaDB service entirely. Docker still starts chroma before the app service (`depends_on` ordering is preserved). The app's own retry logic handles any brief startup delay from ChromaDB.

**What I learned:**
Don't assume a Docker image has common Unix utilities like `curl` or `wget`. Minimal images often strip them out. Either use Python's `urllib` for health checks (if Python is available), or skip the health check and rely on application-level retries instead.

---

## 9. Ollama Connection Refused From Inside Docker Container

**What happened:**
Pipeline ran fine when using `local_runner.py` directly on the Mac, but failed every time when triggered via the Docker container:

```
[error] pipeline.failed  error='[Errno 111] Connection refused'
```

The error occurred at `orchestrator.analysis.start` — right when the LLM was first called.

**Why it happened:**
`ollama serve` by default binds to `127.0.0.1:11434` — the loopback interface. From the Mac itself, `localhost:11434` works fine. But a Docker container is a separate network namespace — it can't reach the Mac's loopback via `host.docker.internal` unless Ollama is listening on `0.0.0.0`.

**How I fixed it:**
Restart Ollama with the host flag:

```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

This makes Ollama listen on all interfaces, including the one Docker routes `host.docker.internal` through.

**What I learned:**
`localhost` inside a Docker container is the container's own loopback, not the host machine's. `host.docker.internal` is Docker's special DNS name that resolves to the host, but the host service must be listening on `0.0.0.0` (not `127.0.0.1`) to accept those connections.

---

## 10. LangSmith 401 Spam in Logs

**What happened:**
After the pipeline started working, the logs were flooded with repeating errors:

```
LangSmithMissingAPIKeyWarning: API key must be provided when using hosted LangSmith API
LangSmithAuthError: Authentication failed for https://api.smith.langchain.com/runs/multipart
```

These appeared dozens of times per request and made the real logs hard to read.

**Why it happened:**
LangChain v0.2+ enables LangSmith tracing by default if it detects the `LANGCHAIN_TRACING_V2` environment variable is set (or even just if LangSmith is importable). It then tries to phone home with traces — and fails noisily when there's no valid API key.

**How I fixed it:**
Added one line to `.env`:

```
LANGCHAIN_TRACING_V2=false
```

**What I learned:**
LangSmith is useful for debugging LLM chains but it's opt-in for a reason. Any library that makes network calls by default (without explicit configuration) is a liability in production — always check what an ML framework phones home with before deploying.
