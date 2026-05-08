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

## Troubleshooting

| Problem                                 | Fix                                                                  |
| --------------------------------------- | -------------------------------------------------------------------- |
| `ollama: command not found`             | Run `brew install ollama` again or restart terminal                  |
| `ModuleNotFoundError: langchain_ollama` | Run `pip install -r requirements.txt` in activated venv              |
| `Connection refused` on port 11434      | Ollama server isn't running — run `ollama serve`                     |
| pytest import errors                    | Make sure you're in the project root directory and venv is activated |
| `chromadb` install fails                | Try `pip install chromadb --no-cache-dir`                            |
| smee not receiving events               | Check webhook is set to "Active" in GitHub App settings              |

---

## Running tests in watch mode (re-runs on file save)

```bash
pip install pytest-watch
ptw tests/
```
