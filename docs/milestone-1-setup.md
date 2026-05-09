# Milestone 1 — Project Setup & Architecture

## What this milestone covers

Before writing a single line of business logic, every software project needs a
solid foundation: the right tools chosen for the right reasons, authentication
set up securely, and the development environment wired so GitHub on the internet
can reach your laptop. That's what Milestone 1 is about.

Topics covered:

- Python virtual environments
- FastAPI and why it was chosen
- GitHub App registration and authentication model
- JWT (JSON Web Tokens) and RSA cryptography
- Webhook architecture and local tunnelling with smee.io
- ChromaDB and Ollama local setup
- Environment variable management and the `.env` pattern

---

## 1. Python Virtual Environments

### What is a virtual environment?

A Python virtual environment is an isolated directory containing its own Python
interpreter and its own set of installed packages, completely separate from your
system Python and from every other project on your machine.

### Why do we need one?

Imagine Project A needs `langchain==0.1.0` and Project B needs `langchain==0.2.0`.
Without virtual environments, installing one breaks the other because there's only
one global `site-packages` folder.

```
Without venv:
  System Python
    └── site-packages/
          ├── langchain 0.2.0   ← overwrote 0.1.0, Project A now broken
          └── chromadb

With venv:
  project-a/.venv/
    └── site-packages/
          └── langchain 0.1.0   ← isolated, Project A always works

  project-b/.venv/
    └── site-packages/
          └── langchain 0.2.0   ← isolated, Project B always works
```

### How to create and activate (Mac)

```bash
python3 -m venv .venv          # create at .venv/ inside project folder
source .venv/bin/activate      # activate — now 'python' and 'pip' point here
pip install -r requirements.txt # install project packages into .venv only
```

You know it's active when your terminal prompt shows `(.venv)` at the start.

### `.venv` is gitignored — why?

The `.venv` folder is hundreds of megabytes of downloaded packages. Committing it
would bloat the repo massively. Anyone who clones the repo runs
`pip install -r requirements.txt` to recreate it. That's why `requirements.txt`
exists — it's the recipe, `.venv` is the result.

---

## 2. FastAPI

### What is FastAPI?

FastAPI is a modern Python web framework for building APIs. It's what receives
the GitHub webhook POST requests and serves the `/ping` health check.

### Why FastAPI and not Flask or Django?

|                   | Flask                  | Django        | FastAPI                     |
| ----------------- | ---------------------- | ------------- | --------------------------- |
| **Speed**         | Moderate               | Moderate      | Very fast (async ASGI)      |
| **Async support** | Bolted on (not native) | Partial       | Native (`async def`)        |
| **Auto docs**     | No                     | No            | Yes (Swagger UI at `/docs`) |
| **Type hints**    | No                     | No            | Yes (Pydantic)              |
| **Best for**      | Small APIs             | Full web apps | Modern APIs / microservices |

FastAPI is built on **ASGI** (Asynchronous Server Gateway Interface). Compare to
.NET: it's like choosing `ASP.NET Core` (async, fast) over classic `ASP.NET` (sync).

### The `async def` keyword

```python
# Synchronous (Flask-style) — blocks the thread while waiting for GitHub
@app.post("/webhook")
def webhook():
    result = call_github_api()   # thread is blocked here — can't handle other requests
    return result

# Asynchronous (FastAPI) — yields control while waiting for I/O
@app.post("/webhook")
async def webhook():
    result = await call_github_api()  # other requests handled while waiting
    return result
```

With `async def`, one process can handle thousands of concurrent connections.
Without it, one slow request blocks everyone.

### What `uvicorn` is

FastAPI doesn't run itself — it needs an ASGI server. `uvicorn` is that server.

```bash
uvicorn app.main:app --reload --port 8000
#         ^^^^^^^^^  ^^^     ^^^^^^^^^^^^^^
#         module     variable  options
#         path       name
```

`--reload` means uvicorn watches for file changes and restarts automatically.
This is only for development — in production you'd omit `--reload`.

### The router pattern

```python
# app/main.py — the entry point
from fastapi import FastAPI
from app.webhook_handler import router

app = FastAPI()
app.include_router(router)   # registers all routes defined in webhook_handler

# app/webhook_handler.py — the handler
from fastapi import APIRouter
router = APIRouter()

@router.post("/webhook")
async def webhook(request: Request):
    ...
```

We use `APIRouter` (not defining routes directly on `app`) so routes can be in
separate files. This follows the Single Responsibility Principle — `main.py`
is the app entry point, `webhook_handler.py` handles webhook logic.

---

## 3. GitHub App — Registration and Authentication

### GitHub App vs Personal Access Token (PAT)

```
Personal Access Token:
  ┌──────────────────────────────────────────────┐
  │  Tied to YOUR personal GitHub account        │
  │  If you delete it → bot breaks               │
  │  If you leave the org → bot breaks           │
  │  All-or-nothing permissions (broad scope)    │
  └──────────────────────────────────────────────┘

GitHub App:
  ┌──────────────────────────────────────────────┐
  │  Independent identity — exists on its own    │
  │  Fine-grained permissions (only what it needs│
  │  Installed per-repository (scoped access)    │
  │  Uses RSA key pair — no password to leak     │
  │  Tokens expire in 1 hour automatically       │
  └──────────────────────────────────────────────┘
```

### The two-step authentication flow

Every API call our app makes to GitHub requires a token. Here's how we get it:

```
                            YOUR MACHINE
                       ┌─────────────────────┐
Step 1:                │                     │
Create JWT             │  private-key.pem    │
                       │  (RSA private key)  │
                       │         │           │
                       │         ▼           │
                       │  PyJWT signs a JWT  │
                       │  payload:           │
                       │  {                  │
                       │    iss: "APP_ID",   │
                       │    iat: now - 60s,  │
                       │    exp: now + 10min │
                       │  }                  │
                       │         │           │
                       └─────────┼───────────┘
                                 │
Step 2:                          ▼
Exchange JWT            POST to GitHub API
for install token:      /app/installations/{id}/access_tokens
                        Authorization: Bearer <jwt>
                                 │
                                 ▼ (GitHub verifies JWT using your public key)
                         { "token": "ghs_xxxxxxxxxx" }
                                 │
Step 3:                          ▼
Use install token        All GitHub API calls:
                         Authorization: Bearer ghs_xxxxxxxxxx
                         (valid for 1 hour, then repeat steps 1-2)
```

### JWT structure explained

A JWT is three Base64URL-encoded sections joined by dots:

```
eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiIxMjM0NSIsImlhdCI6MTcxMDAwMDAwMCwiZXhwIjoxNzEwMDAwNjAwfQ.SIGNATURE
         ^                              ^                                     ^
      Header                         Payload                             Signature
  (algorithm info)              (your claims)                    (RSA-signed hash)

Header decoded:  { "alg": "RS256" }
Payload decoded: { "iss": "12345", "iat": 1710000000, "exp": 1710000600 }
```

Anyone can decode the header and payload (they're just Base64). The **signature**
is what makes it secure — only the holder of the RSA private key can create a valid
signature. GitHub verifies it with the public key you uploaded.

### Why `iat: now - 60s` (issued 60 seconds in the past)?

Clocks between servers are never perfectly synchronised. If your laptop clock is
30 seconds ahead of GitHub's servers, a JWT issued at `now` looks like it was
issued in the future to GitHub, and GitHub rejects it. Subtracting 60 seconds
gives a safety buffer for clock skew.

### Why RSA (asymmetric) instead of HMAC (symmetric)?

```
HMAC (symmetric — HS256):
  Sign   → uses the SECRET
  Verify → uses the SAME SECRET

  Problem: GitHub would need to STORE your secret to verify JWTs.
           If GitHub's database is breached, attackers have your secret
           and can forge tokens.

RSA (asymmetric — RS256):
  Sign   → uses YOUR PRIVATE KEY  (never leaves your machine)
  Verify → uses YOUR PUBLIC KEY   (you upload this to GitHub App settings)

  Solution: GitHub only stores the public key. Even if breached, the public
            key alone cannot forge tokens. Only your private key can sign.
```

---

## 4. Webhooks and smee.io

### What is a webhook?

A webhook is the OPPOSITE of polling.

```
Polling (bad for real-time):
  Your server → "Any new PRs?" → GitHub → "No"
  Your server → "Any new PRs?" → GitHub → "No"
  Your server → "Any new PRs?" → GitHub → "Yes! PR #42 just opened"
  (wastes requests, adds latency)

Webhook (event-driven):
  PR #42 opens...
  GitHub → POST /webhook → Your server → "Got it, reviewing now"
  (instant, zero wasted requests)
```

### The local tunnel problem

GitHub is on the internet. Your laptop is behind a router with NAT (Network
Address Translation). Your laptop's `localhost:8000` is not reachable from the
internet.

```
GitHub (internet IP)
  │
  │  POST https://your-webhook-url/webhook
  │
  ▼
Router (public IP: 203.0.113.42)
  │
  │  But which machine behind the router? Port 8000 is not forwarded.
  │  → Connection refused ❌
  │
  ▼
Your laptop (private IP: 192.168.1.100:8000)  ← unreachable
```

### How smee.io solves this

smee.io is a free relay service. It receives the webhook from GitHub and forwards
it to your local server via a persistent connection (Server-Sent Events).

```
GitHub → POST https://smee.io/abc123 → smee.io (internet, always reachable)
                                              │
                                    SSE long-lived connection
                                              │
                                              ▼
                                  smee-client (running on your laptop)
                                              │
                                   forwards to localhost:8000
                                              │
                                              ▼
                                    Your FastAPI server ✅
```

**smee-client command:**

```bash
smee --url https://smee.io/abc123 --target http://localhost:8000/webhook
```

### Why not ngrok?

ngrok is also a tunnelling tool. The difference:

|                   | smee.io                            | ngrok                                        |
| ----------------- | ---------------------------------- | -------------------------------------------- |
| **Cost**          | Free, no account needed            | Free tier is limited, URL changes on restart |
| **Designed for**  | Specifically webhooks              | General TCP tunnelling                       |
| **URL stability** | Permanent (you choose the channel) | Changes every restart (free tier)            |
| **Setup**         | `npm install -g smee-client`       | Download binary                              |

For GitHub webhooks specifically, smee.io is the simpler choice.

---

## 5. Environment Variables and the `.env` Pattern

### Why not hardcode config values?

```python
# NEVER do this:
API_KEY = "sk-abc123supersecret"
db_password = "mypassword123"

# Why:
# 1. Committed to git → visible to anyone who clones the repo
# 2. Git history is permanent — deleting the file doesn't remove it from history
# 3. Different environments (dev/staging/prod) need different values
```

### The `.env` pattern (12-Factor App principle)

```
.env          ← your REAL secrets (in .gitignore, never committed)
.env.example  ← template with placeholder values (committed, safe)
```

```bash
# .env.example (committed to git — no real values)
GITHUB_APP_ID=
GITHUB_WEBHOOK_SECRET=your_webhook_secret_here
OLLAMA_BASE_URL=http://localhost:11434

# .env (gitignored — your real values)
GITHUB_APP_ID=12345
GITHUB_WEBHOOK_SECRET=dfd5a9757e7cb6d72af9cc8267210e52f288cb8f
OLLAMA_BASE_URL=http://localhost:11434
```

### How python-dotenv loads them

```python
from dotenv import load_dotenv
import os

load_dotenv()  # reads .env file, sets each line as an environment variable

app_id = os.getenv("GITHUB_APP_ID")        # → "12345"
secret = os.getenv("GITHUB_WEBHOOK_SECRET") # → "dfd5a9..."
```

`load_dotenv()` only sets variables that aren't already in the environment.
This means real production environments (where you set env vars directly on the
server) override the `.env` file — which is the desired behaviour.

---

## 6. Ollama and Local LLMs

### What is Ollama?

Ollama is a tool for downloading and running open-source LLMs (Large Language
Models) entirely on your own machine. No internet required after the initial
model download. No API costs. No data leaves your machine.

### Why local instead of OpenAI/Gemini API?

|              | OpenAI / Gemini API           | Ollama (local)               |
| ------------ | ----------------------------- | ---------------------------- |
| **Cost**     | Pay per token                 | Free after hardware          |
| **Privacy**  | Code sent to external servers | Stays on your machine        |
| **Latency**  | ~1-3 seconds (network + API)  | Depends on hardware          |
| **Internet** | Required                      | Not after initial pull       |
| **Control**  | None                          | Full (change models anytime) |

For a code review agent that processes private code, local is a strong choice.

### Models we use

```bash
ollama pull llama3        # Main LLM for analysis and text generation
                          # Llama3 (Meta) — 8B parameters, good at code

ollama pull nomic-embed-text  # Embedding model — converts text to vectors
                              # Dedicated embedding model (DO NOT use llama3 for embedding)
```

Why a SEPARATE embedding model? Llama3 is optimised to GENERATE text.
`nomic-embed-text` is optimised to REPRESENT text as meaningful vectors.
Using a generation model for embedding gives lower quality retrieval.

### Ollama API

Ollama exposes a local HTTP server at `http://localhost:11434`.
LangChain's `ChatOllama` communicates with it:

```python
from langchain_ollama import ChatOllama

llm = ChatOllama(
    model="llama3",
    base_url="http://localhost:11434",
    temperature=0.2,
)

response = llm.invoke("What is 2 + 2?")
print(response.content)  # "4"
```

---

## 7. ChromaDB

### What is ChromaDB?

ChromaDB is an open-source vector database that runs entirely locally.
It stores embeddings (vectors) alongside the original text, allowing
fast similarity search.

### What is a vector/embedding?

An embedding is a fixed-length list of floating point numbers that represents
the MEANING of text in mathematical space.

```
"def connect_to_database():"    → [0.12, -0.34, 0.87, ...]  (768 numbers)
"establish database connection" → [0.11, -0.36, 0.85, ...]  (768 numbers)
"make a cup of tea"             → [-0.72, 0.41, -0.23, ...] (768 numbers)
```

The first two have similar meanings → their vectors are CLOSE (low distance).
The third is unrelated → its vector is FAR from the database-related ones.

### ChromaDB in-memory vs persistent

```python
# In-memory — data lost when Python process exits
import chromadb
client = chromadb.Client()

# Persistent — saved to disk, survives restarts ← we use this
client = chromadb.PersistentClient(path="./chroma_db")
```

We use `PersistentClient` so the index built from the codebase doesn't need
to be rebuilt every time the server restarts.

---

## Interview Questions — Milestone 1 Topics

---

**Q1: What is the difference between a GitHub App and a Personal Access Token?**

> A PAT is tied to a user account — if that user leaves or rotates the token,
> integrations break. A GitHub App is an independent identity with its own
> permissions, installed per-repository, and authenticates using RSA key pairs
> with short-lived tokens. It's more secure, auditable, and suitable for production
> automations because it doesn't depend on any individual user's account.

---

**Q2: How does JWT authentication work in your project?**

> We use a two-step process. First, we sign a JWT using our GitHub App's RSA
> private key (RS256 algorithm). The JWT payload contains the App ID as `iss`,
> an `iat` (issued at, set 60 seconds in the past for clock skew tolerance),
> and an `exp` (expiry at 10 minutes). We POST this JWT to GitHub's
> `/app/installations/{id}/access_tokens` endpoint. GitHub verifies it using
> the public key we uploaded, and returns a short-lived installation token valid
> for 1 hour. We use that token as a Bearer token for all subsequent API calls.

---

**Q3: Why is `hmac.compare_digest()` used instead of `==` for comparing webhook signatures?**

> `==` in Python short-circuits — it stops comparing as soon as it finds a mismatch.
> An attacker can measure how long comparison takes: longer time = more matching
> characters. By repeatedly sending slightly different signatures and timing the
> response, they can reconstruct the correct signature character by character.
> This is called a timing attack. `hmac.compare_digest()` always takes the same
> amount of time regardless of where (or if) a mismatch occurs, eliminating the
> timing side-channel.

---

**Q4: What is the 12-Factor App methodology and how did you apply it?**

> The 12-Factor App is a methodology for building software-as-a-service apps
> that are portable and resilient. We applied Factor III (Config): storing all
> configuration that varies between environments (API keys, URLs, secrets) in
> environment variables, never in code. We use `.env` for local development
> (gitignored) and `.env.example` as a committed template. This means the same
> codebase can run locally, in a colleague's machine, or in CI without any
> code changes — just different env vars.

---

**Q5: Why did you choose FastAPI over Flask or Django?**

> FastAPI has three main advantages for this project. First, native async/await
> support — our webhook handler calls GitHub APIs and the Ollama LLM, both of
> which are I/O operations. With async, the server can handle other requests
> while waiting for those responses. Flask needs workarounds for this. Second,
> automatic OpenAPI documentation — FastAPI generates a Swagger UI at `/docs`
> for free. Third, Pydantic for request/response validation — though we use
> it lightly here. Django would be overkill as a full MVC framework for what
> is essentially a webhook server and API.

---

**Q6: Why use a virtual environment and what problem does it solve?**

> Python has one global package installation directory per Python version.
> Without virtual environments, two projects needing different versions of
> the same library (e.g. `langchain==0.1.0` vs `langchain==0.2.0`) would
> conflict — installing one breaks the other. A virtual environment creates
> an isolated directory with its own Python interpreter and `site-packages`,
> so each project has its own dependencies. It's similar to how Node.js has
> `node_modules` per project.

---

**Q7: What is the difference between polling and webhooks? When would you use each?**

> Polling means your server repeatedly asks an external service "anything new?"
> on a schedule. Webhooks mean the external service calls YOUR server when
> something happens (event-driven). Polling wastes requests and adds latency
> (you might poll every minute but the event happened 1 second after your last
> poll). Webhooks are immediate but require your server to be reachable from
> the internet. You'd use polling when the external service doesn't support
> webhooks, or when eventual consistency is acceptable. We use webhooks here
> so code reviews start immediately when a PR is opened.

---

**Q8: What is RSA and how does asymmetric cryptography work?**

> RSA is an asymmetric encryption algorithm. It uses two mathematically linked
> keys: a private key (kept secret by you) and a public key (shared openly).
> What one key encrypts, only the other can decrypt. For digital signatures,
> you SIGN with the private key and anyone with the public key can VERIFY the
> signature. The security relies on the mathematical difficulty of factoring
> large prime numbers — computing the private key from the public key would
> take more time than the universe has existed with current hardware.

---

**Q9: What is a local LLM and what are the tradeoffs vs cloud APIs?**

> A local LLM (like Llama3 via Ollama) runs entirely on your own hardware.
> Tradeoffs: Local is free after initial setup, private (no data sent externally),
> and works offline, but is slower on CPU and requires a machine with enough RAM
> (Llama3 8B needs ~8GB RAM). Cloud APIs (OpenAI, Gemini) are faster, require no
> hardware investment, but cost money per token and send your data to external
> servers. For a code review tool handling private codebases, local is a strong
> choice from a privacy standpoint.

---

**Q10: What is an embedding and why does code review need a separate embedding model?**

> An embedding is a fixed-length vector of floating point numbers that represents
> the semantic meaning of text in a high-dimensional space. Texts with similar
> meaning have vectors that are mathematically close. We use a dedicated embedding
> model (nomic-embed-text) rather than the generation model (llama3) because they
> are optimised for different tasks. Generation models are trained to predict the
> next token. Embedding models are trained to produce vectors where similar
> meanings cluster together (contrastive learning). Using llama3 for embeddings
> produces lower quality vectors and therefore worse retrieval results.
