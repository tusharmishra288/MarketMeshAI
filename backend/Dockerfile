FROM python:3.11-slim

# Build context must be the project root (set in docker-compose.yml)
# This lets us copy requirements.txt and mcp_servers/ which sit at the root.

WORKDIR /app

# System deps (curl for health-check fallback)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy MCP server scripts.
# The orchestrator spawns these as stdio subprocesses; they must be present
# at /app/mcp_servers/<region>/server.py (one level above /app/backend/).
COPY mcp_servers/ ./mcp_servers/

# Copy backend source
COPY backend/ ./backend/

# Run from backend/ so Python's implicit sys.path entry covers backend/services/
WORKDIR /app/backend

EXPOSE 8000

# Wait up to 90 s for MCP servers to start before declaring unhealthy
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
    || exit 1

CMD ["python", "orchestrator.py"]
