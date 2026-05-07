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

### 👤 Person A & 👤 Person B — Both work on ALL topics

Tasks are split **within each topic**, not between topics.
Every milestone has both people working on agents, RAG, GitHub integration, Docker, and testing — so both learn the full stack equally.

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

- [ ] **A1.1** — Initialize Python project repo with `requirements.txt`, folder structure (`app/`, `agents/`, `rag/`, `tests/`)
- [ ] **A1.2** — Set up FastAPI app skeleton with `/webhook` endpoint and health check `/ping`
- [ ] **A1.3** — Install Ollama locally, pull `llama3` and `nomic-embed-text` models, confirm they respond via `ollama run`
- [ ] **A1.4** — Spike: write a 20-line LangChain `ChatOllama` hello-world script to verify the local LLM works end-to-end

#### Person B

- [ ] **B1.1** — Register GitHub App on GitHub (permissions: pull requests read/write, contents read), download private key
- [ ] **B1.2** — Set up smee.io for local webhook forwarding, confirm a test ping reaches `localhost:8000`
- [ ] **B1.3** — Configure environment variables (`.env.example`): Ollama URL, GitHub secrets, Chroma path, model name
- [ ] **B1.4** — Spike: set up ChromaDB locally and confirm a dummy document embeds and retrieves correctly using `nomic-embed-text`
- [ ] **B1.5** — Write ADR (Architecture Decision Record) in `docs/architecture.md` — document all tool/library choices with reasons

---

### MILESTONE 2 — Agents (Week 2–3)

> Both people build one agent each + write its tests, so both learn the agent + LangChain pattern.

#### Person A — Orchestrator Agent

- [ ] **A2.1** — Configure LangChain `ChatOllama` wrapper (`http://localhost:11434`), add a shared `llm_factory.py` utility both agents will use
- [ ] **A2.2** — Build **Orchestration Agent** (`agents/orchestrator.py`) — receives parsed diff + RAG context, calls sub-agents in sequence, merges results
- [ ] **A2.3** — Write unit tests for the orchestrator using `pytest` with mocked sub-agent calls (`tests/test_agents.py`)

#### Person B — Code Analysis & Formatter Agents

- [ ] **B2.1** — Build **Code Analysis Agent** (`agents/code_analysis_agent.py`) — LangChain agent with three tools:
  - `analyze_bugs` — detect logic errors and null pointer issues
  - `analyze_security` — flag hardcoded secrets, SQL injection, XSS
  - `analyze_quality` — check code smells, naming, complexity
- [ ] **B2.2** — Build **Review Formatter Agent** (`agents/formatter_agent.py`) — converts raw findings into structured GitHub review comment objects (file, line, severity, suggestion)
- [ ] **B2.3** — Write unit tests for both agents with mocked LLM responses (`tests/test_agents.py`)

---

### MILESTONE 3 — RAG + GitHub Integration (Week 2–3, parallel)

> Both people implement one half of RAG and one half of GitHub integration.

#### Person A — RAG Pipeline + Webhook Ingestion

- [ ] **A3.1** — Build **RAG Indexer** (`rag/indexer.py`) — chunk repo files with `RecursiveCharacterTextSplitter`, embed with `OllamaEmbeddings(nomic-embed-text)`, persist to ChromaDB
- [ ] **A3.2** — Write tests for the indexer — index a temp folder of dummy files, assert collection exists in ChromaDB (`tests/test_rag.py`)
- [ ] **A3.3** — Parse incoming GitHub `pull_request` webhook payload — extract repo, PR number, diff URL, commits
- [ ] **A3.4** — Handle webhook signature verification (HMAC SHA-256) for security

#### Person B — RAG Retriever + GitHub Output

- [ ] **B3.1** — Build **RAG Retriever** (`rag/retriever.py`) — given a diff query, retrieve top-k relevant chunks from ChromaDB; integrate retriever output into the orchestrator context window
- [ ] **B3.2** — Write tests for the retriever — index dummy files, query with related text, assert correct chunk is returned (`tests/test_rag.py`)
- [ ] **B3.3** — Build `diff_parser.py` — parse unified diff into per-file, per-hunk, per-line structure for agent consumption
- [ ] **B3.4** — Build `comment_poster.py` — post inline review comments on specific lines using GitHub Review API
- [ ] **B3.5** — Build `auth.py` — JWT generation + installation token exchange; build `status_updater.py` — set commit status (`pending` → `success`/`failure`)

---

### MILESTONE 4 — Integration & Testing (Week 4)

> Both people wire the pipeline together and both write tests, so both understand the full data flow.

#### Person A — Pipeline Wiring + Integration Tests

- [ ] **A4.1** — Wire full pipeline: webhook → diff parser → RAG retriever → orchestrator → code analysis → formatter → comment poster
- [ ] **A4.2** — Add retry logic and error handling (LLM timeouts, GitHub API rate limits, empty diffs)
- [ ] **A4.3** — Write integration tests using a sample PR diff fixture — assert comments are produced and comment_poster is called (`tests/test_integration.py`)
- [ ] **A4.4** — Add structured logging (`structlog`) throughout the pipeline

#### Person B — Observability + Prompt Tuning + Real PR Testing

- [ ] **B4.1** — Set up LangSmith free-tier tracing — instrument all LangChain agent calls so every run is visible in the LangSmith dashboard
- [ ] **B4.2** — Handle GitHub App event filtering — only trigger pipeline on `opened`, `synchronize`, `reopened` PR events
- [ ] **B4.3** — Build a simple eval set: 5 sample diffs with expected review comments; run them and score LLM output accuracy
- [ ] **B4.4** — Tune prompts for all three agents based on eval results — improve precision of security and bug detection
- [ ] **B4.5** — Test the full system end-to-end on 3+ real open source PRs (small repos) and document quality of output

---

### MILESTONE 5 — Local Runner, Docker & Observability (Week 5)

> Both people work on the local dev experience and Docker — key DevOps skills for the resume.

#### Person A — Docker + CI

- [ ] **A5.1** — Write `Dockerfile` for the FastAPI app
- [ ] **A5.2** — Write `docker-compose.yml` wiring FastAPI + ChromaDB + Ollama into a fully self-contained local dev environment
- [ ] **A5.3** — Set up GitHub Actions CI pipeline (`.github/workflows/ci.yml`) — lint (`ruff`) and run tests on every push

#### Person B — Local Runner + Setup Script + Dashboard

- [ ] **B5.1** — Build `local_runner.py` — CLI script to manually trigger a review on any PR URL without needing a live webhook (useful for demos)
- [ ] **B5.2** — Write `setup.ps1` / `setup.sh` one-command setup script: builds Docker images, pulls Ollama models inside the container, initialises ChromaDB
- [ ] **B5.3** — Build a simple local web dashboard (plain HTML + FastAPI route `/dashboard`) showing last 10 reviews, model used, and token counts
- [ ] **B5.4** — Document hardware requirements in README (min RAM for Llama 3, tested on CPU vs GPU)

---

### MILESTONE 6 — Polish, Demo & Documentation (Week 6)

> Both people contribute to documentation and demo materials — both should be able to explain the full project.

#### Person A

- [ ] **A6.1** — Record a 2–3 min demo video showing: PR opened → bot reviews → inline comments appear
- [ ] **A6.2** — Write `README.md` — project overview, quick start, architecture diagram, screenshots
- [ ] **A6.3** — Add `CONTRIBUTING.md` and clean up all code for public visibility

#### Person B

- [ ] **B6.1** — Create architecture diagram (draw.io or Excalidraw) showing full data flow and add to README
- [ ] **B6.2** — Write a short blog post / LinkedIn post explaining what both of you built and what you each learned
- [ ] **B6.3** — Build `demo_pr.py` — script that creates a dummy PR on a test repo so interviewers can run the whole system locally with one command

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
