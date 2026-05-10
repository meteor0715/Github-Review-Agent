# Milestone 5 — Docker, Local Runner & Observability

## What this milestone covers

Milestone 5 focuses on the local development experience and operations tooling:
making the project easy to set up on any machine (not just the original developer's),
easy to run for demos, and easy to observe when things go wrong.

Topics covered:

- Docker images — layers, caching, slim images, non-root users
- `.dockerignore` — what goes in and what doesn't
- Docker Compose — multi-service orchestration, health checks, named volumes
- `host.docker.internal` — how containers reach services on the host machine
- Health checks — liveness vs readiness
- Setup scripts — `setup.sh` / `setup.ps1`
- Local runner CLI tool — bypassing webhooks for demos
- Dashboard — in-memory store, FastAPI HTML response, auto-refresh
- `deque` vs list for bounded in-memory storage

---

## 1. Docker Images

### What is a Docker image?

A Docker image is an immutable snapshot of a filesystem — the OS, runtime,
dependencies, and your code — packaged together. A running instance of an
image is called a container.

```
Image (static):   Like a class definition
Container (live): Like an instance of that class
```

Each image is made of layers. Each `RUN`, `COPY`, `ADD` instruction in the
Dockerfile creates one layer. Layers are cached: if nothing changed in a
layer's dependencies, Docker reuses the cached version.

### Layer caching — the most important Docker performance concept

```dockerfile
# WRONG order — requirements layer rebuilds every time any source file changes:
COPY . .
RUN pip install -r requirements.txt   # ← uncached every time

# CORRECT order — requirements layer only rebuilds when requirements.txt changes:
COPY requirements.txt .
RUN pip install -r requirements.txt   # ← cached unless requirements.txt changes
COPY . .                              # ← only this layer is rebuilt on code changes
```

This makes the difference between a 5-second rebuild (cached pip layer) and a
3-minute rebuild (pip downloading all packages again) on every code change.

### Why `python:3.11-slim` not `python:3.11`?

```
python:3.11       → ~900MB — includes compilers, dev headers, man pages
python:3.11-slim  → ~130MB — just Python + minimal Debian, no dev tools

Our code only RUNS Python, it doesn't compile it.
We add gcc only for packages that compile C extensions (chromadb).
The slim image is ~770MB smaller — 6x smaller final image.
```

### Non-root user — security best practice

```dockerfile
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser
```

By default, Docker containers run as root inside the container. If your app
has a vulnerability that gives an attacker code execution, they have root access
inside the container — potentially allowing privilege escalation to the host.

Running as a dedicated `appuser` limits the damage: the attacker gets a
limited user, not root. This is the principle of least privilege applied
to container security.

### Health check

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/ping').raise_for_status()"
```

Docker runs this command every 30 seconds. If it fails 3 times in a row,
the container is marked `unhealthy`. Docker Compose can then restart it
automatically (`restart: unless-stopped`).

---

## 2. `.dockerignore`

### Why it matters

Without `.dockerignore`, Docker sends your entire project folder to the Docker
daemon as the "build context" — including `.git/`, `.venv/`, `secrets/`,
`chroma_db/`, etc. This can be hundreds of MB and slows every build.

```
With .dockerignore:     build context ~ 50KB (just source files)
Without .dockerignore:  build context ~ 500MB (includes .venv, chroma_db, .git)
```

### Critical entries

```dockerignore
secrets/     ← NEVER send private keys into an image
*.pem        ← belt AND suspenders
.env         ← env vars should be injected at runtime, not baked in
.venv/       ← image installs its own packages from requirements.txt
myenv/       ← same
chroma_db/   ← mounted as a named volume at runtime
.git/        ← huge, never needed
```

### The private key rule

Never `COPY secrets/` into a Docker image. Images are shareable, pushable to
Docker Hub, sometimes stored in CI logs. A private key baked into an image
is a leaked private key. Instead:

```yaml
# docker-compose.yml
volumes:
  - ./secrets:/app/secrets:ro # ← mount at runtime, read-only
```

The `:ro` flag (read-only) means the container can read but not modify the
secrets folder — another application of least privilege.

---

## 3. Docker Compose

### What is Docker Compose?

Compose manages multiple containers as a single unit. Instead of running
`docker run` with dozens of flags for each service, you define everything in
`docker-compose.yml` and run `docker compose up`.

```yaml
services:
  app: # our FastAPI server
  chroma: # ChromaDB vector database
```

### Why separate ChromaDB into its own container?

```
Option A: ChromaDB embedded in the FastAPI process:
  - Simpler (one container)
  - ChromaDB runs in the same process
  - If FastAPI crashes, ChromaDB data is inaccessible during restart

Option B: ChromaDB as a separate container (what we do):
  - Two containers, slightly more config
  - ChromaDB has its own lifecycle — it can be restarted independently
  - ChromaDB's HTTP API is accessible from any other container or tool
  - Data is in a named volume, independent of any container
```

In production, external databases are always separate services. Compose
teaches this pattern at local scale.

### Named volumes vs bind mounts

```yaml
# Bind mount (development — maps host folder into container):
volumes:
  - .:/app          # host ./  ↔  container /app
                    # changes on host are immediately visible in container

# Named volume (data persistence — Docker manages the storage location):
volumes:
  - chroma_data:/app/chroma_db
                    # Docker creates and manages this volume
                    # data persists across docker compose down/up
                    # docker compose down -v deletes it
```

We use bind mounts for source code (so `--reload` works) and named volumes
for data (so ChromaDB index survives container restarts).

### `host.docker.internal` — reaching the host from inside a container

```yaml
# docker-compose.yml
environment:
  OLLAMA_BASE_URL: http://host.docker.internal:11434
```

Inside a container, `localhost` means the container itself, not the Mac.
`host.docker.internal` is a special DNS name Docker provides that resolves
to the Mac's host IP. This lets the container call Ollama which runs natively
on the Mac (for GPU access).

```
Mac (host)                      Container
┌───────────────────┐           ┌────────────────────┐
│ ollama serve :11434 │◄─────────│ OLLAMA_BASE_URL =  │
│                   │  host.    │ http://host.docker │
│                   │  docker.  │ .internal:11434    │
└───────────────────┘  internal └────────────────────┘
```

### Health checks and `depends_on`

```yaml
app:
  depends_on:
    chroma:
      condition: service_healthy # ← wait for ChromaDB to pass health check
```

Without `condition: service_healthy`, Docker starts `app` immediately after
starting `chroma`, but ChromaDB takes ~5 seconds to initialise. The app would
fail to connect to ChromaDB on startup. The health check makes Compose wait
until ChromaDB's `GET /api/v1/heartbeat` returns 200 before starting the app.

---

## 4. Setup Scripts

### Why setup scripts?

Without a setup script, a new developer joining the project has to:

1. Read the README
2. Install the right Python version
3. Create a venv
4. Run `pip install`
5. Copy `.env.example`
6. Pull Ollama models
7. Start Docker

With `./setup.sh`, all of that happens with one command. This matters for:

- Demos where the interviewer wants to run it themselves
- Onboarding a new team member
- Running on a new machine after clone

### `set -e` in bash scripts

```bash
set -e   # exit immediately if any command fails
```

Without `set -e`, if `pip install` fails, the script continues to the next
step and produces confusing errors. With `set -e`, the script stops at the
failure and you see exactly which step broke.

### Checking prerequisites before installing

```bash
if ! command -v ollama &>/dev/null; then
    warn "Ollama not found..."
else
    ok "Ollama found"
fi
```

`command -v` returns exit code 0 if the command exists, non-zero if not.
This is the standard POSIX way to check if a program is installed.

We check before acting — don't try to pull Ollama models if Ollama isn't
installed. Print a clear message instead.

---

## 5. local_runner.py — CLI Tool

### Why it exists

The webhook flow requires: GitHub App configured → smee.io running → PR opened.
For demos, that's a lot of setup. `local_runner.py` lets you point at any
PR URL and trigger the full review pipeline locally in seconds.

### How it works

```python
python local_runner.py --repo owner/repo --pr 42
```

This calls the GitHub API directly (no webhook needed):

1. `generate_jwt()` → `get_installation_token()` — auth
2. `GET /repos/{owner}/{repo}/installation` — find installation ID for this repo
3. `GET /repos/{owner}/{repo}/pulls/{n}` — get head SHA
4. `GET /repos/{owner}/{repo}/pulls/{n}` with `Accept: vnd.github.v3.diff` — get diff
5. `parse_diff()` → `retrieve_context()` → `run_orchestrator()` — pipeline
6. `post_review_comments()` + `set_commit_status()` — post results

### `--dry-run` flag

```python
python local_runner.py --repo owner/repo --pr 42 --dry-run
```

Runs the full pipeline and prints findings to the terminal but does NOT
call `post_review_comments` or `set_commit_status`. Safe for testing
without polluting a real PR with bot comments.

### `--index-repo` flag

```python
python local_runner.py --repo owner/repo --pr 42 --index-repo /path/to/code
```

Triggers `index_repository()` before the review, indexing the local codebase
into ChromaDB. The RAG retriever then has real context to draw on. Useful
when demonstrating the full RAG pipeline.

---

## 6. Dashboard

### Why a simple HTML dashboard and not React?

```
React dashboard:
  ✅ Nice UI, rich interactivity
  ❌ Requires npm, build step, separate dev server
  ❌ ~200MB node_modules just to show a table
  ❌ Much more complexity for a local monitoring page

Plain HTML from FastAPI:
  ✅ No build step, no npm, no separate process
  ✅ One Python function, deployed with the app
  ✅ Works with just `uvicorn app.main:app`
  ❌ Can't build complex interactive UIs
```

For a local dev monitoring page, plain HTML is the right tradeoff. In
production you'd use Jinja2 templates or a proper frontend.

### `deque(maxlen=10)` vs a plain list

```python
from collections import deque

_recent_reviews: deque = deque(maxlen=10)
```

A regular list with `append()` grows forever — a memory leak if the server
runs for weeks. `deque(maxlen=10)` automatically discards the oldest entry
when you add an 11th item. It's a fixed-size circular buffer.

This is also more expressive: `deque(maxlen=10)` communicates the intent
("keep the last 10 items") directly in the data structure.

### Why a separate `review_store.py` module?

`main.py` imports `webhook_handler.py` (to register the router).
If `webhook_handler.py` also imported from `main.py`, we'd have a circular
import — Python would raise `ImportError: cannot import name 'record_review'
from partially initialized module 'app.main'`.

By putting `_recent_reviews` and `record_review` in `app/review_store.py`,
both `main.py` and `webhook_handler.py` can import from it without circularity:

```
main.py         → imports → review_store.py   ✅
webhook_handler → imports → review_store.py   ✅
main.py         → imports → webhook_handler   ✅
webhook_handler → imports → main.py           ❌ circular (we avoid this)
```

### Auto-refresh with `<meta http-equiv="refresh" content="30">`

```html
<meta http-equiv="refresh" content="30" />
```

This HTML meta tag tells the browser to reload the page every 30 seconds.
No JavaScript needed. The dashboard always shows the latest reviews without
the user having to manually refresh.

---

## Interview Questions — Milestone 5 Topics

---

**Q1: Explain Docker image layers and why layer order in a Dockerfile matters.**

> Each Dockerfile instruction (RUN, COPY, ADD) creates an immutable layer.
> Docker caches each layer and only rebuilds layers that changed plus all layers
> after them. If you COPY all source code before pip install, every code change
> invalidates the pip layer — Docker re-downloads all packages. If you
> COPY requirements.txt, pip install, then COPY source, code changes only
> invalidate the source layer. The pip layer is cached. This changes rebuilds
> from minutes to seconds.

---

**Q2: Why do you run the container as a non-root user?**

> By default, containers run as root inside the container. If a vulnerability
> in the app gives an attacker code execution, they have root access to the
> container's filesystem — potentially enabling privilege escalation to the
> host. A dedicated non-root user (`appuser`) limits damage: the attacker gets
> a restricted user account, not root. Files not owned by appuser are
> unreadable. This is the principle of least privilege applied to container
> security — a standard production practice.

---

**Q3: What is `host.docker.internal` and when do you need it?**

> Inside a Docker container, `localhost` resolves to the container itself, not
> the host machine. `host.docker.internal` is a special DNS name Docker provides
> on Mac and Windows that resolves to the host machine's IP. We use it to let
> the FastAPI container call Ollama running natively on the Mac:
> `OLLAMA_BASE_URL=http://host.docker.internal:11434`. Without this, the
> container can't reach Ollama at all, because `localhost:11434` inside the
> container is the container's own loopback, not the Mac's.

---

**Q4: What is the difference between a named volume and a bind mount in Docker Compose?**

> A bind mount maps a host directory directly into the container — changes on
> the host are immediately visible in the container (`- .:/app`). Used for source
> code during development so `uvicorn --reload` picks up changes. A named volume
> is managed by Docker — Docker decides where to store the data on the host
> filesystem. Data in named volumes persists across `docker compose down/up`
> (but is deleted with `docker compose down -v`). Used for database data
> (ChromaDB) so the vector index survives container restarts.

---

**Q5: What does `depends_on: condition: service_healthy` do and why is it important?**

> Without it, `depends_on` only waits for the container to START, not to be
> READY. ChromaDB takes several seconds to initialise after starting — during
> that time it rejects connections. If the app starts before ChromaDB is ready,
> it crashes on the first ChromaDB call. `condition: service_healthy` makes
> Compose wait until ChromaDB's health check passes (GET /api/v1/heartbeat
> returns 200) before starting the app. Always use `service_healthy` for
> databases and services that take time to initialise.

---

**Q6: Why are secrets mounted as volumes instead of being COPY'd into the Docker image?**

> Docker images are shareable — they can be pushed to Docker Hub, stored in
> CI pipelines, shared with collaborators. A secret baked into an image with
> COPY is a leaked secret: anyone who can pull the image can extract it.
> Secrets should be injected at runtime, not at build time. We mount
> `./secrets:/app/secrets:ro` — the private key only exists on the host
> machine and is exposed to the container at runtime only. The `:ro` flag
> makes it read-only so the container can't accidentally modify or delete it.

---

**Q7: What is `deque(maxlen=10)` and why use it instead of a list?**

> `deque` (double-ended queue) from Python's `collections` module is a linked
> list optimised for appending/popping from both ends (O(1)). When `maxlen` is
> set, it automatically discards the oldest element when full — a circular
> buffer. A plain list would grow indefinitely over weeks, consuming more and
> more memory (a memory leak). `deque(maxlen=10)` bounds memory usage and
> communicates intent directly: "keep the last 10 items, discard older ones".

---

**Q8: Why is there a separate `review_store.py` module instead of storing reviews in `main.py`?**

> To avoid a circular import. `main.py` imports from `webhook_handler.py`
> (to register the router). If `webhook_handler.py` also imported from
> `main.py` (to call `record_review`), Python would have a circular dependency
> and raise an ImportError. By extracting the shared state into `review_store.py`,
> both `main.py` and `webhook_handler.py` can import from it independently.
> This follows the single responsibility principle: `review_store.py` does one
> thing — store recent review results.

---

**Q9: What are Docker health checks and what problem do they solve?**

> A health check is a command Docker runs periodically (every N seconds) to
> determine if the container is functioning correctly. If it fails repeatedly,
> Docker marks the container `unhealthy`. Without health checks, Docker
> considers a container healthy the moment the process starts — even if the
> process started but is stuck in an error loop. Health checks let Docker
> Compose properly sequence startup (`depends_on: condition: service_healthy`)
> and restart unhealthy containers automatically. Our check calls `GET /ping`
> on the FastAPI server to verify it's responding.

---

**Q10: Describe the `local_runner.py` tool and what problem it solves.**

> `local_runner.py` is a CLI that triggers the full PR review pipeline
> without needing a live GitHub webhook or smee.io tunnel. Given a repo and
> PR number, it authenticates as the GitHub App, fetches the PR diff via
> the GitHub API, runs the full pipeline (diff parser → RAG → orchestrator →
> comment poster), and updates the commit status. The `--dry-run` flag lets
> you run the pipeline and print results without posting to GitHub — safe for
> demos and debugging. This is essential for interviewer demos: you can show the
> agent reviewing any public PR in real-time without any webhook infrastructure.

---

**Q11: Why is the dashboard built as plain HTML served by FastAPI instead of a React app?**

> For a local monitoring page, the complexity of React (npm, build step, webpack,
> node_modules) is unjustified. FastAPI can serve a pre-built HTML string directly
> from a route handler — no build step, no additional processes, no npm. The
> `<meta http-equiv="refresh" content="30">` tag provides auto-refresh without
> JavaScript. This is a classic "right tool for the job" decision: React excels
> at complex interactive UIs; a 10-row status table doesn't need it. In production,
> Jinja2 templates would be the next step up without adding a separate frontend.
