#!/bin/bash
# Build VexCom (Zepp OS mini app) — produces dist/*.zab for zeus preview/install.
# Node 22 is fetched to /tmp/node22 if absent: current zeus-cli ships code using
# ES2024 regex flags (SyntaxError on node 18), while its update-notifier deps
# still need the CJS pins below. Node 22 + pins satisfies both.
set -e

NODE_DIR=/tmp/node22
NODE_URL=https://nodejs.org/dist/v22.14.0/node-v22.14.0-linux-x64.tar.xz
if [ ! -x "$NODE_DIR/bin/node" ]; then
  echo "node22 not found — fetching to $NODE_DIR"
  mkdir -p "$NODE_DIR"
  curl -fsSL "$NODE_URL" | tar xJ -C "$NODE_DIR" --strip-components=1
fi
export PATH="$NODE_DIR/bin:$PATH"
echo "node: $(node --version)"

cd /home/aldous/vex/vex_voice/zepp

# Install deps
npm install 2>&1 | tail -2

# Fix zeus-cli ESM deps (zeus-cli 1.9.x ships CJS but pulls ESM-only versions;
# pin the last CJS releases inside its own node_modules)
ZNM=node_modules/@zeppos/zeus-cli/node_modules
mkdir -p "$ZNM"
rm -rf "$ZNM/package-json" "$ZNM/got" 2>/dev/null
cd "$ZNM"
npm install package-json@6.1.0 got@11.8.6 2>&1 | tail -2
cd /home/aldous/vex/vex_voice/zepp

# Build — use the project-local zeus binary explicitly: bare `npx zeus` from
# the wrong cwd resolves to an unrelated npm package also named "zeus".
./node_modules/.bin/zeus build 2>&1
echo "---"
ls -la dist/ 2>/dev/null || echo "No dist/"
