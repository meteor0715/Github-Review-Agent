# Milestone 4 — Integration & End-to-End Testing

## What this milestone covers

Milestone 4 wires all the components built in M2 and M3 into a single working
pipeline. Before M4, each component was tested in isolation. Now they run
together in the correct sequence. This milestone focuses on:

- Full pipeline wiring (webhook → diff parser → RAG → orchestrator → GitHub API)
- Error handling and retry logic
- Exponential back-off for transient failures
- Structured logging throughout the pipeline
- Integration testing — testing components wired together (not just in isolation)
- Commit status lifecycle (pending → success/failure)
- LangSmith tracing for LLM observability (B4.1)

---

## 1. What "Integration" Means

### System before M4

```
webhook_handler.py  → receives PR, parses payload, returns "accepted"   (stub)
orchestrator.py     → coordinates agents                                 (complete)
rag/retriever.py    → retrieves codebase context                        (complete)
comment_poster.py   → posts GitHub review                               (complete)
status_updater.py   → sets commit status badge                          (complete)
```

All the pieces existed but weren't connected. Like having an engine, wheels,
and a steering wheel in different rooms — none of them do anything useful alone.

### System after M4

```
GitHub PR event
      │
      ▼
webhook_handler.py
  ├── verify HMAC signature
  ├── parse PR payload
  ├── generate_jwt() → get_installation_token()
  ├── set_commit_status("pending")
  ├── _fetch_with_retry(diff_url)
  ├── parse_diff(raw_diff)
  ├── retrieve_context(raw_diff)      ← RAG
  ├── run_orchestrator(diff, context) ← agents
  ├── post_review_comments(...)       ← GitHub
  └── set_commit_status("success"/"failure")
```

One PR event now flows through the entire system. This is integration.

---

## 2. The Full Pipeline — Step by Step

### Step 1: Authentication (generate_jwt + get_installation_token)

Before making any GitHub API call, we need a valid token. But we can't use
a stored long-lived token — GitHub Apps use short-lived tokens for security.

```python
jwt_token = generate_jwt()                         # RSA-signed, valid 10 min
token = get_installation_token(inst_id, jwt_token) # Bearer token, valid 1 hour
```

This happens at the start of EVERY pipeline run. We don't cache the token
between runs because each token is only valid 1 hour, and runs are infrequent.

### Step 2: Signal "pending" immediately

```python
set_commit_status(token, repo, sha, "pending",
                  description="AI Review in progress…")
```

This appears in the PR's Checks section within milliseconds of the PR opening.
It reassures the PR author the bot is working, even though the LLM analysis
takes 15-30 seconds.

### Step 3: Fetch the diff

```python
diff_response = _fetch_with_retry(pr_data["diff_url"], token)
raw_diff = diff_response.text
```

GitHub provides a diff URL in the webhook payload. We fetch it with the
`Accept: application/vnd.github.v3.diff` header, which tells GitHub to return
raw unified diff format (not JSON).

### Step 4: Parse the diff

```python
parsed_diff = parse_diff(raw_diff)
```

Converts the raw text diff into structured data:

```python
[{
    "filename": "src/auth.py",
    "added_lines": "    query = f\"SELECT * FROM users WHERE name='{user}'\"\n",
    "hunks": [{"new_start": 5, "lines": [...]}]
}]
```

### Step 5: Retrieve RAG context

```python
rag_context = retrieve_context(raw_diff)
```

Queries ChromaDB for code chunks semantically similar to the diff. If
ChromaDB is empty (nothing indexed yet) or Ollama returns an error, we
catch the exception, log a warning, and continue with `rag_context = ""`.

```python
try:
    rag_context = retrieve_context(raw_diff)
except Exception as exc:
    log.warning("pipeline.rag.failed", error=str(exc))
    rag_context = ""  # non-fatal — review continues without context
```

This is a key design decision: **RAG failure is non-fatal**. The review
is less contextually aware, but still useful. The alternative — failing the
whole review because ChromaDB is down — would be a much worse user experience.

### Step 6: Run the orchestrator

```python
result = run_orchestrator(parsed_diff, rag_context)
# → {"summary": str, "comments": list[dict]}
```

The orchestrator calls the code analysis agent, formatter, and summary builder
in sequence. This was already implemented in M2.

### Step 7: Post the review

```python
post_review_comments(token, repo, pr_num, comments, summary, sha)
```

Submits the review to GitHub's Pull Request Review API. If there are no
findings, we still post so the summary (e.g. "No issues found") appears.

### Step 8: Set final status

```python
high_count = sum(1 for c in comments if "🔴" in c.get("body", ""))
state = "failure" if high_count > 0 else "success"
set_commit_status(token, repo, sha, state, description=desc)
```

We set `failure` if any HIGH severity issue was found — this makes the PR
check badge red, drawing attention. LOW/MEDIUM findings produce `success`
(informational, not blocking).

---

## 3. Retry Logic and Exponential Back-off

### Why do we need retry?

External services fail transiently. Network blips, GitHub API returning 503,
Ollama being temporarily overloaded — all of these happen in production.
Without retry, a single transient error causes the entire review to fail.

### Exponential back-off pattern

```python
def _fetch_with_retry(url, token, retries=MAX_RETRIES):
    for attempt in range(retries + 1):
        try:
            response = httpx.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            if attempt == retries:
                raise   # give up after all retries exhausted
            wait = RETRY_BACKOFF ** attempt  # 2^0=1s, 2^1=2s, 2^2=4s
            log.warning("fetch.retrying", attempt=attempt+1, wait=wait)
            time.sleep(wait)
```

With `MAX_RETRIES=2` and `RETRY_BACKOFF=2`:

- Attempt 0: fails → wait 1 second (2^0)
- Attempt 1: fails → wait 2 seconds (2^1)
- Attempt 2: fails → raise (give up)
- Total wait time: 3 seconds before giving up

### Why "exponential" and not fixed delay?

If many servers hit a struggling service at fixed intervals, they'll all
retry at the same moment, creating a new spike that overloads it again.
With exponential back-off, servers spread out their retries — the service
gets breathing room to recover. This is called the "thundering herd problem".

### Why we only retry HTTP fetches, not the LLM

Retrying an LLM call that failed is risky because:

1. LLM failures are usually due to resource constraints (out of memory) — retrying immediately makes it worse
2. An LLM failure should result in `state="error"` so the team knows to investigate

For HTTP calls to GitHub (which are lightweight), retrying is safe.

---

## 4. Error Handling Strategy

### The three levels of errors

```
1. Non-fatal, continue:
   - RAG retrieval fails → rag_context = "", log warning, keep going
   - A single file's analysis fails → skip that file, continue

2. Fatal, set error status, raise 500:
   - GitHub auth fails → can't do anything without a token
   - Diff fetch fails after all retries → no diff = no review
   - Orchestrator crashes → unexpected bug, needs investigation

3. Ignored, return 200:
   - Non-PR events (push, issue, label) → "ignored" response
   - PR actions we don't handle (closed, labeled) → "ignored" response
```

### Why we always return 200 for non-PR events

If our server returns non-2xx for events we don't handle, GitHub marks
those webhook deliveries as failures. After many failures, GitHub may
disable the webhook. By returning 200 with `{"status": "ignored"}`, we
tell GitHub "received, no action needed" — the correct behaviour.

### The error response flow

```python
try:
    # full pipeline
    ...
except Exception as exc:
    log.error("pipeline.failed", error=str(exc))
    set_commit_status(token, repo, sha, "error",
                      description="AI Review failed — check server logs")
    raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}")
```

Even when the pipeline crashes, we update the commit status to `error`.
This ensures the PR author always sees a status badge — never a "pending"
that stays forever.

---

## 5. Structured Logging with structlog

### What is structlog?

structlog formats log messages as key-value pairs (structured data) instead
of plain text strings. This makes logs machine-parseable and easy to filter.

```python
# Plain logging (hard to parse):
logging.info(f"Pipeline done for PR {pr_num} in repo {repo} with {n} comments")

# structlog (machine-parseable):
log.info("pipeline.done", pr=pr_num, repo=repo, comments=n)
```

Output (JSON format):

```json
{
  "event": "pipeline.done",
  "pr": 42,
  "repo": "owner/repo",
  "comments": 3,
  "level": "info"
}
```

### Why structured logs matter for debugging

When something goes wrong at 3am:

```
# With plain logging:
"Error in pipeline"  ← which pipeline? which PR? which repo?

# With structlog:
{"event": "pipeline.failed", "error": "Connection refused", "repo": "owner/repo", "pr": 42}
← immediately know: PR 42 in owner/repo, connection refused
```

You can filter structured logs by field:

```bash
# Show only failures for a specific repo
cat app.log | jq 'select(.event == "pipeline.failed" and .repo == "owner/repo")'
```

### Event naming convention

We use dot-notation to create a hierarchy:

```
webhook.signature.invalid     ← webhook → signature → what happened
pipeline.rag.failed           ← pipeline → rag → what happened
orchestrator.analysis.done    ← which component → what phase → done/start/failed
```

This makes it easy to grep for categories:

```bash
grep "pipeline.rag" app.log    # all RAG-related events
grep ".failed" app.log         # all failures
```

---

## 6. Integration Testing

### Unit test vs Integration test

```
Unit test:
  - Tests ONE function
  - All dependencies mocked
  - Fast (milliseconds)
  - Catches bugs IN the function

Integration test:
  - Tests MULTIPLE functions together
  - Only external services mocked (GitHub, Ollama)
  - Slower (seconds)
  - Catches bugs at the SEAMS between functions
```

### What our integration tests verify

```python
test_pipeline_produces_comments_for_diff:
  diff_parser.parse_diff → run_orchestrator → format_review_comments
  Verifies: the three components pass data correctly between them

test_pipeline_posts_comments_to_github:
  run_orchestrator → post_review_comments → httpx.post (mocked)
  Verifies: comment_poster receives correctly shaped data from the orchestrator

test_pipeline_handles_empty_diff_gracefully:
  parse_diff("") → run_orchestrator([])
  Verifies: no crash on edge case, returns empty comments

test_commit_status_pending_then_success:
  set_commit_status("pending") → set_commit_status("success")
  Verifies: the full status lifecycle works without error
```

### Why mock at the HTTP boundary (not at the function boundary)

```python
# Too fine-grained (mocking too low — brittle):
@patch("agents.formatter_agent.format_review_comments")
# → If we rename the function, the test breaks even if behaviour is unchanged

# Right level (mocking at the external service boundary):
@patch("github_client.comment_poster.httpx.post")
# → We test all our code; only the HTTP call to GitHub is fake
```

Mocking at the HTTP boundary tests the maximum amount of real code while
keeping tests deterministic. The mock represents the boundary between
"our code" and "the outside world".

---

## 7. Commit Status Lifecycle

### The four valid states

```
pending  → shown as ⏳ (grey circle with clock) — review in progress
success  → shown as ✅ (green checkmark)         — review done, no HIGH issues
failure  → shown as ❌ (red X)                   — review done, HIGH issues found
error    → shown as ⚠️  (orange triangle)         — pipeline crashed
```

### When to use failure vs error

```
failure: the review COMPLETED but found serious issues
         → expected outcome, PR author should fix the issues

error:   the review CRASHED — did not complete
         → unexpected, someone needs to look at the server logs

Don't use failure for crashes — it suggests issues were found when actually
the bot just broke. error is the semantically correct state.
```

### The `context` field as a status identifier

```python
set_commit_status(..., context="ai-review-agent")
```

If you call this twice with the same `context`, GitHub shows ONE status badge
(updated in-place), not two. If you use different context strings, GitHub
shows multiple separate check lines. Always use the same context string to
avoid polluting the PR checks with duplicate entries.

---

## 8. LangSmith Tracing (B4.1)

### What is LangSmith?

LangSmith is Langchain's observability platform. Every LangChain chain
invocation can be automatically traced — you can see:

- What prompts were sent to the LLM
- What the LLM returned
- How long each call took
- Token counts and costs

### Setup

In `.env`:

```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_...   ← get from smith.langchain.com (free tier)
LANGCHAIN_PROJECT=github-review-agent
```

No code changes needed — LangChain auto-detects these env vars and sends
traces to LangSmith. Every `chain.invoke()` call appears in the dashboard.

### What you can see in LangSmith

```
Run: "Bug Analysis"
  ├── Prompt sent:   "Analyse this code for bugs: ..."
  ├── LLM response:  '[{"line": 5, "message": "Null pointer possible"}]'
  ├── Duration:      4.2s
  └── Token usage:   input=450, output=87
```

This is invaluable for prompt tuning. You can see exactly what the LLM
received and returned, identify where the JSON parsing fails, and compare
responses across different prompts.

### LangSmith vs print debugging

```python
# Without LangSmith (hard):
print("LLM response:", response)  # buried in terminal output
# → loses history across runs, no timing, no filtering

# With LangSmith (easy):
# → web dashboard, searchable history, timing graphs, side-by-side comparison
```

---

## Interview Questions — Milestone 4 Topics

---

**Q1: What is the difference between a unit test and an integration test? When do you use each?**

> A unit test tests a single function or class in isolation, with all external
> dependencies mocked. It runs in milliseconds and precisely identifies bugs
> in the function under test. An integration test tests multiple components
> wired together, mocking only truly external services (HTTP endpoints, databases).
> It runs slower but catches bugs at the seams between components — e.g. the
> orchestrator returns the wrong shape that comment_poster can't handle.
> We use unit tests for every component's internal logic and integration tests
> to verify the pipeline composition is correct.

---

**Q2: What is exponential back-off and why is it preferred over fixed-delay retry?**

> Exponential back-off increases the wait time between retries by a multiplier
> each attempt (e.g. 1s, 2s, 4s). Fixed delay retries wait the same time each
> attempt. The problem with fixed delays under high load: if many clients retry
> at the same fixed interval, they create simultaneous retry spikes that prevent
> the overloaded service from recovering. Exponential back-off spreads retries
> across time, giving the service breathing room. This solves the "thundering
> herd" problem. Adding random jitter (±some random ms) further desynchronises
> retries across multiple clients.

---

**Q3: How do you decide what to retry vs what to fail immediately?**

> Retry on transient errors — network timeouts, connection resets, HTTP 5xx
> from external services (which indicate temporary overload, not permanent error).
> Fail immediately on permanent errors — HTTP 401/403 (auth is wrong, retrying
> won't help), HTTP 404 (resource doesn't exist, retrying won't help), validation
> errors in our data (retrying the same bad input gets the same error). In our
> pipeline, we retry the GitHub diff fetch (transient network) but don't retry
> auth failures (would loop futilely) or LLM failures (resource pressure).

---

**Q4: Why is RAG failure treated as non-fatal in your pipeline?**

> RAG provides additional context to improve review quality but isn't required
> for a review to be useful. If ChromaDB is down or the embedding model fails,
> the LLM can still analyse the diff itself — just without full codebase context.
> Making RAG failure fatal would mean one ChromaDB error disables the entire
> code review system. The degraded experience (review without RAG context) is
> far better than no review at all. We log a warning so the team knows RAG is
> degraded, but the pipeline continues. This is the design principle of
> "graceful degradation".

---

**Q5: What is structured logging and why use it over print statements or basic logging?**

> Structured logging emits log events as key-value pairs (often JSON) rather
> than free-form strings. For example: `log.info("pipeline.done", pr=42, repo="owner/repo")`
> produces `{"event": "pipeline.done", "pr": 42, "repo": "owner/repo"}`.
> Benefits over plain strings: machine-parseable (grep/jq/Kibana can filter by
> field), consistent format, easy to add fields without breaking parsers, no
> string interpolation errors. In production, logs go to aggregation systems
> (Datadog, CloudWatch, Loki) that require structured data to build dashboards
> and alerts. `structlog` is the standard Python library for this.

---

**Q6: When should you use "failure" vs "error" as the GitHub commit status state?**

> "failure" means the check ran to completion and determined the code has problems
> — the expected outcome when the LLM finds HIGH severity issues. "error" means
> the check itself broke unexpectedly — an unhandled exception, auth failure, or
> crash. From the PR author's perspective: "failure" means "fix your code",
> "error" means "the bot is broken, someone alert the team". Using "failure" for
> crashes is misleading because it implies issues were detected when actually the
> bot just crashed. Semantic precision here matters for trust in the tool.

---

**Q7: Why do you set commit status to "pending" before starting the LLM analysis?**

> The LLM analysis takes 15-30 seconds. Without "pending", the PR opens and
> nothing appears in the Checks section — the PR author might think the bot
> isn't installed, is broken, or simply didn't run. Setting "pending" immediately
> provides visual feedback that work is in progress. This is identical to how
> every CI system works: GitHub Actions, CircleCI, and Jenkins all set "pending"
> the moment a run starts. It's a fundamental UX principle for async systems:
> always acknowledge receipt and progress, don't leave users wondering.

---

**Q8: What is the "thundering herd" problem?**

> When many clients (servers, processes) all fail at the same time and retry
> at the same fixed interval, they all hit the struggling service simultaneously,
> creating a new load spike that re-triggers the failure. The herd of retrying
> clients "thunders" into the service together, preventing recovery. Solutions:
> exponential back-off (each client waits longer each attempt), plus random
> jitter (each client waits a slightly different random duration so they desync).
> At the scale of our project (one server) this is less critical, but it's a
> standard distributed systems concept interviewers expect senior candidates to know.

---

**Q9: What is LangSmith and how does it help with prompt engineering?**

> LangSmith is LangChain's observability platform that automatically traces every
> LLM chain call. For each run it shows: the exact prompt sent, the raw LLM
> response, duration, and token counts — no code changes required beyond setting
> env vars. This is invaluable for prompt tuning because you can see exactly what
> the LLM received and returned across many runs, identify patterns in failures
> (e.g. the JSON parser always fails when the LLM adds extra text), and do
> side-by-side comparisons of different prompt versions. Without it, you'd have
> to add print statements and re-run manually.

---

**Q10: Why should webhook handlers return 200 for events they don't handle?**

> If your server returns 4xx or 5xx for events you don't handle, GitHub marks
> those deliveries as failed. After repeated failures, GitHub may disable the
> webhook or reduce delivery frequency. By returning 200 with a body like
> `{"status": "ignored", "reason": "event type 'push' not handled"}`, you tell
> GitHub "received, understood, no action needed" — semantically correct.
> 200 means "the server handled the message successfully", which is true:
> we successfully decided to do nothing with it.

---

**Q11: Explain the pipeline's authentication flow from webhook receipt to API call.**

> When a webhook arrives: 1) Verify HMAC signature (proves it's from GitHub). 2) Extract the installation_id from the payload — this identifies which
> installation of the app (which repo/org) sent the event. 3) Call generate_jwt()
> to create a 10-minute RS256 JWT signed with our private key. 4) POST that JWT
> to GitHub's `/app/installations/{id}/access_tokens` to exchange for a 1-hour
> installation token. 5) Use that installation token as `Authorization: Bearer`
> header for all subsequent API calls (posting comments, setting status).
> This happens fresh on every webhook event to ensure the token is always valid.

---

**Q12: How do you determine the severity level to set commit status to failure vs success?**

> We inspect the body of each generated comment for the 🔴 emoji or "[HIGH]" tag,
> which the formatter agent adds to HIGH severity findings. If any comment contains
> that marker, we set state="failure". Otherwise, state="success". This ties the
> CI badge directly to finding severity rather than just finding count — a PR with
> 10 LOW quality suggestions still gets "success" (informational), while a PR with
> 1 hardcoded secret gets "failure" (blocking). This is consistent with how human
> reviewers work: quality suggestions are advisory, security issues block merge.
