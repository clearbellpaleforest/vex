---
name: cross-repo-ops
description: Use when working across multiple repos — Fen, Vex, Town Records. Fleet overview, health checks, DB inspection, one-command shipping. Saves context-switching between repo directories.
---

# Cross-Repo Operations

Use Vex's ops toolkit to work across repos without leaving the conversation.

## Fleet Status

```bash
vex fleet
```
Shows all 5 tracked repos: branch, ahead/behind, dirty files, last commit.

## Health Pulse

```bash
vex pulse
```
Checks: Fen (:8000), Vex daemon (:8520), Town Records web (:8080), Qdrant (:6333).

## Database Inspector

```bash
vex db                          # auto-detect (checks fen, vex, ~/.fen)
vex db /path/to/custom.sqlite   # specific file
```
Shows: file size, all tables, row counts per table.

## Ship (stage + commit + push)

```bash
vex ship fen "fix: description of change"
vex ship vex "feat: new feature"
vex ship town-records "fix: deploy script update"
```
Stages all changes, commits with Co-Authored-By trailer, pushes to master.

Also available via API at `http://localhost:8520/ops/`:
- `GET /ops/fleet`
- `GET /ops/pulse`
- `GET /ops/db?path=...`
- `POST /ops/ship` with `{"repo": "fen", "message": "..."}`

## Repos Tracked

| Key | Path |
|-----|------|
| `fen` | `/home/aldous/Desktop/fenemerge` |
| `vex` | `/home/aldous/Desktop/vex` |
| `town-records` | `/home/aldous/Desktop/work/town-records` |
| `town-records-pipeline` | `/home/aldous/Desktop/work/town-records-pipeline` |
| `town-records-pipeline-search` | `/home/aldous/Desktop/work/town-records-pipeline-search` |

## When to Use

- Starting a session: `vex fleet` to see what's been happening
- After making changes: `vex ship <repo> "message"` to commit and push
- Diagnosing issues: `vex pulse` to check service health
- Exploring data: `vex db` to inspect what's stored
