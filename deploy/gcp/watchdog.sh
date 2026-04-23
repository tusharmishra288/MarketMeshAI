#!/bin/bash
# =============================================================================
# MarketMesh AI — VM health watchdog (runs every 5 min via cron)
#
# Checks /health on the local orchestrator. If any MCP server is not
# "healthy", restarts the orchestrator container so all 6 MCP subprocesses
# are respawned fresh.
#
# Installed automatically by the deploy workflow into:
#   /usr/local/bin/marketmesh-watchdog
# Crontab entry (marketmesh user):
#   */5 * * * * /usr/local/bin/marketmesh-watchdog >> /var/log/marketmesh-watchdog.log 2>&1
#
# Recovery timeline:
#   MCP subprocess dies → watchdog detects in ≤60s (in-process ping task)
#   → /health returns "degraded" → cron runs within ≤5min → docker restart
#   → orchestrator back online in ~2min (MCP servers re-initialise)
#   Total worst-case downtime: ~7 minutes, fully automatic.
# =============================================================================

set -euo pipefail

LOG_PREFIX="$(date '+%Y-%m-%d %H:%M:%S') [marketmesh-watchdog]"
COMPOSE_FILE="/opt/marketmesh/docker-compose-gcp.yml"

# ── Check health endpoint ──────────────────────────────────────────────────
HEALTH=$(curl -sf --max-time 10 http://localhost:8000/health 2>/dev/null || echo "")

if [ -z "$HEALTH" ]; then
    echo "$LOG_PREFIX No response from /health — restarting orchestrator"
    cd /opt/marketmesh
    sudo docker compose -f "$COMPOSE_FILE" restart orchestrator
    exit 0
fi

STATUS=$(echo "$HEALTH" | python3 -c \
    "import sys, json; print(json.load(sys.stdin).get('status', 'unknown'))" \
    2>/dev/null || echo "parse_error")

if [ "$STATUS" != "healthy" ]; then
    echo "$LOG_PREFIX Status='$STATUS' — restarting orchestrator"
    cd /opt/marketmesh
    sudo docker compose -f "$COMPOSE_FILE" restart orchestrator
    echo "$LOG_PREFIX Restart issued"
else
    # All good — log nothing (keeps log file clean; only failures are recorded)
    :
fi
