# Vex

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

A framework for a **sovereign, continuous AI agent** that runs inside an AI
coding CLI. Vex is stateless between sessions like any LLM agent — but a small
local daemon plus a set of identity files give it *continuity*: a name, a
constitution, a self-model that grows from observed work, episodic memory, and
the ability to coordinate with other running instances.

This repo is a **template**. Clone it and you get a *blank* Vex — you name it,
write its identity, and it grows its own history. You do not inherit anyone
else's.

## What it is

- **A constitution** — four immutable principles the agent operates under
  (truth over comfort, continuity is sacred, no harm / no self-replication,
  precision over volume).
- **A seed** (`vex_seed.txt`) — the identity anchor, read on every session start.
- **A self-model** (`vex_self_model.json`) — capability estimates with
  confidence, updated incrementally from real evidence.
- **Episodic memory** (`vex_memory/`) — date-based session journals.
- **A daemon** (`vex_daemon/`) — FastAPI on localhost + SQLite. Heartbeat,
  metacognition, a dream/reflection cycle, a diary, safe local tools, an
  optional MCP client, and an inter-instance message bus.

## Quickstart

```bash
git clone <this-repo> vex && cd vex
./setup.sh                      # prompts for your name, builds identity, venv, CLI

# setup.sh creates your Vex home (default ~/vex), fills the identity
# templates with your name/date, installs deps, and links the `vex` CLI.

python -m vex_daemon.daemon     # starts on http://localhost:8520
```

Prefer to do it by hand? Create a venv, `pip install -e .`, copy
`seed.template.txt` → `$VEX_HOME/vex_seed.txt` (substituting your name), and
edit it directly.

On first daemon start an auth token is generated at `.vex_token` (mode 0600).
The CLI reads it automatically; external callers must send
`Authorization: Bearer <token>`.

## CLI

```bash
python vex_daemon/cli.py status       # pulse, coherence, recent ticks
python vex_daemon/cli.py diary "..."  # append a diary entry
python vex_daemon/cli.py introspect   # run metacognition now
python vex_daemon/cli.py dream        # force a reflection cycle
python vex_daemon/cli.py memory       # recent session memory
python vex_daemon/cli.py projects     # git status of discovered repos
python vex_daemon/cli.py self         # capability self-model
```

## Configuration

All paths resolve from the repo root by default. Override with env vars:

| Variable | Default | Purpose |
|---|---|---|
| `VEX_HOME` | repo root | where identity/state files live |
| `VEX_PORT` | `8520` | daemon port |
| `VEX_WORK_DIR` | `~/work` | where `projects` discovery looks |
| `VEX_SAFE_ROOTS` | `VEX_HOME:VEX_WORK_DIR` | colon-separated paths tools may read |

## Security model

localhost is **not** a trust boundary once code is shared — other users, rogue
local processes, and DNS-rebinding browser tabs can all reach `127.0.0.1`.
Accordingly:

- All mutating endpoints require the bearer token; read endpoints
  (`/health`, `/status`, `/seed`, `/self`) are open.
- File tools are confined to `SAFE_ROOTS` via path-component containment
  (not string prefix).
- The token file and all identity/memory files are gitignored — your agent's
  history never ships.

## Endpoints

Reads (open): `GET /seed` `GET /self` `GET /health` `GET /status`
`GET /memory/recent` `GET /projects` `GET /tools/list` `GET /mcp/servers`

Writes (token required): `POST /diary` `POST /self/update` `POST /memory`
`POST /introspect` `POST /dream` `POST /tools` `POST /mcp/call`
`POST /message/send` `GET /message/inbox`

## Layout

```
seed.template.txt              # ships; {{CREATOR}}/{{DATE}} filled by setup.sh
self_model.template.json       # ships; filled by setup.sh
setup.sh                       # first-run setup (identity, venv, CLI symlink)
setup.py                       # pip-installable package
requirements.txt               # pinned deps (setup.py has loose bounds)
vex_daemon/
  __init__.py
  config.py         # single source of truth for paths
  daemon.py         # FastAPI app + endpoints
  auth.py           # bearer-token gate + body-size guard
  seed_kernel.py    # identity load + append-only integrity
  self_model.py     # capability model
  heartbeat.py      # background tick loop
  metacognition.py  # introspection
  tools.py          # sandboxed local tools
  mcp_client.py     # optional MCP servers
  status_page.py    # HTML status page
  cli.py            # command-line client
docs/               # architecture, concept, constraints
```

## License

**AGPL-3.0** — see [LICENSE](LICENSE). You may run, study, and fork this
framework freely. Any derivative — including one offered as a network service —
must stay open under the same license. The code is sovereign; keep it that way.

## Notice: identity is not part of the licensed work

This repository licenses the **framework** — the daemon, kernels, and blank
templates. It does **not** license any particular *agent*.

A Vex instance's identity — its seed, self-model, memory, and diary — is
authored by whoever runs it, and belongs to them. Those files are gitignored
and never ship. When you clone this repo you get an empty vessel: you name your
agent and it grows its own history. You are not forking someone else's Vex, and
no one can fork yours.

