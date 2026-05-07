# AI-Powered GitHub Code Review Agent — Project Plan

## Project Overview

A GitHub App that automatically reviews pull requests using an LLM. It analyzes code for bugs, security issues, and quality problems, then posts structured review comments directly on the PR.

---

## Architecture Overview

```
GitHub PR Event
      │
      ▼
Webhook Server (FastAPI)
      │
      ▼
Orchestration Layer
      ├── RAG Engine (codebase context via vector DB)
      ├── Code Analysis Agent (bugs, security, quality)
      ├── Review Formatter Agent (structured PR comments)
      └── GitHub API Client (post comments)
```

---

## Tech Stack

| Layer              | Technology                                           |
| ------------------ | ---------------------------------------------------- |
| Backend            | Python + FastAPI                                     |
| LLM                | Ollama (local) — Llama 3 / Mistral                   |
| Agentic Framework  | LangChain                                            |
| Vector DB          | ChromaDB (fully local)                               |
| GitHub Integration | PyGithub + Webhooks                                  |
| Local Tunnel       | smee.io / ngrok (receive GitHub events)              |
| Containerisation   | Docker + docker-compose (local dev environment only) |
| Observability      | LangSmith (free tier, tracing + evals)               |
| Auth               | GitHub App JWT + Installation tokens                 |

---

## Team Split

### 👤 Person A — Backend, Agents & AI Core

### 👤 Person B — GitHub Integration, RAG & Local Setup

---

## Milestones

| #   | Milestone                        | Duration |
| --- | -------------------------------- | -------- |
| 1   | Project Setup & Architecture     | Week 1   |
| 2   | Core Agents & LLM Logic          | Week 2–3 |
| 3   | GitHub Integration & RAG         | Week 2–3 |
| 4   | Integration & End-to-End Testing | Week 4   |
| 5   | Local Runner & Observability     | Week 5   |
| 6   | Polish, Demo & Documentation     | Week 6   |

---

## Detailed Task Breakdown

---

### MILESTONE 1 — Project Setup & Architecture (Week 1)

#### Person A

- [ ] **A1.1** — Initialize Python project repo with `pyproject.toml` / `requirements.txt`, folder structure (`app/`, `agents/`, `rag/`, `tests/`)
- [ ] **A1.2** — Set up FastAPI app skeleton with `/webhook` endpoint and health check `/ping`
- [ ] **A1.3** — Configure environment variables (`.env.example`): Ollama base URL, GitHub secrets, Chroma DB path, model name
- [ ] **A1.4** — Write ADR (Architecture Decision Record) in `docs/architecture.md` — finalize agent design

#### Person B

- [ ] **B1.1** — Register GitHub App on GitHub (permissions: pull requests read/write, contents read), download private key
- [ ] **B1.2** — Set up ngrok or smee.io for local webhook forwarding during development
- [ ] **B1.3** — Create `github_client.py` — handle JWT auth, installation token generation, and basic API calls
- [ ] **B1.4** — Install Ollama locally, pull `llama3` and `mistral` models, confirm they respond via `ollama run`
- [ ] **B1.5** — Set up ChromaDB locally and confirm embeddings round-trip works using Ollama's embedding model (`nomic-embed-text`)

---

### MILESTONE 2 — Core Agents & LLM Logic (Week 2–3)

#### Person A

- [ ] **A2.1** — Configure LangChain `ChatOllama` LLM wrapper pointing to local Ollama server (`http://localhost:11434`), add model switcher utility
- [ ] **A2.2** — Build **Orchestration Agent** (`agents/orchestrator.py`) — receives PR diff, routes to sub-agents, collects results
- [ ] **A2.3** — Build **Code Analysis Agent** (`agents/code_analysis_agent.py`) — LangChain agent with tools:
  - `analyze_bugs` — detect logic errors and null pointer issues
  - `analyze_security` — flag hardcoded secrets, SQL injection, XSS
  - `analyze_quality` — check code smells, naming, complexity
- [ ] **A2.4** — Build **Review Formatter Agent** (`agents/formatter_agent.py`) — converts raw agent output into structured GitHub review comments (file, line number, severity, suggestion)
- [ ] **A2.5** — Write unit tests for each agent using `pytest` with mocked LLM responses (`tests/test_agents.py`)

#### Person B

- [ ] **B2.1** — Build **RAG pipeline** (`rag/indexer.py`) — chunk and embed repo files into ChromaDB using Ollama `nomic-embed-text` embeddings on first run
- [ ] **B2.2** — Build **RAG retriever** (`rag/retriever.py`) — given a diff, retrieve relevant existing code context to give agents better understanding
- [ ] **B2.3** — Integrate retriever output into the orchestrator context window
- [ ] **B2.4** — Write tests for RAG pipeline — confirm correct chunks are retrieved for sample diffs

---

### MILESTONE 3 — GitHub Integration (Week 2–3, parallel)

#### Person A

- [ ] **A3.1** — Parse incoming GitHub `pull_request` webhook payload — extract repo, PR number, diff URL, commits
- [ ] **A3.2** — Build `diff_parser.py` — parse unified diff into per-file, per-hunk, per-line structure for agent consumption
- [ ] **A3.3** — Handle webhook signature verification (HMAC SHA-256) for security

#### Person B

- [ ] **B3.1** — Build `comment_poster.py` — post inline review comments on specific lines using GitHub Review API
- [ ] **B3.2** — Build PR status updater — set commit status (`pending` → `success`/`failure`) with summary message
- [ ] **B3.3** — Handle GitHub App event filtering — only trigger on `opened`, `synchronize`, `reopened` PR events
- [ ] **B3.4** — Test full webhook → comment flow end-to-end on a test repo

---

### MILESTONE 4 — Integration & Testing (Week 4)

#### Person A

- [ ] **A4.1** — Wire full pipeline: webhook → diff parser → RAG context → orchestrator → formatter → comment poster
- [ ] **A4.2** — Add retry logic and error handling (rate limits, LLM timeouts, GitHub API failures)
- [ ] **A4.3** — Write integration tests using a sample PR diff fixture (`tests/test_integration.py`)
- [ ] **A4.4** — Add logging (`structlog`) throughout the pipeline

#### Person B

- [ ] **B4.1** — Set up LangSmith tracing — instrument all LangChain agent calls for observability
- [ ] **B4.2** — Build a simple eval set: 5 sample diffs with expected review comments, score LLM accuracy
- [ ] **B4.3** — Tune prompts based on eval results — improve precision of security and bug detection
- [ ] **B4.4** — Test on 3+ real open source PRs (small repos) and review quality of output

---

### MILESTONE 5 — Local Runner & Observability (Week 5)

#### Person A

- [ ] **A5.1** — Build `local_runner.py` — a CLI script to manually trigger a review on any PR URL without needing a live webhook (useful for demos)
- [ ] **A5.2** — Write `Dockerfile` for the FastAPI app and `docker-compose.yml` that wires up the FastAPI server + ChromaDB + Ollama container for a fully self-contained local dev environment
- [ ] **A5.3** — Write a `setup.sh` / `setup.ps1` one-command setup script: builds Docker images, pulls Ollama models inside container, initialises ChromaDB
- [ ] **A5.4** — Set up GitHub Actions CI pipeline (`.github/workflows/ci.yml`) — lint and test on push (no deployment step)

#### Person B

- [ ] **B5.1** — Set up LangSmith free-tier tracing — instrument all LangChain calls so every agent run is visible in the LangSmith dashboard
- [ ] **B5.2** — Keep smee.io tunnel running persistently via a background script so GitHub webhooks reach localhost reliably
- [ ] **B5.3** — Build a simple local web dashboard (plain HTML + FastAPI route `/dashboard`) showing last 10 reviews, model used, and token counts
- [ ] **B5.4** — Document hardware requirements in README (min RAM for running Llama 3 locally, tested on CPU vs GPU)

---

### MILESTONE 6 — Polish, Demo & Documentation (Week 6)

#### Person A

- [ ] **A6.1** — Record a 2–3 min demo video showing: PR opened → bot reviews → inline comments appear
- [ ] **A6.2** — Write `README.md` — project overview, architecture diagram, setup instructions, screenshots
- [ ] **A6.3** — Add a `CONTRIBUTING.md` and clean up code for public visibility

#### Person B

- [ ] **B6.1** — Create architecture diagram (draw.io or Excalidraw) and add to README
- [ ] **B6.2** — Write a short blog post / LinkedIn post explaining what you built and what you learned
- [ ] **B6.3** — Provide a `demo_pr.py` script that creates a dummy PR on a test repo so interviewers can run the whole thing locally with one command

---

## Folder Structure

```
github-review-agent/
├── app/
│   ├── main.py               # FastAPI entry point
│   ├── webhook_handler.py    # Webhook routing
│   └── diff_parser.py        # Unified diff parser
├── agents/
│   ├── orchestrator.py
│   ├── code_analysis_agent.py
│   └── formatter_agent.py
├── rag/
│   ├── indexer.py
│   └── retriever.py
├── github_client/
│   ├── auth.py               # JWT + installation token
│   ├── comment_poster.py
│   └── status_updater.py
├── tests/
│   ├── test_agents.py
│   ├── test_rag.py
│   └── test_integration.py
├── docs/
│   └── architecture.md
├── .github/workflows/ci.yml
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Resume Talking Points (after completion)

- Built a multi-agent LLM system using LangChain with orchestration, analysis, and formatting agents
- Ran LLMs fully locally using Ollama (Llama 3 / Mistral) — zero cloud cost, privacy-preserving
- Implemented RAG pipeline over codebases using ChromaDB + Ollama embeddings for context-aware reviews
- Integrated with GitHub API via GitHub App (webhooks, JWT auth, inline PR comments)
- Built a local tunnel setup (smee.io) to receive live GitHub events during development
- Evaluated LLM output quality using a custom eval set and LangSmith tracing — improved precision by prompt tuning
