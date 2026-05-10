#!/usr/bin/env bash
# setup.sh — one-command local setup for Mac/Linux
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
#
# What this does:
#   1. Checks prerequisites (Python, Ollama, Docker)
#   2. Creates Python virtual environment
#   3. Installs dependencies
#   4. Copies .env.example to .env if not already present
#   5. Pulls required Ollama models
#   6. Starts Docker services (FastAPI + ChromaDB)

set -e  # exit immediately if any command fails

# ── Colours for output ────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'  # no colour

ok()   { echo -e "${GREEN}✅ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
fail() { echo -e "${RED}❌ $1${NC}"; exit 1; }

echo ""
echo "🤖 AI GitHub Review Agent — Setup"
echo "===================================="
echo ""

# ── Step 1: Check Python ──────────────────────────────────────────────────────
PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ]; then
    fail "Python 3.11+ is required. Install via: brew install python@3.11"
fi
PY_VERSION=$($PY --version 2>&1 | awk '{print $2}')
ok "Python found: $PY_VERSION"

# ── Step 2: Check Ollama ──────────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
    warn "Ollama not found. Install via: brew install ollama"
    warn "Then run: ollama serve  (in a separate terminal)"
else
    ok "Ollama found"
fi

# ── Step 3: Check Docker ──────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    warn "Docker not found. Install Docker Desktop from https://docker.com"
else
    ok "Docker found"
fi

# ── Step 4: Create virtual environment ───────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo ""
    echo "📦 Creating Python virtual environment (.venv)..."
    $PY -m venv .venv
    ok "Virtual environment created"
else
    ok "Virtual environment already exists"
fi

# Activate venv
source .venv/bin/activate
ok "Virtual environment activated"

# ── Step 5: Install dependencies ──────────────────────────────────────────────
echo ""
echo "📦 Installing Python dependencies..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
ok "Dependencies installed"

# ── Step 6: Configure .env ────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    cp .env.example .env
    warn ".env created from .env.example — fill in your GitHub App credentials"
else
    ok ".env already exists"
fi

# ── Step 7: Pull Ollama models ────────────────────────────────────────────────
if command -v ollama &>/dev/null; then
    echo ""
    echo "🤖 Pulling Ollama models (this may take a few minutes on first run)..."
    # Check if ollama is running
    if curl -s http://localhost:11434/api/tags &>/dev/null; then
        ollama pull llama3 && ok "llama3 ready"
        ollama pull nomic-embed-text && ok "nomic-embed-text ready"
    else
        warn "Ollama server not running. Start it with: ollama serve"
        warn "Then pull models manually:"
        warn "  ollama pull llama3"
        warn "  ollama pull nomic-embed-text"
    fi
fi

# ── Step 8: Start Docker services ────────────────────────────────────────────
if command -v docker &>/dev/null; then
    echo ""
    echo "🐳 Starting Docker services (FastAPI + ChromaDB)..."
    if docker info &>/dev/null 2>&1; then
        docker compose up --build -d
        ok "Docker services started"
        echo ""
        echo "   FastAPI:  http://localhost:8000"
        echo "   ChromaDB: http://localhost:8001"
        echo "   Dashboard: http://localhost:8000/dashboard"
    else
        warn "Docker daemon not running. Start Docker Desktop then run:"
        warn "  docker compose up --build -d"
    fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "===================================="
ok "Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Fill in .env with your GitHub App ID and webhook secret"
echo "  2. Place your private-key.pem in secrets/"
echo "  3. Run smee: smee --url YOUR_SMEE_URL --path /webhook --port 8000"
echo "  4. Open a PR on your test repo and watch the agent review it"
echo ""
echo "Run tests:  source .venv/bin/activate && pytest tests/ -v"
echo "Logs:       docker compose logs -f app"
echo ""
