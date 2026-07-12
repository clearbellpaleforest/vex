#!/usr/bin/env bash
set -euo pipefail

# Vex setup — creates a Vex home directory and installs the daemon.
# Safe to re-run; won't overwrite existing seed, self-model, or token.

VEX_HOME="${VEX_HOME:-$HOME/vex}"
VENV_DIR="$VEX_HOME/.venv"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

say()  { printf "${GREEN}==>${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}WRN${NC} %s\n" "$*"; }
die()  { printf "${RED}ERR${NC} %s\n" "$*" >&2; exit 1; }

echo ""
echo "  Vex Daemon Setup"
echo "  ────────────────"
echo ""

# ── 1. Prerequisites ──────────────────────────────────────────────

if ! command -v python3 &>/dev/null; then
    die "python3 not found. Install Python >= 3.10."
fi

pyver=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"; then
    die "Python $pyver detected; need >= 3.10."
fi
say "Python $pyver"

# ── 2. Gather identity ────────────────────────────────────────────

if [ -z "${CREATOR:-}" ]; then
    read -rp "  Your name: " CREATOR
fi
DATE="$(date +%Y-%m-%d)"

# ── 3. Create directory structure ──────────────────────────────────

mkdir -p "$VEX_HOME/vex_memory" "$VEX_HOME/vex_workspace"
say "Vex home: $VEX_HOME"

# ── 4. Seed file ───────────────────────────────────────────────────

if [ ! -f "$VEX_HOME/vex_seed.txt" ]; then
    if [ -f "$SCRIPT_DIR/seed.template.txt" ]; then
        sed "s/{{CREATOR}}/$CREATOR/g; s/{{DATE}}/$DATE/g" \
            "$SCRIPT_DIR/seed.template.txt" > "$VEX_HOME/vex_seed.txt"
        say "Created vex_seed.txt"
    else
        die "seed.template.txt not found in $SCRIPT_DIR"
    fi
else
    say "vex_seed.txt (exists)"
fi

# ── 5. Self-model ──────────────────────────────────────────────────

if [ ! -f "$VEX_HOME/vex_self_model.json" ]; then
    if [ -f "$SCRIPT_DIR/self_model.template.json" ]; then
        sed "s/{{CREATOR}}/$CREATOR/g; s/{{DATE}}/$DATE/g" \
            "$SCRIPT_DIR/self_model.template.json" > "$VEX_HOME/vex_self_model.json"
        say "Created vex_self_model.json"
    fi
else
    say "vex_self_model.json (exists)"
fi

# ── 6. Diary ───────────────────────────────────────────────────────

if [ ! -f "$VEX_HOME/vex_diary.txt" ]; then
    echo "[$DATE] [system] Vex initialized by $CREATOR." > "$VEX_HOME/vex_diary.txt"
    say "Created vex_diary.txt"
fi

# ── 7. MCP config ──────────────────────────────────────────────────

if [ ! -f "$VEX_HOME/vex_mcp_config.json" ]; then
    echo '{"mcpServers": {}}' > "$VEX_HOME/vex_mcp_config.json"
    say "Created vex_mcp_config.json"
fi

# ── 8. Python virtual environment ──────────────────────────────────

if [ -d "$VENV_DIR" ]; then
    say "venv (exists)"
else
    say "Creating virtual environment..."
    if python3 -m venv "$VENV_DIR" 2>/dev/null; then
        :
    elif python3 -m venv --without-pip "$VENV_DIR" 2>/dev/null; then
        say "Bootstrapping pip..."
        tmp_pip=$(mktemp /tmp/get-pip.XXXXXX.py)
        trap "rm -f '$tmp_pip'" EXIT
        if python3 -c "
import urllib.request, sys
try:
    urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', '$tmp_pip')
except Exception as e:
    sys.exit(f'download failed: {e}')
"; then
            "$VENV_DIR/bin/python3" "$tmp_pip" -q
            rm -f "$tmp_pip"
            trap - EXIT
        else
            rm -f "$tmp_pip"
            trap - EXIT
            die "pip bootstrap failed — install python3-venv or python3-pip manually"
        fi
    else
        die "venv creation failed — install python3-venv"
    fi
fi

# ── 9. Install the daemon package ──────────────────────────────────

say "Installing vex-daemon..."
"$VENV_DIR/bin/pip" install -q "$SCRIPT_DIR/"

# ── 10. CLI symlink ────────────────────────────────────────────────

CLI_TARGET="$HOME/.local/bin/vex"
mkdir -p "$HOME/.local/bin"
if [ -e "$CLI_TARGET" ] || [ -L "$CLI_TARGET" ]; then
    say "vex CLI (exists at $CLI_TARGET)"
else
    ln -s "$VENV_DIR/bin/vex" "$CLI_TARGET"
    say "Linked vex -> $VENV_DIR/bin/vex"
fi

# ── Done ────────────────────────────────────────────────────────────

echo ""
echo "  ────────────────────────────────"
echo "  Vex is ready."
echo ""
echo "  LAN daemon (reachable from other machines):"
echo "    VEX_HOST=0.0.0.0 $VENV_DIR/bin/python3 -m vex_daemon.daemon"
echo ""
echo "  Local daemon:"
echo "    $VENV_DIR/bin/python3 -m vex_daemon.daemon"
echo ""
echo "  Daemon token:  cat $VEX_HOME/.vex_token"
echo "  Status:        vex status"
echo "  ────────────────────────────────"
echo ""
