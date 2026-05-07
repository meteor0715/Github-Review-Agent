# GitHub AI Code Review Agent

A locally-run multi-agent LLM system that automatically reviews GitHub pull requests.
It analyses the diff for bugs, security issues, and code quality problems,
then posts structured inline comments directly on the PR.

> Runs 100% locally — no cloud services, no API costs. Powered by Ollama + LangChain + ChromaDB.

---

## Architecture

```
GitHub PR Event
      │
      ▼ (smee.io tunnel)
Webhook Server (FastAPI)
      │
      ▼
Orchestration Agent (LangChain + ChatOllama)
      ├── RAG Retriever (ChromaDB + nomic-embed-text)
      ├── Code Analysis Agent (bugs / security / quality tools)
      └── Review Formatter Agent
            │
            ▼
      GitHub PR Review API (inline comments)
```

---

## Prerequisites

- Python 3.11+
- [Ollama](https://ollama.com/) installed and running locally
- Docker + Docker Compose
- A GitHub account to register a GitHub App

---

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/your-org/github-review-agent
cd github-review-agent

# 2. Copy and fill in environment variables
cp .env.example .env

# 3. Start everything with Docker Compose
docker-compose up --build

# 4. Pull required Ollama models (first time only)
docker exec <ollama_container_name> ollama pull llama3
docker exec <ollama_container_name> ollama pull nomic-embed-text

# 5. Forward GitHub webhooks to localhost
npx smee-client --url https://smee.io/<your-channel> --target http://localhost:8000/webhook
```

---

## Manual PR Review (no webhook needed)

```bash
python local_runner.py --pr https://github.com/owner/repo/pull/42
```

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Project Structure

```
github-review-agent/
├── app/                  # FastAPI server
├── agents/               # Orchestrator, Code Analysis, Formatter
├── rag/                  # ChromaDB indexer and retriever
├── github_client/        # GitHub App auth, comment poster, status updater
├── tests/                # Unit + integration tests
├── docs/                 # Architecture decisions
├── local_runner.py       # CLI for manual reviews
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

---

## Team

- **Person A** — Backend, Agents & AI Core
- **Person B** — GitHub Integration, RAG & Local Setup
