# ══════════════════════════════════════════════════════════════════════════════
# StockPilot AI — Developer Makefile
# ══════════════════════════════════════════════════════════════════════════════
# Usage:
#   make install      Install all Python dependencies
#   make run          Start backend + frontend (Python mode, no Docker)
#   make backend      Start FastAPI backend only
#   make frontend     Start Streamlit frontend only
#   make docker-up    Build and start all services via Docker Compose
#   make docker-down  Stop all Docker services
#   make docker-logs  Tail logs from all Docker services
#   make lint         Run ruff linter on all Python files
#   make clean        Remove cache files and logs
# ══════════════════════════════════════════════════════════════════════════════

.PHONY: install run backend frontend docker-up docker-down docker-logs lint clean help

# ── Configuration ─────────────────────────────────────────────────────────────
PYTHON     ?= python
PIP        ?= pip
BACKEND_DIR = backend
FRONTEND_DIR= frontend
LOG_DIR     = .

install:
	$(PIP) install -r requirements.txt

# ── Development servers ────────────────────────────────────────────────────────
backend:
	@echo "🚀  Starting StockPilot AI backend (FastAPI + 6 MCP servers)…"
	cd $(BACKEND_DIR) && $(PYTHON) orchestrator.py

frontend:
	@echo "🚀  Starting StockPilot AI frontend (Streamlit)…"
	cd $(FRONTEND_DIR) && streamlit run app.py --server.port 8501

run:
	@echo "🚀  Starting StockPilot AI (backend + frontend in background)…"
	@cd $(BACKEND_DIR) && $(PYTHON) orchestrator.py > ../backend.log 2>&1 & echo "Backend PID: $$!"
	@sleep 15
	@cd $(FRONTEND_DIR) && streamlit run app.py --server.port 8501 --server.headless true > ../frontend.log 2>&1 & echo "Frontend PID: $$!"
	@echo ""
	@echo "  Backend : http://127.0.0.1:8000"
	@echo "  API Docs: http://127.0.0.1:8000/docs"
	@echo "  Frontend: http://127.0.0.1:8501"
	@echo ""
	@echo "  Logs: backend.log | frontend.log"
	@echo "  Stop: make stop"

stop:
	@echo "⏹️   Stopping all StockPilot AI processes…"
	-pkill -f "orchestrator.py" 2>/dev/null || true
	-pkill -f "streamlit run app.py" 2>/dev/null || true
	@echo "Done."

# ── Docker ────────────────────────────────────────────────────────────────────
docker-up:
	@echo "🐳  Building and starting StockPilot AI via Docker Compose…"
	docker compose up --build -d
	@echo ""
	@echo "  Backend : http://localhost:8000"
	@echo "  Frontend: http://localhost:8501"
	@echo "  Logs    : make docker-logs"

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

docker-restart:
	docker compose down && docker compose up --build -d

# ── Code quality ──────────────────────────────────────────────────────────────
lint:
	@echo "🔍  Running ruff linter…"
	ruff check backend/ frontend/ mcp_servers/ --ignore E501

format:
	@echo "🎨  Running ruff formatter…"
	ruff format backend/ frontend/ mcp_servers/

# ── Cleanup ───────────────────────────────────────────────────────────────────
clean:
	@echo "🧹  Cleaning cache files and logs…"
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "*.log" -delete 2>/dev/null || true
	find . -name ".DS_Store" -delete 2>/dev/null || true
	@echo "Done."

# ── Help ──────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  StockPilot AI — Available make targets"
	@echo "  ───────────────────────────────────────"
	@echo "  make install      Install Python dependencies from requirements.txt"
	@echo "  make run          Start backend + frontend (background, logs to *.log)"
	@echo "  make stop         Stop all background processes"
	@echo "  make backend      Start FastAPI backend only (foreground)"
	@echo "  make frontend     Start Streamlit frontend only (foreground)"
	@echo "  make docker-up    Build + start via Docker Compose (detached)"
	@echo "  make docker-down  Stop Docker Compose services"
	@echo "  make docker-logs  Tail Docker Compose logs"
	@echo "  make lint         Run ruff linter"
	@echo "  make format       Run ruff formatter"
	@echo "  make clean        Remove __pycache__, *.pyc, *.log files"
	@echo ""
