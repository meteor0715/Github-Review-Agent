# Architecture Decision Record

## System Overview

The GitHub Review Agent is a locally-run FastAPI application that receives GitHub pull request
webhook events, analyses the code diff using a multi-agent LLM pipeline, and posts inline
review comments back to the PR via the GitHub API.

---

## Component Decisions

### LLM — Ollama (local)

- **Decision:** Use Ollama with Llama 3 / Mistral instead of OpenAI API
- **Reason:** Zero cost, fully local, no data leaves the machine

### Vector DB — ChromaDB

- **Decision:** ChromaDB persisted locally
- **Reason:** No external service needed, simple Python API, integrates natively with LangChain

### Embeddings — nomic-embed-text via Ollama

- **Decision:** Use Ollama's nomic-embed-text for all embeddings
- **Reason:** Keeps the entire stack local and free

### Webhook Tunnel — smee.io / ngrok

- **Decision:** Use smee.io to forward GitHub webhook events to localhost
- **Reason:** Required for GitHub App to reach a local server during development

### Agent Framework — LangChain

- **Decision:** LangChain for agent orchestration and tool use
- **Reason:** Native support for ChatOllama, ChromaDB, tool calling, and LangSmith tracing

---

## Agent Design

```
PR Diff + RAG Context
         │
         ▼
   Orchestrator Agent
         │
    ┌────┴────┐
    ▼         ▼
Code Analysis  (future agents)
  Agent
    │
    ▼
Formatter Agent
    │
    ▼
GitHub Comment Poster
```
