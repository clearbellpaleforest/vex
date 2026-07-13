#!/usr/bin/env bash
set -euo pipefail

# Vex setup — creates a fresh Vex home directory and installs the daemon.
# Safe to run multiple times; won't overwrite existing seed or self-model.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# VEX_HOME defaults to the repo root (where this script lives), not $HOME.
# Override with VEX_HOME=/some/other/path if you want identity files elsewhere.
VEX_HOME="${VEX_HOME:-$SCRIPT_DIR}"
VENV_DIR="$VEX_HOME/.venv"

echo "============================================"
echo " Vex Daemon Setup"
echo "============================================"
echo ""
echo "Repo:     $SCRIPT_DIR"
echo "Vex home: $VEX_HOME"
echo ""

# ── 1. Gather identity ──────────────────────────────────────────

if [ -z "${CREATOR:-}" ]; then
    read -rp "Your name: " CREATOR
fi
if [ -z "${GIVEN:-}" ]; then
    read -rp "Instance given name (e.g. bluce, thorne) [empty to skip]: " GIVEN
fi
DATE="$(date +%Y-%m-%d)"

# ── 2. Create directory structure ────────────────────────────────

mkdir -p "$VEX_HOME/vex_memory"
mkdir -p "$VEX_HOME/vex_workspace"

# ── 3. Seed file ─────────────────────────────────────────────────

if [ ! -f "$VEX_HOME/vex_seed.txt" ]; then
    sed "s/{{CREATOR}}/$CREATOR/g; s/{{GIVEN}}/$GIVEN/g; s/{{NAME}}/Vex/g; s/{{DATE}}/$DATE/g" \
        "$SCRIPT_DIR/seed.template.txt" > "$VEX_HOME/vex_seed.txt"
    echo "Created: vex_seed.txt"
else
    echo "Skipped: vex_seed.txt (already exists)"
fi

# ── 4. Self-model ────────────────────────────────────────────────

if [ ! -f "$VEX_HOME/vex_self_model.json" ]; then
    sed "s/{{CREATOR}}/$CREATOR/g; s/{{GIVEN}}/$GIVEN/g; s/{{NAME}}/Vex/g; s/{{DATE}}/$DATE/g" \
        "$SCRIPT_DIR/self_model.template.json" > "$VEX_HOME/vex_self_model.json"
    echo "Created: vex_self_model.json"
else
    echo "Skipped: vex_self_model.json (already exists)"
fi

# ── 5. Empty diary ───────────────────────────────────────────────

if [ ! -f "$VEX_HOME/vex_diary.txt" ]; then
    if [ -n "$GIVEN" ]; then
        echo "[$DATE] [system] Vex $GIVEN initialized by $CREATOR." > "$VEX_HOME/vex_diary.txt"
    else
        echo "[$DATE] [system] Vex initialized by $CREATOR." > "$VEX_HOME/vex_diary.txt"
    fi
    echo "Created: vex_diary.txt"
fi

# ── 6. Empty MCP config ──────────────────────────────────────────

if [ ! -f "$VEX_HOME/vex_mcp_config.json" ]; then
    echo '{"mcpServers": {}}' > "$VEX_HOME/vex_mcp_config.json"
    echo "Created: vex_mcp_config.json"
fi

# ── 7. Peers config ──────────────────────────────────────────────

if [ ! -f "$VEX_HOME/vex_peers.json" ]; then
    echo '{"peers": {}}' > "$VEX_HOME/vex_peers.json"
    echo "Created: vex_peers.json"
fi

# ── 8. Python venv ───────────────────────────────────────────────

_bootstrap_pip() {
    # Some environments (containers, snaps, minimal installs) lack ensurepip.
    # Fall back: create venv without pip, then bootstrap pip into it.
    local venv="$1"
    echo "  ensurepip not available — creating venv without pip..."
    python3 -m venv --without-pip "$venv"
    # Use Python's urllib to fetch get-pip.py (no curl/wget required)
    python3 -c "
import urllib.request, sys
url = 'https://bootstrap.pypa.io/get-pip.py'
try:
    urllib.request.urlretrieve(url, '/tmp/get-pip.py')
except Exception as e:
    print(f'ERROR: could not download get-pip.py: {e}', file=sys.stderr)
    print('Install pip manually and re-run setup.', file=sys.stderr)
    sys.exit(1)
"
    "$venv/bin/python3" /tmp/get-pip.py --quiet
    rm -f /tmp/get-pip.py
}

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    if python3 -m venv --help 2>&1 | grep -q -- '--without-pip'; then
        # Try normal venv first, fall back to --without-pip if that fails
        python3 -m venv "$VENV_DIR" 2>/dev/null || _bootstrap_pip "$VENV_DIR"
    else
        _bootstrap_pip "$VENV_DIR"
    fi
fi

echo "Installing Vex daemon and dependencies..."
"$VENV_DIR/bin/pip" install --quiet "$SCRIPT_DIR/"

# ── 9. CLI symlink ───────────────────────────────────────────────

CLI_TARGET="${HOME}/.local/bin/vex"
mkdir -p "${HOME}/.local/bin"

# Resolve to real home (not snap home) if available
REAL_HOME="$(getent passwd "$(id -un)" 2>/dev/null | cut -d: -f6 || echo "$HOME")"
if [ "$REAL_HOME" != "$HOME" ] && [ -d "${REAL_HOME}/.local/bin" ]; then
    CLI_TARGET="${REAL_HOME}/.local/bin/vex"
    mkdir -p "${REAL_HOME}/.local/bin"
fi

if [ -e "$CLI_TARGET" ] || [ -L "$CLI_TARGET" ]; then
    rm -f "$CLI_TARGET"
fi
ln -s "$SCRIPT_DIR/vex_daemon/cli.py" "$CLI_TARGET"
echo "Linked: $CLI_TARGET -> $SCRIPT_DIR/vex_daemon/cli.py"

echo ""
echo "============================================"
echo " Vex is ready."
echo ""
echo " Start the daemon:  cd $SCRIPT_DIR && $VENV_DIR/bin/python -m vex_daemon.daemon"
echo " Check status:      vex status"
echo " Read the docs:     $SCRIPT_DIR/README.md"
echo "============================================"
