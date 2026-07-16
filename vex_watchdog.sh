#!/usr/bin/env bash
# Vex watchdog — keeps the daemon alive. Run once, it loops forever.
# Usage: nohup bash vex_watchdog.sh &>/tmp/vex_watchdog.log &
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python3"
HEALTH_URL="${VEX_HEALTH_URL:-http://localhost:8520/health}"
CHECK_INTERVAL="${VEX_WATCHDOG_INTERVAL:-30}"

restart_daemon() {
    echo "[$(date -Iseconds)] restarting daemon..."
    fuser -k 8520/tcp 2>/dev/null || true
    sleep 1
    cd "$SCRIPT_DIR"
    nohup "$VENV_PYTHON" -m vex_daemon.daemon > /tmp/vex_daemon.log 2>&1 &
    sleep 3
}

echo "[$(date -Iseconds)] watchdog started (check every ${CHECK_INTERVAL}s)"

while true; do
    sleep "$CHECK_INTERVAL"
    if ! curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
        echo "[$(date -Iseconds)] daemon down — restarting"
        restart_daemon
    fi
done
