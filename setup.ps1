# setup.ps1 — one-command local setup for Windows (PowerShell)
#
# Usage (run in PowerShell as normal user):
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
#   .\setup.ps1
#
# What this does:
#   1. Checks prerequisites (Python, Docker)
#   2. Creates Python virtual environment
#   3. Installs dependencies
#   4. Copies .env.example to .env if not already present
#   5. Reminds you to start Ollama and pull models

$ErrorActionPreference = "Stop"

function Ok($msg)   { Write-Host "✅ $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "⚠️  $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "❌ $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "🤖 AI GitHub Review Agent — Setup" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Check Python ──────────────────────────────────────────────────────
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Fail "Python 3.11+ is required. Download from https://python.org"
}
$pyVer = & python --version 2>&1
Ok "Python found: $pyVer"

# ── Step 2: Check Docker ──────────────────────────────────────────────────────
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Warn "Docker not found. Install Docker Desktop from https://docker.com"
} else {
    Ok "Docker found"
}

# ── Step 3: Create virtual environment ───────────────────────────────────────
if (-not (Test-Path ".venv")) {
    Write-Host ""
    Write-Host "📦 Creating Python virtual environment (.venv)..."
    python -m venv .venv
    Ok "Virtual environment created"
} else {
    Ok "Virtual environment already exists"
}

# Activate
& .\.venv\Scripts\Activate.ps1
Ok "Virtual environment activated"

# ── Step 4: Install dependencies ──────────────────────────────────────────────
Write-Host ""
Write-Host "📦 Installing Python dependencies..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
Ok "Dependencies installed"

# ── Step 5: Configure .env ────────────────────────────────────────────────────
if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Warn ".env created from .env.example — fill in your GitHub App credentials"
} else {
    Ok ".env already exists"
}

# ── Step 6: Ollama reminder ───────────────────────────────────────────────────
Write-Host ""
Warn "Ollama must be started manually on Windows:"
Warn "  1. Download from https://ollama.com/download"
Warn "  2. Run: ollama serve"
Warn "  3. In another terminal: ollama pull llama3.1:8b"
Warn "  4. In another terminal: ollama pull nomic-embed-text"

# ── Step 7: Docker compose ────────────────────────────────────────────────────
if ($docker) {
    Write-Host ""
    Write-Host "🐳 Starting Docker services (FastAPI + ChromaDB)..."
    try {
        docker info 2>&1 | Out-Null
        docker compose up --build -d
        Ok "Docker services started"
        Write-Host ""
        Write-Host "   FastAPI:   http://localhost:8000" -ForegroundColor Cyan
        Write-Host "   ChromaDB:  http://localhost:8001" -ForegroundColor Cyan
        Write-Host "   Dashboard: http://localhost:8000/dashboard" -ForegroundColor Cyan
    } catch {
        Warn "Docker daemon not running. Start Docker Desktop, then run:"
        Warn "  docker compose up --build -d"
    }
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "====================================" -ForegroundColor Cyan
Ok "Setup complete!"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Fill in .env with your GitHub App ID and webhook secret"
Write-Host "  2. Place your private-key.pem in secrets\"
Write-Host "  3. Run: smee --url YOUR_SMEE_URL --path /webhook --port 8000"
Write-Host ""
Write-Host "Run tests:  .\.venv\Scripts\Activate.ps1; pytest tests\ -v"
Write-Host "Logs:       docker compose logs -f app"
Write-Host ""
