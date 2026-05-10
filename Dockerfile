# ── Stage: runtime ───────────────────────────────────────────────────────────
# python:3.11-slim is a minimal Debian image with just Python.
# We avoid the full python:3.11 image (~900MB) since we don't need dev tools.
# 'slim' saves ~600MB — important when the image will be pulled frequently.
FROM python:3.11-slim

# Set working directory inside the container.
# All subsequent COPY / RUN commands are relative to this path.
WORKDIR /app

# ── Install system dependencies ───────────────────────────────────────────────
# We need gcc for some Python packages that compile C extensions (e.g. chromadb).
# --no-install-recommends keeps the layer small.
# We clean apt cache in the same layer to avoid bloating the image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# ── Install Python dependencies ───────────────────────────────────────────────
# Copy requirements BEFORE the rest of the source code.
# Docker caches each layer. If only source code changes (not requirements.txt),
# Docker reuses the pip install layer — much faster rebuilds.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Copy source code ──────────────────────────────────────────────────────────
# .dockerignore excludes .venv, myenv, __pycache__, .git, secrets/ etc.
# so those never enter the image.
COPY . .

# ── Security: run as non-root user ────────────────────────────────────────────
# Running as root inside a container is a security risk — if the container is
# compromised, the attacker has root on the container filesystem.
# We create a dedicated 'appuser' and switch to it.
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

# Document the port the app listens on (informational — doesn't open the port).
EXPOSE 8000

# ── Health check ──────────────────────────────────────────────────────────────
# Docker will call GET /ping every 30s. If it fails 3 times, the container
# is marked unhealthy — docker-compose can then restart it automatically.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/ping').raise_for_status()"

# Start the FastAPI app.
# --host 0.0.0.0 makes it reachable from outside the container (not just localhost).
# Remove --reload in production (it watches filesystem for changes, wastes CPU).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
