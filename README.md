# AI-Powered GitHub Code Review Agent

A **multi-agent LLM system** that automatically reviews GitHub pull requests. When a PR is opened, it fetches the diff, retrieves relevant codebase context via RAG, runs three specialized AI agents (bugs, security, code quality), and posts structured inline comments directly on the PR — all running **100% locally** with no cloud API costs.

> Built with Python · FastAPI · LangChain · Ollama · ChromaDB · GitHub Apps API

---

## What It Does

1. **GitHub App receives a PR webhook** → validates HMAC-SHA256 signature
2. **Fetches the PR diff** → parses changed files and line numbers
3. **RAG retrieval** → pulls relevant codebase patterns from ChromaDB (nomic-embed-text embeddings)
4. **Three parallel analysis agents** (LangChain LCEL chains on Llama 3):
   - 🐛 Bug detection — logic errors, null dereferences, off-by-ones
   - 🔒 Security analysis — injections, hardcoded secrets, auth bypasses
   - ✨ Code quality — complexity, naming, missing docs
5. **Posts inline review comments** on the exact lines via GitHub Review API
6. **Sets commit status** (pending → success/failure) so the PR status badge updates

---

## Architecture

```
GitHub PR Event (opened / synchronize)
        │
        ▼  HMAC-SHA256 verified
 FastAPI Webhook Server  (/webhook)
        │
        ├─► Diff Parser          → extract changed files + line numbers
        ├─► RAG Retriever        → ChromaDB similarity search for context
        │
        ▼
 Orchestrator (LangChain)
        ├─► Bug Analysis Agent       ─┐
        ├─► Security Analysis Agent   ├─► JSON findings
        └─► Quality Analysis Agent   ─┘
                │
                ▼
        Formatter Agent  → GitHub Review API shape
                │
                ▼
        GitHub PR Review API  → inline comments + commit status
```

---

## Tech Stack

| Layer              | Technology                             |
| ------------------ | -------------------------------------- |
| API Server         | Python 3.11 + FastAPI + uvicorn        |
| LLM                | Ollama (local) — Llama 3               |
| Agent Framework    | LangChain LCEL chains                  |
| Embeddings         | nomic-embed-text via Ollama            |
| Vector DB          | ChromaDB (fully local, persistent)     |
| GitHub Integration | GitHub App JWT (RS256) + PyGithub      |
| HTTP Client        | httpx (async-safe, redirect-following) |
| Containerisation   | Docker + docker-compose                |
| Webhook Tunnel     | smee.io                                |
| Logging            | structlog (structured JSON)            |
| Testing            | pytest + unittest.mock (52 tests)      |

---

## Quick Start (Mac / Linux)

```bash
# One-command setup (installs deps, starts Docker services)
chmod +x setup.sh && ./setup.sh
```

Then open a new terminal and start the tunnel:

```bash
smee --url https://smee.io/<your-channel> --path /webhook --port 8000
```

Open a PR on your test repo — the bot will review it automatically.

### Windows

```powershell
.\setup.ps1
```

---

## Prerequisites

| Tool           | Version        | Install                                                  |
| -------------- | -------------- | -------------------------------------------------------- |
| Python         | 3.11+          | [python.org](https://python.org)                         |
| Ollama         | any            | [ollama.com](https://ollama.com)                         |
| Docker Desktop | any            | [docker.com](https://docker.com/products/docker-desktop) |
| Node.js        | 18+ (for smee) | [nodejs.org](https://nodejs.org)                         |
| smee-client    | any            | `npm install -g smee-client`                             |

---

## Manual Setup (step by step)

```bash
# 1. Clone
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>

# 2. Virtual environment
python3 -m venv .venv && source .venv/bin/activate   # Mac/Linux
# .\myenv\Scripts\Activate.ps1                        # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Pull Ollama models
ollama pull llama3
ollama pull nomic-embed-text

# 5. Configure environment
cp .env.example .env
# Fill in: GITHUB_APP_ID, GITHUB_WEBHOOK_SECRET, GITHUB_APP_PRIVATE_KEY_PATH

# 6. Start Docker services (FastAPI + ChromaDB)
docker compose up --build -d

# 7. Verify
curl http://localhost:8000/ping   # → {"status":"ok"}
```

---

## GitHub App Setup

1. Go to **GitHub → Settings → Developer Settings → GitHub Apps → New GitHub App**
2. Set permissions: **Pull Requests** (R/W), **Contents** (Read), **Commit statuses** (R/W)
3. Subscribe to events: **Pull request**
4. Set Webhook URL to your smee.io channel URL
5. Generate and download the private key → save as `secrets/private-key.pem`
6. Install the app on your target repository

---

## Environment Variables

```bash
# Required
GITHUB_APP_ID=123456
GITHUB_WEBHOOK_SECRET=your_webhook_secret
GITHUB_APP_PRIVATE_KEY_PATH=secrets/private-key.pem

# Ollama (defaults shown)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
OLLAMA_EMBED_MODEL=nomic-embed-text

# Optional — disable LangSmith tracing noise if no API key
LANGCHAIN_TRACING_V2=false
```

---

## Reviewing Any PR Without a Webhook

```bash
# By repo + PR number
python local_runner.py --repo owner/repo --pr 42

# By full URL
python local_runner.py --url https://github.com/owner/repo/pull/42

# Dry run (print findings, don't post to GitHub)
python local_runner.py --repo owner/repo --pr 42 --dry-run

# With RAG context from a local codebase
python local_runner.py --repo owner/repo --pr 42 --index-repo /path/to/code
```

---

## Running Tests

```bash
pytest tests/ -v        # all 52 tests
pytest tests/ -q        # quiet summary
pytest tests/test_agents.py -v   # agents only
```

All tests are fully mocked — no Ollama, GitHub, or ChromaDB required.

---

## Dashboard

After starting the server, view recent reviews at:

**http://localhost:8000/dashboard**

Auto-refreshes every 30 seconds. Also available as JSON at `/reviews`.

---

## Project Structure

```
.
├── app/
│   ├── main.py              # FastAPI entry point, dashboard
│   ├── webhook_handler.py   # Full pipeline coordinator
│   ├── diff_parser.py       # Unified diff → structured file/line data
│   └── review_store.py      # In-memory circular buffer (last 10 reviews)
├── agents/
│   ├── llm_factory.py       # Provider-agnostic LLM instantiation (factory pattern)
│   ├── code_analysis_agent.py  # Bug / security / quality LCEL chains
│   ├── formatter_agent.py   # Findings → GitHub Review API shape
│   └── orchestrator.py      # Coordinates all agents
├── rag/
│   ├── indexer.py           # Chunk + embed codebase into ChromaDB
│   └── retriever.py         # Similarity search for diff context
├── github_client/
│   ├── auth.py              # JWT RS256 + installation token exchange
│   ├── comment_poster.py    # Post PR review with inline comments
│   └── status_updater.py    # Commit status (pending/success/failure)
├── tests/                   # 52 unit + integration tests
├── docs/                    # Milestone docs + interview Q&As
├── local_runner.py          # CLI: review any PR without a webhook
├── demo_pr.py               # Interviewer demo: create PR + run review
├── Dockerfile
├── docker-compose.yml
├── setup.sh                 # One-command Mac/Linux setup
├── setup.ps1                # One-command Windows setup
└── .env.example
```

---

## Key Design Decisions

**Why LangChain LCEL?** The pipe `|` operator composes prompt → LLM → parser chains cleanly. New agent types drop in without touching existing code.

**Why local Ollama?** Zero API costs, no data leaves the machine, works offline. Swap to Azure OpenAI by setting `LLM_PROVIDER=azure` in `.env` — no code changes needed (factory pattern).

**Why ChromaDB?** Fully local vector store, no server required. The RAG layer gives the LLM context about the codebase it's reviewing, reducing hallucinated suggestions.

**Why GitHub App over OAuth?** Apps can be installed on specific repos, have fine-grained permissions, and use short-lived installation tokens — more secure than user OAuth tokens.
