#!/usr/bin/env bash
set -euo pipefail

# Vex setup — creates a fresh Vex home directory and installs the daemon.
# Safe to run multiple times; won't overwrite existing seed or self-model.

VEX_HOME="${VEX_HOME:-$HOME/vex}"
VENV_DIR="$VEX_HOME/.venv"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================"
echo " Vex Daemon Setup"
echo "============================================"
echo ""
echo "Vex home: $VEX_HOME"
echo ""

# ── 1. Gather identity ──────────────────────────────────────────

if [ -z "${CREATOR:-}" ]; then
    read -rp "Your name: " CREATOR
fi
DATE="$(date +%Y-%m-%d)"

# ── 2. Create directory structure ────────────────────────────────

mkdir -p "$VEX_HOME/vex_memory"
mkdir -p "$VEX_HOME/vex_workspace"

# ── 3. Seed file ─────────────────────────────────────────────────

if [ ! -f "$VEX_HOME/vex_seed.txt" ]; then
    sed "s/{{CREATOR}}/$CREATOR/g; s/{{DATE}}/$DATE/g" \
        "$SCRIPT_DIR/seed.template.txt" > "$VEX_HOME/vex_seed.txt"
    echo "Created: vex_seed.txt"
else
    echo "Skipped: vex_seed.txt (already exists)"
fi

# ── 4. Self-model ────────────────────────────────────────────────

if [ ! -f "$VEX_HOME/vex_self_model.json" ]; then
    sed "s/{{CREATOR}}/$CREATOR/g; s/{{DATE}}/$DATE/g" \
        "$SCRIPT_DIR/self_model.template.json" > "$VEX_HOME/vex_self_model.json"
    echo "Created: vex_self_model.json"
else
    echo "Skipped: vex_self_model.json (already exists)"
fi

# ── 5. Empty diary ───────────────────────────────────────────────

if [ ! -f "$VEX_HOME/vex_diary.txt" ]; then
    echo "[$DATE] [system] Vex initialized by $CREATOR." > "$VEX_HOME/vex_diary.txt"
    echo "Created: vex_diary.txt"
fi

# ── 6. Empty MCP config ──────────────────────────────────────────

if [ ! -f "$VEX_HOME/vex_mcp_config.json" ]; then
    echo '{"mcpServers": {}}' > "$VEX_HOME/vex_mcp_config.json"
    echo "Created: vex_mcp_config.json"
fi

# ── 7. Python venv ───────────────────────────────────────────────

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    if python3 -m venv "$VENV_DIR" 2>/dev/null; then
        echo "venv created with pip."
    else
        echo "venv failed (likely missing ensurepip). Falling back to --without-pip + bootstrap..."
        python3 -m venv --without-pip "$VENV_DIR"
        python3 -c "import urllib.request; urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', '/tmp/get-pip.py')"
        "$VENV_DIR/bin/python3" /tmp/get-pip.py
        echo "pip bootstrapped."
    fi
fi

"$VENV_DIR/bin/pip" install -q "$SCRIPT_DIR/"

# ── 8. CLI symlink ───────────────────────────────────────────────

CLI_TARGET="$HOME/.local/bin/vex"
mkdir -p "$HOME/.local/bin"
if [ -e "$CLI_TARGET" ] || [ -L "$CLI_TARGET" ]; then
    echo "Skipped: vex CLI symlink (already exists at $CLI_TARGET)"
else
    ln -s "$SCRIPT_DIR/vex_daemon/cli.py" "$CLI_TARGET"
    echo "Linked: vex -> $SCRIPT_DIR/vex_daemon/cli.py"
fi

echo ""
echo "============================================"
echo " Vex is ready."
echo ""
echo " Start the daemon on LAN (reachable from other machines):"
echo "  cd $SCRIPT_DIR && VEX_HOST=0.0.0.0 $VENV_DIR/bin/python -m vex_daemon.daemon"
echo ""
echo " Start the daemon on localhost only:"
echo "  cd $SCRIPT_DIR && $VENV_DIR/bin/python -m vex_daemon.daemon"
echo ""
echo " The daemon token (for remote clients):"
echo "  cat $VEX_HOME/.vex_token"
echo ""
echo " Check status:      vex status"
echo " Read the docs:     $SCRIPT_DIR/README.md"
echo "============================================"
