# Orchestrator APP image — source code only, layered on the prebuilt base.
#
# OS packages and pip install live in backend/Dockerfile.base, published to
# GHCR and tagged with a hash of requirements.txt. That keeps the ~1 GB
# dependency layer's digest stable across deploys, so the e2-micro reports
# "Already exists" instead of re-extracting it for a code-only change.
#
# BASE_IMAGE is supplied by the deploy workflow as the exact hash-tagged base.
# The :latest default is for local `docker compose build`; CI never relies on it,
# because :latest can lag behind requirements.txt.
ARG BASE_IMAGE=ghcr.io/tusharmishra288/stockpilotai/orchestrator-base:latest
FROM ${BASE_IMAGE}

# Build context must be the project root (set in docker-compose.yml)
# This lets us copy mcp_servers/ which sits at the root.

WORKDIR /app

# Copy MCP server scripts.
# The orchestrator spawns these as stdio subprocesses; they must be present
# at /app/mcp_servers/<region>/server.py (one level above /app/backend/).
COPY mcp_servers/ ./mcp_servers/

# Copy backend source
COPY backend/ ./backend/

# Run from backend/ so Python's implicit sys.path entry covers backend/services/
WORKDIR /app/backend

EXPOSE 8000

# Wait up to 90 s for MCP servers to start before declaring unhealthy.
# Parses the body rather than just checking the request succeeds: /health
# returns HTTP 200 even when status is "degraded", so a bare urlopen() would
# report healthy with dead MCP servers.
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=5 \
    CMD python -c "import urllib.request,json,sys; d=json.load(urllib.request.urlopen('http://localhost:8000/health')); sys.exit(0 if d['status']=='healthy' else 1)" \
    || exit 1

CMD ["python", "orchestrator.py"]
