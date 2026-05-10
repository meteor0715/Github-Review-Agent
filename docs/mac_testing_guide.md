# Mac Testing Guide — AI GitHub Review Agent

Step-by-step instructions to set up and test the project on your personal Mac.

---

## Prerequisites (one-time setup)

### 1. Install Homebrew (if not already installed)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 2. Install Python 3.11+

```bash
brew install python@3.11
python3 --version   # should print 3.11.x or higher
```

### 3. Install Ollama

```bash
brew install ollama
```

Start the Ollama server (runs in background):

```bash
ollama serve
```

Open a **new terminal tab** and pull the required models:

```bash
ollama pull llama3
ollama pull nomic-embed-text
```

Verify they work:

```bash
ollama run llama3 "say hello in one word"
# Should print: Hello
```

### 4. Install Docker Desktop

Download from: https://www.docker.com/products/docker-desktop/
Open Docker Desktop and wait until the whale icon in the menu bar stops animating.

---

## Project Setup

### 5. Clone the repo

```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
```

### 6. Create a Python virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

> You must run `source .venv/bin/activate` every time you open a new terminal for this project.
> You'll see `(.venv)` at the start of your prompt when it's active.

**Why a virtual environment?**
It creates an isolated Python environment just for this project. Without it, every Python project on your Mac shares the same packages — installing v1 for one project can break another that needs v2. `.venv` is listed in `.gitignore` so it never gets committed.

### 7. Install dependencies

```bash
pip install -r requirements.txt
```

### 8. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in:

```
GITHUB_APP_ID=<your app ID from GitHub App settings>
GITHUB_WEBHOOK_SECRET=<your webhook secret>
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
OLLAMA_EMBED_MODEL=nomic-embed-text
```

Leave `LANGCHAIN_API_KEY` blank for now — LangSmith tracing is optional.

---

## Testing — Milestone 2 (Agents)

### Run all unit tests (no Ollama needed)

The unit tests mock all LLM calls, so they run instantly without Ollama:

```bash
pytest tests/test_agents.py -v
```

Expected output:

```
tests/test_agents.py::TestLLMFactory::test_get_llm_returns_chat_ollama PASSED
tests/test_agents.py::TestParseJsonResponse::test_parses_clean_json PASSED
tests/test_agents.py::TestParseJsonResponse::test_parses_json_wrapped_in_code_fence PASSED
tests/test_agents.py::TestParseJsonResponse::test_returns_empty_list_for_no_array PASSED
tests/test_agents.py::TestParseJsonResponse::test_returns_empty_list_for_empty_array PASSED
tests/test_agents.py::TestParseJsonResponse::test_returns_empty_list_for_malformed_json PASSED
tests/test_agents.py::TestCodeAnalysisAgent::test_run_code_analysis_agent_skips_empty_files PASSED
tests/test_agents.py::TestFormatterAgent::test_format_review_comments_shape PASSED
tests/test_agents.py::TestFormatterAgent::test_format_review_comments_line_defaults_to_1 PASSED
tests/test_agents.py::TestFormatterAgent::test_format_review_comments_empty_findings PASSED
tests/test_agents.py::TestFormatterAgent::test_comment_body_contains_severity_and_category PASSED
tests/test_agents.py::TestFormatterAgent::test_build_review_summary_no_findings PASSED
tests/test_agents.py::TestOrchestrator::test_orchestrator_calls_all_sub_agents PASSED
tests/test_agents.py::TestOrchestrator::test_orchestrator_returns_correct_structure PASSED
```

If any test fails, the output will show exactly which assertion failed and why.

---

### Manual live test (Ollama must be running)

This actually calls Ollama and runs the full agent pipeline on a sample diff.

Make sure Ollama is running first:

```bash
ollama serve   # in a separate terminal, or check it's already running
```

Then run:

```bash
python3 - << 'EOF'
from agents.orchestrator import run_orchestrator

# A sample diff with an obvious security issue — hardcoded password
test_diff = [
    {
        "filename": "src/database.py",
        "added_lines": 'password = "supersecret123"\ndb.connect(host="localhost", password=password)\n',
        "hunks": [],
    }
]

print("Running orchestrator with test diff...")
result = run_orchestrator(test_diff, rag_context="")
print("\n--- SUMMARY ---")
print(result["summary"])
print("\n--- COMMENTS ---")
for c in result["comments"]:
    print(f"\nFile: {c['path']}, Line: {c['line']}")
    print(c["body"])
EOF
```

**Expected:** The security agent should flag the hardcoded password with a HIGH severity finding.

---

## Testing — Milestone 1 (Setup tasks — YOUR tasks on Mac)

### B1.1 — Verify GitHub App is registered

- Go to https://github.com/settings/apps — your app should appear
- Click the app → verify permissions are set: Pull Requests (R/W), Contents (Read), Commit statuses (R/W)

### B1.2 — Set up smee.io tunnel

Install smee client:

```bash
npm install --global smee-client
```

Go to https://smee.io and click "Start a new channel". Copy the channel URL (e.g. `https://smee.io/abc123xyz`).

In a separate terminal:

```bash
smee --url https://smee.io/abc123xyz --target http://localhost:8000/webhook
```

Go back to your GitHub App settings, paste the smee URL as Webhook URL, check "Active", save.

### B1.3 — Verify .env is populated

```bash
cat .env   # all required values should be filled in, no empty GITHUB_ fields
```

### B1.4 — ChromaDB spike test

```bash
python3 - << 'EOF'
import chromadb
from langchain_ollama import OllamaEmbeddings

# Create a ChromaDB collection
client = chromadb.Client()
collection = client.create_collection("spike-test")

# Embed a dummy document using Ollama
embeddings = OllamaEmbeddings(model="nomic-embed-text")
doc = "def connect_db(): pass  # connects to the database"
vector = embeddings.embed_query(doc)

# Store it
collection.add(documents=[doc], embeddings=[vector], ids=["doc1"])

# Query it back
results = collection.query(query_embeddings=[vector], n_results=1)
print("Retrieved:", results["documents"][0][0])
print("✅ ChromaDB + Ollama embeddings working!")
EOF
```

### B1.5 — Start the FastAPI server

```bash
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/ping in your browser — should return `{"status": "ok"}`.

---

## Testing — Milestone 3 (RAG + GitHub Integration + Diff Parser)

### Run all unit tests (no Ollama or GitHub needed)

```bash
pytest tests/test_rag.py tests/test_github_client.py -v
```

All calls to ChromaDB, Ollama, and GitHub API are mocked — runs instantly.

Expected: all tests pass with `PASSED` status.

---

### Manual diff parser test (no dependencies)

```bash
python3 - << 'EOF'
from app.diff_parser import parse_diff

sample = """\
diff --git a/src/app.py b/src/app.py
index abc..def 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,5 @@
 def connect():
+    password = "secret"
+    db.connect(password)
     return True
"""

result = parse_diff(sample)
print("Files parsed:", len(result))
print("Filename:", result[0]["filename"])
print("Added lines:", result[0]["added_lines"])
print("Hunk line numbers:", [(l["type"], l["line_no"]) for l in result[0]["hunks"][0]["lines"]])
EOF
```

Expected output:

```
Files parsed: 1
Filename: src/app.py
Added lines:     password = "secret"
    db.connect(password)

Hunk line numbers: [('context', 1), ('added', 2), ('added', 3), ('context', 4)]
```

---

### Manual RAG indexer test (Ollama must be running)

```bash
python3 - << 'EOF'
from rag.indexer import index_repository

# Index this project itself as a test
count = index_repository(".")
print(f"✅ Indexed {count} chunks into ChromaDB")
EOF
```

Then test retrieval:

```bash
python3 - << 'EOF'
from rag.retriever import retrieve_context

diff = "+password = 'secret'\n+db.connect(password)\n"
context = retrieve_context(diff)
if context:
    print("✅ Retrieved context:")
    print(context[:500])
else:
    print("⚠️  No context retrieved — did indexer run first?")
EOF
```

---

### Manual webhook signature test (no Ollama needed)

```bash
python3 - << 'EOF'
import hmac, hashlib, os

# Simulate what GitHub does when sending a webhook
secret = "test_secret"
payload = b'{"action": "opened"}'
mac = hmac.new(secret.encode(), payload, hashlib.sha256)
sig = "sha256=" + mac.hexdigest()

# Now test our verification
import sys
sys.path.insert(0, ".")
os.environ["GITHUB_WEBHOOK_SECRET"] = secret
from app.webhook_handler import _verify_signature
result = _verify_signature(payload, sig)
print("✅ Signature valid:", result)

# Test with wrong secret
wrong = _verify_signature(payload, "sha256=fakehash")
print("✅ Wrong signature rejected:", not wrong)
EOF
```

---

## Testing — Milestone 4 (Full Pipeline Integration)

Milestone 4 wires every component together:
`webhook → diff parser → RAG → orchestrator → GitHub comment poster + commit status`

### Run integration tests (no Ollama or GitHub needed — all mocked)

```bash
pytest tests/test_integration.py -v
```

Expected output:

```
tests/test_integration.py::TestFullPipeline::test_pipeline_produces_comments_for_diff PASSED
tests/test_integration.py::TestFullPipeline::test_pipeline_posts_comments_to_github PASSED
tests/test_integration.py::TestFullPipeline::test_pipeline_handles_empty_diff_gracefully PASSED
tests/test_integration.py::TestFullPipeline::test_clean_diff_produces_no_high_findings PASSED
tests/test_integration.py::TestFullPipeline::test_commit_status_pending_then_success PASSED
```

### Run ALL tests together

```bash
pytest tests/ -v
```

This runs all 3 test files (agents, rag, github_client, integration) and should
show 40+ passing tests.

---

### End-to-end live test (Ollama + GitHub App + smee required)

This is the real thing. Make sure all 3 terminals are running:

| Terminal | Command                                                               |
| -------- | --------------------------------------------------------------------- |
| 1        | `ollama serve`                                                        |
| 2        | `smee --url https://smee.io/YOUR_CHANNEL --path /webhook --port 8000` |
| 3        | `source .venv/bin/activate && uvicorn app.main:app --reload`          |

Then on your test GitHub repo:

1. Create a branch, add a Python file with a deliberate issue:

```bash
cat > test_security.py << 'EOF'
import sqlite3

def get_user(username):
    conn = sqlite3.connect("users.db")
    query = f"SELECT * FROM users WHERE name = '{username}'"
    conn.execute(query)

SECRET_KEY = "hardcoded_secret_12345"
EOF

git add test_security.py
git commit -m "test: add file with deliberate security issues"
git push origin your-branch
```

2. Open a Pull Request on GitHub from `your-branch` → `main`

3. Watch Terminal 3 (uvicorn) for the pipeline logs:

```
[info] webhook.pr.received repo=you/repo pr=1 action=opened
[info] pipeline.status.pending repo=you/repo pr=1
[info] pipeline.diff.parsed files=1
[info] pipeline.rag.done context_chars=0
[info] orchestrator.start files_in_diff=1
[info] orchestrator.analysis.done total_findings=2
[info] orchestrator.formatting.done total_comments=2
[info] pipeline.review.posted repo=you/repo pr=1
[info] pipeline.status.final state=failure repo=you/repo pr=1
```

4. Open the PR on GitHub — you should see:
   - ❌ `ai-review-agent` status badge (failure, because HIGH issues found)
   - Inline comments on the specific lines with the hardcoded secret and SQL injection

---

### Manually trigger via local_runner.py (no live webhook needed)

Once you have the `.env` filled in and Ollama running, you can test any PR:

```bash
python local_runner.py --repo owner/repo --pr 1
```

This fetches the PR diff via GitHub API and runs the full pipeline without
needing smee.io or a webhook event.

---

### Verify retry logic works

Test the exponential back-off by temporarily pointing to a bad URL:

```bash
python3 - << 'EOF'
import os
os.environ["GITHUB_APP_ID"] = "test"

from app.webhook_handler import _fetch_with_retry
import httpx

try:
    _fetch_with_retry("http://localhost:9999/nonexistent", "fake-token", retries=1)
except Exception as e:
    print(f"✅ Retry exhausted as expected: {type(e).__name__}")
EOF
```

Expected: `✅ Retry exhausted as expected: ConnectError`

---

### Verify commit status lifecycle

```bash
python3 - << 'EOF'
# Dry run — inspect the request without a real token
from unittest.mock import patch, MagicMock

with patch("github_client.status_updater.httpx.post") as mock_post:
    mock_post.return_value = MagicMock(status_code=201, json=lambda: {})
    from github_client.status_updater import set_commit_status
    set_commit_status("fake", "owner/repo", "abc123", "pending", "AI Review starting…")
    set_commit_status("fake", "owner/repo", "abc123", "success", "AI Review complete — 0 HIGH issues")
    print(f"✅ set_commit_status called {mock_post.call_count} times")
    for call in mock_post.call_args_list:
        print("  State:", call.kwargs["json"]["state"],
              "| Description:", call.kwargs["json"]["description"])
EOF
```

---

## Testing — Milestone 5 (Docker, Local Runner & Dashboard)

### One-command setup (first time on a new machine)

```bash
chmod +x setup.sh
./setup.sh
```

Expected output:

```
✅ Python found: 3.11.x
✅ Ollama found
✅ Docker found
✅ Virtual environment created
✅ Dependencies installed
✅ Docker services started
```

---

### Start Docker services (FastAPI + ChromaDB)

```bash
docker compose up --build -d
```

Verify both containers are healthy:

```bash
docker compose ps
# Expected:
# NAME                  STATUS                   PORTS
# ai-review-agent       Up (healthy)             0.0.0.0:8000->8000/tcp
# ai-review-chroma      Up (healthy)             0.0.0.0:8001->8000/tcp
```

Verify the app responds:

```bash
curl http://localhost:8000/ping
# Expected: {"status":"ok"}
```

---

### View the dashboard

Open in browser: **http://localhost:8000/dashboard**

Or check JSON:

```bash
curl http://localhost:8000/reviews
# Expected: {"reviews": []}  (empty until a real PR review runs)
```

After running a review (via local_runner or live webhook), the dashboard shows:

- Timestamp, repo, PR number, comment count, status badge, model name
- Auto-refreshes every 30 seconds

---

### Run local_runner.py — review any PR without a live webhook

Make sure Ollama is running and `.env` is filled in:

```bash
# Using --repo and --pr flags:
python local_runner.py --repo owner/yourrepo --pr 1

# Using a full URL:
python local_runner.py --url https://github.com/owner/repo/pull/42

# Dry run — print findings without posting to GitHub:
python local_runner.py --repo owner/repo --pr 1 --dry-run

# Index a local codebase first for better RAG context:
python local_runner.py --repo owner/repo --pr 1 --index-repo /path/to/codebase
```

Expected output:

```
============================================================
AI Review — owner/repo PR #1
============================================================

📋 SUMMARY
Found 2 issues: 1 HIGH (hardcoded password), 1 LOW (missing docstring).

💬 INLINE COMMENTS (2 total)

  [1] src/auth.py line 5
      🔴 [HIGH] [security] Hardcoded password detected...

  [2] src/utils.py line 12
      🟡 [LOW] [quality] Function has no docstring...

============================================================
```

---

### View Docker logs

```bash
# Follow all logs from the FastAPI container:
docker compose logs -f app

# ChromaDB logs:
docker compose logs -f chroma

# All services:
docker compose logs -f
```

### Stop and clean up

```bash
docker compose down          # stop containers, keep volumes (ChromaDB data)
docker compose down -v       # stop AND delete volumes (wipes ChromaDB index)
```

---

## Troubleshooting

| Problem                                 | Fix                                                                                                                       |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | --- | ------------------------------------ | --------------------------------------------------------------------------- |
| `ollama: command not found`             | Run `brew install ollama` again or restart terminal                                                                       |
| `ModuleNotFoundError: langchain_ollama` | Run `pip install -r requirements.txt` in activated venv                                                                   |
| `Connection refused` on port 11434      | Ollama server isn't running — run `ollama serve`                                                                          |
| pytest import errors                    | Make sure you're in the project root directory and venv is activated                                                      |
| `chromadb` install fails                | Try `pip install chromadb --no-cache-dir`                                                                                 |
| smee not receiving events               | Check webhook is set to "Active" in GitHub App settings                                                                   |     | `FileNotFoundError: private-key.pem` | Download .pem from GitHub App settings → place at `secrets/private-key.pem` |
| `ValueError: GITHUB_APP_ID`             | Fill in `GITHUB_APP_ID` in your `.env` file                                                                               |
| ChromaDB `Collection not found`         | Run the indexer manually before retriever: `python3 -c "from rag.indexer import index_repository; index_repository('.')"` |

---

## Running tests in watch mode (re-runs on file save)

```bash
pip install pytest-watch
ptw tests/
```
