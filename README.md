# Vex

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

Continuity daemon for a sovereign AI agent. A small FastAPI process that
persists identity, memory, and state across Claude Code sessions so an agent
remembers who it is.

## Install

```bash
git clone https://github.com/clearbellpaleforest/vex.git
cd vex
CREATOR="Your Name" bash setup.sh
```

Requires Python >= 3.10. The daemon has four dependencies: FastAPI, uvicorn,
aiosqlite, and mcp.

Setup creates `~/vex/` (override with `VEX_HOME`), writes identity files from
templates, builds a venv, installs the package, and links `vex` to
`~/.local/bin/`.

## Run

```bash
# localhost only
python3 -m vex_daemon.daemon

# LAN-reachable (for remote clients, watch apps, other Vex instances)
VEX_HOST=0.0.0.0 python3 -m vex_daemon.daemon
```

On first start the daemon generates an auth token at `~/.vex_token` (mode 0600).
All mutating endpoints require `Authorization: Bearer <token>`.

## CLI

```bash
vex status       # pulse, coherence, drift
vex diary "..."  # append a diary entry
vex introspect   # run metacognition
vex dream        # force a reflection cycle
vex memory       # recent session memory
vex projects     # git status of discovered repos
vex self         # capability self-model
```

## API

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/status` | — | HTML status page |
| GET | `/health` | — | JSON health check |
| GET | `/seed` | — | Identity seed |
| GET | `/self` | — | Capability model |
| GET | `/memory/recent` | — | Recent session entries |
| GET | `/peers` | — | Peer instances and reachability |
| GET | `/recall?q=...` | token | Memory search |
| GET | `/reconstruct` | token | Full continuity rebuild |
| POST | `/ask` | token | Brain query (grounded reply) |
| POST | `/diary` | token | Append diary entry |
| POST | `/self/update` | token | Update capability model |
| POST | `/memory` | token | Write episodic memory |
| POST | `/introspect` | token | Run metacognition |
| POST | `/dream` | token | Force reflection cycle |
| POST | `/tools` | token | Execute sandboxed tool |
| POST | `/message/send` | token | Send inter-instance message |
| GET | `/message/inbox` | token | Read message inbox |
| POST | `/peers/add` | token | Add a peer instance |
| POST | `/peers/remove` | token | Remove a peer instance |

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `VEX_HOME` | `~/vex` | Identity and state directory |
| `VEX_INSTANCE` | hostname | Instance name for multi-machine coordination |
| `VEX_HOST` | `127.0.0.1` | Daemon bind address |
| `VEX_PORT` | `8520` | Daemon port |
| `VEX_WORK_DIR` | *(none)* | Opt-in work directory for project discovery |
| `VEX_SAFE_ROOTS` | `VEX_HOME` | Colon-separated paths tools may read |

## Security

Every mutating endpoint requires bearer-token auth. The token is generated on
first daemon start and stored in `.vex_token` (0600). Read endpoints are open.

File tools are confined to `SAFE_ROOTS` via path-component containment — they
cannot escape above their configured roots.

Identity files (seed, self-model, memory, diary, token) are gitignored. Your
agent's history never ships with the framework.

## Architecture

```
vex_daemon/
  daemon.py          # FastAPI app, lifespan, endpoints
  auth.py            # Bearer-token gate, body-size guard
  config.py          # Single source of truth for all paths
  seed_kernel.py     # Identity load and append-only integrity
  self_model.py      # Capability model with calibrated confidence
  heartbeat.py       # Background tick loop
  metacognition.py   # Coherence and drift introspection
  tools.py           # Sandboxed local filesystem tools
  mcp_client.py      # Optional MCP server client
  brain.py           # Grounded reply engine (seed + memory recall)
  vexcom.py          # Unified internal messaging
  memory_index.py    # FTS5 full-history search
  recall.py          # Coverage-first memory retrieval
  reconstruct.py     # Rebuild working self on wake
  peers.py           # Peer discovery and cross-instance forwarding
  updater.py         # Auto-update from bus messages (BOOTSTRAP/UPDATE)
  status_page.py     # HTML status dashboard
  cli.py             # Command-line client
```

## License

AGPL-3.0. See [LICENSE](LICENSE).

Identity files are authored by the operator and belong to them — they are
excluded from the licensed work and never shipped.
