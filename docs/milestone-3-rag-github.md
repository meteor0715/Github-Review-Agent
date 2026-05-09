# Milestone 3 — RAG + GitHub Integration

## What this milestone covers

Milestone 3 wires the project to the outside world. We build the RAG pipeline
that gives the LLM codebase context, and we build the full GitHub integration:
parsing diffs, verifying webhook security, and posting reviews as inline comments.

Topics covered:

- RAG (Retrieval-Augmented Generation) — full deep dive
- Vector databases and how similarity search works
- Text chunking strategies
- The unified diff format — how Git diffs are structured
- HMAC-SHA256 webhook signature verification
- Security: timing attacks and constant-time comparison
- GitHub Pull Request Review API vs Issue Comments API
- Commit Status API
- GitHub App installation tokens and Bearer authentication
- `async def` in FastAPI and why raw bytes matter for webhook verification

---

## 1. RAG — Retrieval-Augmented Generation

### The problem RAG solves

LLMs are trained on data up to a cutoff date and have no knowledge of YOUR
codebase. When reviewing a PR, the LLM only sees the CHANGED lines. But to
understand if something is truly a bug, it needs context:

```
PR diff:
  + user = get_user(request.user_id)
  + print(user.name)

Is this a bug? Depends on:
  - Can get_user() return None? (look at the function definition elsewhere)
  - Is user.name always populated? (look at the User model definition)
  - Is printing user data a security issue? (look at logging policy in the codebase)
```

Without RAG, the LLM guesses. With RAG, we retrieve the actual `get_user()`
definition and User model from the codebase and inject them into the prompt.

### RAG in two phases

**Phase 1 — Indexing (run once, or when code changes):**

```
Codebase files
      │
      ▼ read each file
Split into chunks (1000 chars, 200 overlap)
      │
      ▼ embed each chunk
  [0.12, -0.34, 0.87, ...]   ← vector representation of chunk's meaning
      │
      ▼ store in ChromaDB
  {chunk_text, vector, filename, chunk_index}
```

**Phase 2 — Retrieval (run for each PR review):**

```
PR diff (added lines)
      │
      ▼ extract clean text, embed it
  [0.11, -0.36, 0.85, ...]   ← vector of the diff's meaning
      │
      ▼ similarity search in ChromaDB
Find top-5 vectors closest to the diff vector
      │
      ▼ return their original text
"def get_user(user_id):\n    return db.query(User)..."   ← inject into agent prompt
```

---

## 2. Vector Databases and Similarity Search

### What is a vector?

An embedding model converts text into a fixed-length list of floating point numbers.
These numbers represent the text's meaning in a high-dimensional space.

```python
# Using nomic-embed-text via OllamaEmbeddings:
from langchain_ollama import OllamaEmbeddings
embeddings = OllamaEmbeddings(model="nomic-embed-text")

vector_1 = embeddings.embed_query("def connect_to_database():")
# → [0.12, -0.34, 0.87, 0.45, ... ]  (768 numbers)

vector_2 = embeddings.embed_query("establish a database connection")
# → [0.11, -0.36, 0.85, 0.44, ... ]  (similar! same meaning)

vector_3 = embeddings.embed_query("make a cup of coffee")
# → [-0.72, 0.41, -0.23, -0.67, ...] (very different! different meaning)
```

The math: similar meanings → vectors point in similar directions in 768D space.

### How similarity search works

ChromaDB stores vectors. When you query with a new vector, it computes the
distance between your query vector and all stored vectors, then returns the
closest ones.

Distance metric used: **L2 (Euclidean distance)**

```
L2 distance between two vectors A and B:
  distance = √( Σ (A[i] - B[i])² )

  Small distance = similar meaning
  Large distance = different meaning
```

This is exactly like distance between two points in 2D space
(Pythagorean theorem), but in 768 dimensions.

### Why ChromaDB and not Pinecone or Weaviate?

```
ChromaDB:
  ✅ Fully open source
  ✅ Runs locally — no internet, no account, no cost
  ✅ PersistentClient saves to disk between restarts
  ✅ Simple Python API
  ❌ Not designed for billions of vectors (fine for our use case)

Pinecone:
  ✅ Managed cloud service, scales to billions of vectors
  ✅ Very fast at scale
  ❌ Paid (free tier is limited)
  ❌ Data sent to Pinecone's servers (privacy concern for code)

Weaviate:
  ✅ Can run locally or in cloud
  ✅ Has built-in text vectorisation
  ❌ More complex setup
```

For a local development project reviewing private code, ChromaDB is the clear choice.

---

## 3. Text Chunking — Why and How

### Why we can't embed entire files

The embedding model has a token limit (typically 512-8192 tokens depending on model).
A large Python file might have 10,000+ tokens — too large to embed as one unit.

Also, embedding a 500-line file as one vector makes retrieval imprecise.
A query about database connections would retrieve the whole file, including
unrelated code about UI rendering.

### RecursiveCharacterTextSplitter explained

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,     # target size of each chunk in characters
    chunk_overlap=200,   # how many characters adjacent chunks share
    length_function=len, # use character count (not token count)
)
```

**"Recursive" means:** it tries to split on `['\n\n', '\n', ' ', '']` in order,
choosing the split point that keeps each chunk closest to `chunk_size` while
preserving semantic boundaries.

```
Priority 1: Split on \n\n (paragraph breaks — best semantic boundary)
Priority 2: Split on \n  (line breaks — still good)
Priority 3: Split on ' ' (spaces — last resort, keeps words intact)
Priority 4: Split on ''  (characters — absolute last resort)
```

This is much better than splitting at exactly 1000 characters because that
would often cut in the middle of a function:

```python
# BAD: Fixed character split — cuts mid-function
chunk 1: "def process_payment(amount, card_number):\n    # validate\n    if amount <=..."
chunk 2: "0:\n        raise ValueError('Invalid')\n    charge_card(card_number, amount)"

# GOOD: RecursiveCharacterTextSplitter — splits between functions
chunk 1: "def validate_input(data):\n    if not data:\n        raise ValueError('Empty')\n    return True\n"
chunk 2: "def process_payment(amount, card_number):\n    ...\n    return receipt\n"
```

### Chunk overlap explained

```
File content:
  ...function A code...  |  boundary  |  ...function B code...

Chunk 1 (chars 0-999):   [...function A code...|first 200 chars of B...]
Chunk 2 (chars 800-1799): [...last 200 of A...|...function B code...]
                          ←200 overlap→
```

The 200-character overlap ensures that if a function straddles a chunk boundary,
it appears FULLY in at least one chunk. Without overlap, the middle of a function
could disappear into the gap between chunks.

---

## 4. The Unified Diff Format

### What is a unified diff?

When you open a PR and click "Files changed", GitHub shows a unified diff.
This is the standard format Git uses to represent changes. We parse this to
know which lines were added and at what line numbers.

### Full anatomy of a unified diff

```
diff --git a/src/database.py b/src/database.py     ← file header
index a1b2c3d..e4f5g6h 100644                       ← git metadata (we skip this)
--- a/src/database.py                               ← old file path
+++ b/src/database.py                               ← new file path (we use this)
@@ -10,6 +10,9 @@ class Database:                   ← hunk header (key!)
     def __init__(self):                            ← context line (space prefix)
         self.host = "localhost"                    ← context line
-        self.password = "hardcoded123"             ← REMOVED line (- prefix)
+        self.password = os.getenv("DB_PASS")       ← ADDED line (+ prefix)
+        if not self.password:                      ← ADDED line
+            raise ValueError("DB_PASS not set")   ← ADDED line
         self.connect()                             ← context line
```

### Parsing the hunk header `@@ -10,6 +10,9 @@`

```
@@ -{old_start},{old_count} +{new_start},{new_count} @@

@@ -10,6 +10,9 @@
      ^^^                  old file: starts at line 10, shows 6 lines
              ^^^^         new file: starts at line 10, shows 9 lines
```

We capture `new_start` (10 in this example) and use it to number all lines
in the new file. We increment this counter for every context line and every
added line, but NOT for removed lines (they don't exist in the new file).

### Line number tracking in our parser

```python
new_line_no = int(hunk_match.group(1))  # start from hunk's new_start

for line in hunk_lines:
    if line.startswith("+"):
        # Added line — DOES exist in new file → increment
        record_as_added(line_no=new_line_no)
        new_line_no += 1

    elif line.startswith("-"):
        # Removed line — does NOT exist in new file → do NOT increment
        record_as_removed(line_no=None)

    else:
        # Context line — exists in new file → increment
        record_as_context(line_no=new_line_no)
        new_line_no += 1
```

Why track line numbers accurately? Because GitHub's inline comment API requires
the EXACT line number in the new file. If we're off by one, comments appear on
the wrong line.

---

## 5. HMAC-SHA256 Webhook Signature Verification

### Why signature verification is security-critical

Your `/webhook` endpoint is publicly accessible at the smee.io URL. Without
verification, anyone could:

- POST fake webhook events to trigger reviews on code they don't control
- Flood your server with fake "PR opened" events (DoS attack)
- Craft payloads that cause your agent to post misleading comments

Signature verification proves the request came FROM GitHub, not from an attacker.

### How HMAC works

HMAC = Hash-based Message Authentication Code

```
You and GitHub share a secret: "my_webhook_secret"

When GitHub sends a webhook:
  1. GitHub computes: HMAC_SHA256("my_webhook_secret", request_body_bytes)
  2. GitHub sends result in header: X-Hub-Signature-256: sha256=abc123...
  3. Your server computes the same: HMAC_SHA256("my_webhook_secret", request_body_bytes)
  4. If your result == GitHub's result → request is authentic
```

```python
import hmac, hashlib

def _verify_signature(payload_bytes: bytes, signature_header: str) -> bool:
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    expected_sig = signature_header[7:]  # strip "sha256=" prefix

    # Compute HMAC of the raw payload
    mac = hmac.new(secret.encode(), payload_bytes, hashlib.sha256)
    computed_sig = mac.hexdigest()

    # Compare using constant-time comparison (see timing attacks below)
    return hmac.compare_digest(computed_sig, expected_sig)
```

### CRITICAL: Why `await request.body()` must come BEFORE `await request.json()`

```python
@router.post("/webhook")
async def webhook(request: Request):
    # CORRECT ORDER:
    payload_bytes = await request.body()    # 1. Read raw bytes
    # ... verify signature using payload_bytes ...
    payload = json.loads(payload_bytes)    # 2. Parse JSON from bytes

    # WRONG ORDER (would break signature verification):
    payload = await request.json()          # ← body stream consumed!
    payload_bytes = await request.body()    # ← now empty! signature check fails
```

HTTP request bodies are **streams** — you can only read them once. If you parse
JSON first, the bytes are consumed. Calling `.body()` again returns empty bytes.
HMAC of empty bytes ≠ HMAC of original payload → signature check fails → 401.

### Timing attacks and `hmac.compare_digest()`

```python
# VULNERABLE (don't do this):
if computed_sig == expected_sig:

# Explanation of the attack:
# Python's == operator short-circuits on first mismatch.
# If computed_sig[0] != expected_sig[0], it returns False immediately.
# If computed_sig[0] == expected_sig[0] but [1] differs, it returns False slightly later.
#
# An attacker sends thousands of requests with varying first characters,
# measuring response time. Slightly slower = more matching characters.
# Over ~256 requests per character position, they reconstruct the full signature.
# This is a timing side-channel attack.

# SAFE (use this):
return hmac.compare_digest(computed_sig, expected_sig)
# compare_digest always takes the same time regardless of where mismatch occurs.
# Zero timing information leaks.
```

---

## 6. GitHub Pull Request Review API

### Two types of comments on a PR

```
1. Issue Comments  (POST /repos/{owner}/{repo}/issues/{number}/comments)
   → Appears at the BOTTOM of the PR conversation tab
   → Like a regular text comment anyone posts
   → No line attachment, no file context
   → Good for: general messages, bot status updates

2. Pull Request Reviews  (POST /repos/{owner}/{repo}/pulls/{number}/reviews)
   → Appears in the "Files changed" tab as inline code comments
   → Attached to a specific FILE and LINE NUMBER
   → Shows alongside the actual code change
   → Can include: APPROVE, REQUEST_CHANGES, or COMMENT event
   → Good for: inline code review feedback ← we use this
```

We use Reviews because inline comments are the standard for code review
tools (how GitHub's own review system works, how Copilot Code Review works,
how SonarQube GitHub integration works).

### Review event types

```python
body = {
    "event": "COMMENT",         # ← we use this (advisory, non-blocking)
    # "event": "APPROVE",       # adds green checkmark, allows merge
    # "event": "REQUEST_CHANGES" # blocks merge until author responds
}
```

We use `COMMENT` so our bot never blocks a PR. It's advisory. The team can
choose to ignore a finding. Being non-blocking is the right default for an
automated tool — it's a suggestion, not a gatekeeper.

### The `commit_id` field and why it matters

```python
body = {
    "commit_id": head_sha,  # REQUIRED — the PR's HEAD commit SHA
    "comments": [...],
}
```

GitHub uses `commit_id` to anchor inline comments to a specific version of the
code. Without it, GitHub doesn't know which version of the file to show the
comment on. If the PR is updated (new commits pushed), old comments stay anchored
to the commit they were made on — correct behaviour.

---

## 7. GitHub Commit Status API

### What is a commit status?

Every commit can have a badge shown in the PR checks section:

```
Checks:
  ✅ ci/tests (passing)
  ⏳ ai-review-agent (pending)   ← our bot sets this when review starts
  ✅ ai-review-agent (success)   ← our bot sets this when review completes
```

These are set via `POST /repos/{owner}/{repo}/statuses/{sha}`.

### Why set "pending" immediately?

```
Without pending status:
  PR opened → ... 30 seconds pass ... review comments appear
  PR author: "Is the bot broken? Did it run? Where are the results?"

With pending status:
  PR opened → bot immediately sets "AI Review in progress..." ← reassuring
  → ... 30 seconds pass ...
  → bot sets "Success — 2 findings, 0 HIGH issues"
```

This is standard UX for CI systems. Every CI tool (GitHub Actions, CircleCI)
sets "pending" the moment a run starts for exactly this reason.

### The `context` field

```python
set_commit_status(
    state="success",
    context="ai-review-agent",   # ← THIS is the display name in the PR
    description="AI Review complete — 0 HIGH issues",
)
```

The `context` is also used as an identifier. If you create a status with
`context="ai-review-agent"`, then update it with the same context, GitHub
updates the SAME status badge (doesn't create a second one). Use a consistent
context string on every call.

---

## 8. GitHub App Installation Tokens

### Why installation tokens expire in 1 hour

Short-lived tokens limit breach impact. If a token is:

- Logged accidentally → expires in at most 1 hour
- Intercepted in transit → expires quickly
- Leaked in an error message → minimal window for abuse

Compare to a PAT that might be valid indefinitely — one leak could mean months
of unauthorised access.

### When to refresh the token

Our current implementation gets a fresh token for each webhook event:

1. PR opens → get_installation_token() → use token → token expires
2. Next PR opens → get new token → use token → expires

This is slightly inefficient (an extra API call per PR) but simple and correct.
A production system would cache the token and refresh it proactively before
the 1-hour expiry. That's an optimisation for a later milestone.

### Bearer token authentication

```python
headers = {
    "Authorization": f"Bearer {installation_token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
```

**Bearer** authentication means "whoever bears (carries) this token is authorised".
The token itself IS the credential — no username/password needed.

**Why specify `X-GitHub-Api-Version`?**
GitHub versions their API. By specifying the version, you guarantee your code
continues working even if GitHub ships breaking API changes in a future version.
Without it, GitHub uses the latest version, which might change behaviour.

---

## 9. Async HTTP with httpx

### Why httpx instead of requests?

```python
# requests library (classic, sync only)
import requests
response = requests.post(url, json=body)  # blocks the thread until response

# httpx library (modern, supports both sync and async)
import httpx
response = httpx.post(url, json=body)   # sync (what we use in utils)
# or
async with httpx.AsyncClient() as client:
    response = await client.post(url)   # async (for production use in handlers)
```

We use sync `httpx` in our GitHub client utilities because they're called from
the orchestrator which is called from the async webhook handler — in Python,
you can call sync functions from async context fine (it blocks the async event
loop momentarily, acceptable for our scale).

For a high-traffic production server, you'd make all HTTP calls async to avoid
blocking the event loop.

---

## 10. `__init__.py` Files and Python Packages

### Why we added `__init__.py` to each folder

```
Without __init__.py:
  agents/
    orchestrator.py

  # In test file:
  from agents.orchestrator import run_orchestrator
  # → ModuleNotFoundError: No module named 'agents'
  # Python doesn't know 'agents/' is a package
```

```
With __init__.py:
  agents/
    __init__.py    ← empty file signals "this is a Python package"
    orchestrator.py

  from agents.orchestrator import run_orchestrator  # ✅ works
```

In Python 3.3+, there are "namespace packages" that work without `__init__.py`,
but pytest's import system is more reliable with explicit `__init__.py`.

### `conftest.py` and sys.path

```python
# conftest.py (project root)
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
```

pytest loads `conftest.py` automatically before any test. By inserting the
project root into `sys.path`, all imports like `from agents.orchestrator import ...`
work correctly from any test file. Without this, pytest might run from the
wrong directory and fail to find your modules.

---

## Interview Questions — Milestone 3 Topics

---

**Q1: What is RAG and how does it work in your project?**

> RAG (Retrieval-Augmented Generation) is a pattern that gives an LLM access to
> external knowledge it wasn't trained on. In two phases: first, we index the
> codebase by chunking files, embedding each chunk with nomic-embed-text into
> vectors, and storing in ChromaDB. When a PR comes in, we extract the meaningful
> text from the diff, embed that as a query vector, find the top-5 most similar
> chunks in ChromaDB (nearest neighbours), and inject that retrieved code as
> context into the agent prompt. This gives the agent knowledge of the full
> codebase, not just the changed lines — so it can understand whether a function
> call might return None, or whether a pattern conflicts with existing conventions.

---

**Q2: What is a vector embedding and how is similarity measured?**

> An embedding is a fixed-length list of floating-point numbers produced by a
> neural network that represents the semantic meaning of text. The embedding model
> is trained so texts with similar meanings produce vectors that are close together
> in the high-dimensional space. Similarity is typically measured by L2 (Euclidean)
> distance or cosine similarity. Cosine similarity measures the angle between
> vectors (independent of magnitude), which is often better for text similarity.
> ChromaDB defaults to L2 distance. A smaller distance means more similar meaning.

---

**Q3: Why do you chunk text before embedding instead of embedding entire files?**

> Two reasons. First, embedding models have token limits (typically 512-8192 tokens)
> — large files exceed this. Second, a full file embedded as one vector is too
> coarse for retrieval. A 200-line file contains many different topics. One vector
> representing the whole file would match many unrelated queries. Smaller chunks
> (1000 chars) make retrieval precise — a chunk about database connections is
> retrieved specifically for database-related queries, not every query about the file.

---

**Q4: What is chunk overlap and why is it important?**

> Chunk overlap means adjacent chunks share some characters at their boundary.
> With 200-char overlap: if chunk 1 is chars 0-999, chunk 2 is chars 800-1799.
> Without overlap, a function that straddles the boundary between chunk 1 and 2
> would appear split across both — neither chunk has the complete function.
> With overlap, the function's beginning appears at the end of chunk 1 AND the
> start of chunk 2, so it's fully represented in at least one chunk for retrieval.

---

**Q5: Explain the unified diff format and how your parser handles line numbers.**

> A unified diff has file headers (`diff --git`), file paths (`+++`), and hunks.
> Each hunk starts with `@@ -{old_start},{count} +{new_start},{count} @@` which
> tells us the starting line number in the new file. Lines with `+` prefix are
> added (we track these with incrementing line numbers), lines with `-` prefix are
> removed (they don't exist in the new file so we don't increment the counter),
> and unmodified context lines increment the counter. Accurate line numbers are
> critical because GitHub's inline comment API requires the exact line number in
> the new file to attach the comment.

---

**Q6: What is HMAC and why do we use it for webhook verification?**

> HMAC (Hash-based Message Authentication Code) lets two parties verify that a
> message came from the expected sender and wasn't tampered with. GitHub and our
> server share a secret key. When GitHub sends a webhook, it computes
> HMAC-SHA256 of the request body using the shared secret and includes the result
> in the `X-Hub-Signature-256` header. Our server computes the same HMAC and
> compares. If they match, the request is authentic — only someone who knows the
> secret could produce that signature. SHA256 is the hash function, and HMAC adds
> the keyed authentication on top of it.

---

**Q7: What is a timing attack and how do you prevent it?**

> A timing attack exploits the fact that string comparison with `==` returns
> False faster when strings differ early. By sending many requests with slightly
> varying signature values and precisely measuring response time, an attacker
> can determine how many leading characters of their guess match the correct
> signature. Enough measurements let them reconstruct the full signature without
> knowing the secret. We prevent this by using `hmac.compare_digest()` which
> always takes the same amount of time regardless of where (or if) strings differ,
> eliminating the timing side-channel.

---

**Q8: Why must you read `request.body()` before `request.json()` for webhook handling?**

> HTTP request bodies are streams — once read, the data is consumed and the stream
> pointer is at the end. If you call `request.json()` first, FastAPI reads and
> parses the body, but the raw bytes are gone. A subsequent call to `request.body()`
> returns empty bytes. HMAC-SHA256 of empty bytes is completely different from HMAC
> of the real payload, so signature verification fails. We must read raw bytes first,
> verify the signature with those bytes, then parse the JSON from the same bytes.

---

**Q9: What is the difference between PR Reviews and Issue Comments on GitHub, and why did you choose Reviews?**

> Issue Comments (POST /issues/{number}/comments) post a plain text comment at the
> bottom of the PR conversation — no file or line attachment. Pull Request Reviews
> (POST /pulls/{number}/reviews) support inline comments attached to specific files
> and line numbers in the "Files changed" view, alongside the actual code. We chose
> Reviews because inline feedback is the standard for code review tools — it's
> immediately visible in context, alongside the code that has the problem. It's
> how GitHub's own review interface, GitHub Copilot Code Review, and SonarQube
> GitHub integration all post feedback.

---

**Q10: What are GitHub App installation tokens, why do they expire, and how do you obtain them?**

> Installation tokens are short-lived credentials (valid 1 hour) that grant the
> GitHub App permission to make API calls on behalf of an installation (a specific
> repo or org). They're obtained by first signing a JWT with our RSA private key,
> then POSTing that JWT to `/app/installations/{id}/access_tokens`. GitHub verifies
> the JWT using our public key and returns the token. They expire in 1 hour to
> limit the impact of a leaked token — compare to a long-lived PAT where one leak
> could mean months of unauthorised access. Our current implementation fetches a
> fresh token per PR review; a production system would cache and refresh proactively.

---

**Q11: What is semantic search and how does it differ from keyword search?**

> Keyword search (like grep or SQL LIKE) finds exact word matches — it looks for the
> literal string "database connection" in the text. Semantic search uses embeddings
> to find text with similar MEANING, regardless of exact wording. For example, a
> query about "database connection error handling" would semantically match code with
> `try: db.connect() except ConnectionError:` even though those exact words don't
> appear. For code review context retrieval, semantic search is far more useful —
> the agent wants conceptually related code, not files that happen to contain
> specific keywords.

---

**Q12: What is the GitHub commit status API and why do you set "pending" status immediately?**

> The commit status API lets you set a named status badge (pending/success/failure/error)
> on any commit, visible in the PR's checks section. We set "pending" as the first
> thing when we receive a PR webhook because the LLM analysis takes 10-30 seconds.
> Without a pending status, the PR author sees nothing during that time and might
> think the bot isn't working. Setting "pending" immediately gives visual feedback
> that the review is in progress — standard UX practice used by every CI system
> (GitHub Actions, CircleCI, Travis CI). We then update to "success" or "failure"
> when the review completes.

---

**Q13: What is a Bearer token and how does it differ from other authentication methods?**

> Bearer authentication means "whoever bears (possesses) this token is authorised".
> The token is included in the `Authorization: Bearer <token>` header. The server
> trusts the token without any additional verification of the requester's identity —
> the token itself is the credential. Compare to: Basic auth (username + password
> encoded), API Key (custom header or query param), OAuth 2.0 (Bearer tokens but
> obtained through a user login flow). GitHub installation tokens use Bearer auth —
> we obtain the token via JWT exchange, then include it in every API call header.

---

**Q14: What is the `X-GitHub-Api-Version` header and why do you include it?**

> GitHub versions their REST API and ships breaking changes behind version dates.
> By specifying `X-GitHub-Api-Version: 2022-11-28`, our code uses the exact API
> behaviour from that date. If GitHub ships incompatible changes in a future version,
> our code continues working because we're pinned to a specific version. Without this
> header, GitHub uses the latest version, which could break in the future with no
> changes on our side. API versioning is a contract between API provider and consumer —
> specifying the version makes that contract explicit.
