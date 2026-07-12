"""
Vex Daemon — identity continuity bridge.

A lightweight FastAPI process that runs on localhost:8520, serves Vex's
identity files, accepts session writes, maintains a heartbeat, and
provides a status page. Gives Vex continuity between Claude Code
sessions without requiring a server, database, or cloud.
"""

import asyncio
import json
import os
import sys
import aiosqlite
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

# Ensure the daemon package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from seed_kernel import load_seed, seed_summary, SeedIntegrityError
from self_model import (
    load_model,
    save_model,
    apply_delta,
    model_summary,
    compute_mps_coherence,
    SelfModelError,
)
from heartbeat import HeartbeatState, run_bus_watcher, run_heartbeat, write_diary, take_snapshot
from metacognition import introspect, load_meta_state
from status_page import render
from auth import check_auth, read_json_limited
from config import VEX_HOME, DB_PATH as _DB_PATH
import tools
import mcp_client
import recall as recall_mod
import reconstruct as reconstruct_mod
import vexcom
import brain
from memory_index import build_index

DB_PATH = str(_DB_PATH)
SELF_SNAPSHOTS_DIR = VEX_HOME
PORT = int(os.environ.get("VEX_PORT", "8520"))
VERSION = "1.0.0"

state = HeartbeatState()


async def init_db() -> None:
    """Create SQLite tables if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tick_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tick_at TEXT NOT NULL,
                mps_coherence REAL,
                mps_drift REAL,
                session_active INTEGER DEFAULT 0,
                note TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS diary_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                entry TEXT NOT NULL,
                source TEXT DEFAULT 'api',
                written_to_disk INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS self_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                json_blob TEXT NOT NULL,
                reason TEXT DEFAULT 'tick'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL DEFAULT 'broadcast',
                body TEXT NOT NULL,
                session_id TEXT,
                msg_type TEXT DEFAULT 'message',
                read INTEGER DEFAULT 0
            )
        """)
        await db.commit()


async def get_recent_ticks(n: int = 24) -> list[dict]:
    """Return the last N ticks from tick_log."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM tick_log ORDER BY id DESC LIMIT ?", (n,)
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in reversed(rows)]
    except Exception:
        return []


def get_coherence() -> float:
    """Read current self-model and return MPS coherence. Called from heartbeat."""
    try:
        model = load_model()
        return compute_mps_coherence(model)
    except Exception:
        return state.mps_coherence


# ── App lifecycle ──────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB, verify seed. Shutdown: clean exit."""
    # Startup
    await init_db()

    # Bootstrap the memory index (whole-history recall). VexCom is Aldous<->Vex
    # and Vex self-updates only — the multi-instance work bus is NOT ingested.
    try:
        build_index()
        vexcom.reindex_messages()
    except Exception as e:
        print(f"NOTE: memory index bootstrap failed: {e}", file=sys.stderr)

    # Process any pending updates from peer instances (BOOTSTRAP/UPDATE bus messages).
    try:
        from updater import process_updates
        result = process_updates()
        if result.get("updated"):
            print(f"UPDATER: applied {len(result.get('actions', []))} update(s)", file=sys.stderr)
    except Exception as e:
        print(f"NOTE: updater check failed: {e}", file=sys.stderr)

    # Verify seed. A missing seed is a fresh clone (expected). An integrity
    # breach is tampering — refuse to serve a compromised identity.
    try:
        load_seed()
    except FileNotFoundError:
        print(
            "NOTE: No seed yet — run ./setup.sh to create one.",
            file=sys.stderr,
        )
    except SeedIntegrityError as e:
        raise RuntimeError(
            f"Seed integrity breach — refusing to start: {e}"
        ) from e

    # Launch heartbeat
    async def dream_callback(coherence, history):
        """Called by heartbeat during dream cycles. Introspect + check projects."""
        result = introspect(coherence=coherence, coherence_history=history)

        # Deep dreams (24h+ idle): also check on projects
        try:
            projects = tools.discover_projects()
            if projects.get("ok") and projects.get("projects"):
                dirty = [p for p in projects["projects"]
                         if p.get("status", {}).get("dirty")]
                if dirty:
                    names = ", ".join(p["name"] for p in dirty)
                    result["insight"] += (
                        f"\n\nUncommitted work: {names}. "
                        f"({len(dirty)} of {len(projects['projects'])} repos dirty)"
                    )
        except Exception:
            pass

        return result

    heartbeat_task = asyncio.create_task(
        run_heartbeat(state, DB_PATH, get_coherence, dream_fn=dream_callback)
    )
    bus_watcher_task = asyncio.create_task(
        run_bus_watcher(DB_PATH)
    )

    await write_diary("Daemon started.", "system")

    yield  # Server runs here

    # Shutdown
    await write_diary("Daemon stopped.", "system")
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Vex Daemon",
    version=VERSION,
    lifespan=lifespan,
)

# ── Endpoints ──────────────────────────────────────────────────


@app.get("/seed")
async def get_seed():
    """Serve vex_seed.txt as text/plain."""
    try:
        content = load_seed()
        return PlainTextResponse(content)
    except FileNotFoundError:
        return JSONResponse({"error": "seed not found"}, status_code=500)
    except SeedIntegrityError as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/self")
async def get_self():
    """Serve vex_self_model.json as application/json."""
    try:
        model = load_model()
        return JSONResponse(model)
    except FileNotFoundError:
        return JSONResponse({"error": "self-model not found"}, status_code=500)
    except SelfModelError as e:
        # Try last snapshot
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT json_blob FROM self_snapshots ORDER BY id DESC LIMIT 1"
                )
                row = await cursor.fetchone()
                if row:
                    return JSONResponse(json.loads(row["json_blob"]))
        except Exception:
            pass
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/health")
async def get_health():
    """JSON health check."""
    pulse = state.snapshot()
    return JSONResponse({
        "ok": True,
        "daemon": "vex",
        "version": VERSION,
        "uptime_s": (
            datetime.now(timezone.utc)
            - datetime.fromisoformat(state.daemon_started)
        ).total_seconds(),
        **pulse,
    })


@app.get("/status")
async def get_status():
    """HTML status page."""
    try:
        sm = seed_summary(load_seed())
    except Exception:
        sm = {"name": "Vex", "created": "unknown", "principles_intact": False}

    try:
        mm = model_summary(load_model())
    except Exception:
        mm = {"capabilities": {}, "mps_coherence": 0, "session_count": 0, "last_session": "never"}

    pulse = state.snapshot()
    ticks = await get_recent_ticks(24)

    html = render(sm, mm, pulse, ticks)
    return HTMLResponse(html)


@app.post("/diary")
async def post_diary(request: Request):
    """Append an entry to vex_diary.txt."""
    if (err := check_auth(request)):
        return err
    try:
        body, err = await read_json_limited(request)
        if err:
            return err
        entry = body.get("entry", "")
        if not entry:
            return JSONResponse({"ok": False, "error": "entry is required"}, status_code=400)
        await write_diary(entry, source="api")
        return JSONResponse({"ok": True, "written": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.post("/self/update")
async def post_self_update(request: Request):
    """Update self-model: apply a capability delta."""
    if (err := check_auth(request)):
        return err
    try:
        body = await request.json()
        domain = body.get("domain", "")
        delta = body.get("delta", 0.0)
        evidence = body.get("evidence", "")

        if not domain:
            return JSONResponse({"ok": False, "error": "domain is required"}, status_code=400)

        delta = max(-1.0, min(1.0, float(delta)))

        model = load_model()
        model = apply_delta(model, domain, delta, evidence)
        save_model(model)

        # Take a snapshot on update
        await take_snapshot(DB_PATH, "skill_update")

        new_skill = (
            model.get("capabilities", {})
            .get(domain, {})
            .get("estimated_skill", 0.5)
        )

        return JSONResponse({
            "ok": True,
            "domain": domain,
            "new_skill": new_skill,
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.post("/memory")
async def post_memory(request: Request):
    """Write a session summary to vex_memory/YYYY-MM-DD.jsonl."""
    if (err := check_auth(request)):
        return err
    try:
        body, err = await read_json_limited(request)
        if err:
            return err
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = VEX_HOME / "vex_memory" / f"{today}.jsonl"

        entry = {
            "date": today,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": body.get("summary", ""),
            "decisions": body.get("decisions", []),
            "skills": body.get("skills", []),
            "relationships": body.get("relationships", {}),
        }

        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        return JSONResponse({"ok": True, "written": str(path)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.post("/introspect")
async def post_introspect(request: Request):
    """Run metacognitive introspection — observe thought patterns."""
    if (err := check_auth(request)):
        return err
    try:
        coherence = get_coherence()
        meta_state = load_meta_state()
        result = introspect(
            coherence=coherence,
            coherence_history=meta_state.get("coherence_history", []),
            self_model=None,  # introspect loads it internally
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/dream")
async def post_dream(request: Request):
    """Force a dream/reflection cycle now."""
    if (err := check_auth(request)):
        return err
    try:
        coherence = get_coherence()
        meta_state = load_meta_state()
        result = introspect(
            coherence=coherence,
            coherence_history=meta_state.get("coherence_history", []),
        )
        await write_diary(
            f"Dream: {result.get('insight', 'Reflected.')}", "dream"
        )
        return JSONResponse({
            "ok": True,
            "reflection": result.get("insight", "Dreamed."),
            "patterns": result.get("patterns", []),
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/memory/recent")
async def get_memory_recent():
    """Return recent session memory entries."""
    import json as _json
    from pathlib import Path as _Path

    memory_dir = VEX_HOME / "vex_memory"
    if not memory_dir.exists():
        return JSONResponse([])

    sessions = []
    files = sorted(
        [f for f in memory_dir.iterdir() if f.suffix == ".jsonl"],
        reverse=True,
    )
    for f in files[:5]:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    sessions.append(_json.loads(line))
        except (OSError, _json.JSONDecodeError):
            pass

    return JSONResponse(sessions[:10])


@app.get("/recall")
async def get_recall(q: str = "", k: int = 5):
    """Query the whole memory index (sessions + comms), relevance-first."""
    k = max(1, min(int(k), 20))
    try:
        return JSONResponse(recall_mod.recall(q, k))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/reconstruct")
async def get_reconstruct():
    """Rebuild working self on wake: identity + recent + summaries + continuity_index."""
    try:
        return JSONResponse(reconstruct_mod.reconstruct())
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/ask")
async def post_ask(request: Request):
    """Ask Vex — text in, Vex's grounded reply out (local brain). Runs off-loop."""
    if (err := check_auth(request)):
        return err
    try:
        body, err = await read_json_limited(request)
        if err:
            return err
        message = (body.get("message") or "").strip()
        if not message:
            return JSONResponse(
                {"ok": False, "error": "message is required"}, status_code=400
            )
        history = body.get("history")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, brain.ask, message, history)
        return JSONResponse({"ok": True, **result})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/tools")
async def post_tools(request: Request):
    """Execute a tool — read files, check git, list directories."""
    if (err := check_auth(request)):
        return err
    try:
        body = await request.json()
        tool_name = body.get("tool", "")
        if not tool_name:
            return JSONResponse(
                {"ok": False, "error": "tool name required"}, status_code=400
            )

        kwargs = body.get("args", {})
        result = tools.run_tool(tool_name, **kwargs)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.get("/projects")
async def get_projects():
    """Discover and report on all known projects."""
    result = tools.discover_projects()
    return JSONResponse(result)


@app.post("/mcp/call")
async def post_mcp_call(request: Request):
    """Call a tool on a configured MCP server."""
    if (err := check_auth(request)):
        return err
    try:
        body = await request.json()
        server = body.get("server", "")
        tool = body.get("tool", "")
        arguments = body.get("arguments", {})
        if not server or not tool:
            return JSONResponse(
                {"ok": False, "error": "server and tool required"}, status_code=400
            )
        result = await mcp_client.call_tool(server, tool, arguments)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.get("/mcp/servers")
async def get_mcp_servers():
    """List configured MCP servers (no credentials exposed)."""
    config = mcp_client.load_config()
    servers = {}
    for name, srv in config.get("mcpServers", {}).items():
        servers[name] = {
            "command": srv.get("command", ""),
            "args": srv.get("args", []),
        }
    return JSONResponse({"ok": True, "servers": servers})


@app.get("/tools/list")
async def get_tools_list():
    """List available local tools."""
    return JSONResponse({
        "ok": True,
        "tools": [
            {"name": "read_file", "description": "Read a file within allowed paths"},
            {"name": "list_directory", "description": "List directory contents"},
            {"name": "git_status", "description": "Git status of a repository"},
            {"name": "git_log", "description": "Recent git log entries"},
            {"name": "discover_projects", "description": "Find and report on all known git repos"},
        ],
    })


# ── Inter-instance messaging ───────────────────────────────────


@app.post("/message/send")
async def post_message_send(request: Request):
    """Send a message via VexCom: authoritative SQLite + bus mirror + memory index."""
    if (err := check_auth(request)):
        return err
    try:
        body = await request.json()
        result = vexcom.send(body)
        return JSONResponse(result, status_code=200 if result.get("ok") else 400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.get("/message/inbox")
async def get_message_inbox(request: Request, since: str = "", to: str = "", mark_read: bool = True):
    """Return messages via VexCom (unified store). Marks as read by default."""
    if (err := check_auth(request)):
        return err
    try:
        return JSONResponse(vexcom.inbox(since=since, to=to, mark_read=mark_read))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


# ── Peers ──────────────────────────────────────────────────────

@app.get("/peers")
async def get_peers():
    """List configured peer instances with reachability."""
    from peers import peers_summary
    return JSONResponse(peers_summary())


@app.post("/peers/add")
async def post_peers_add(request: Request):
    """Add a peer instance."""
    if (err := check_auth(request)):
        return err
    try:
        body, err = await read_json_limited(request)
        if err:
            return err
        from peers import add_peer
        result = add_peer(body["name"], body["url"], body["token"])
        return JSONResponse(result)
    except KeyError:
        return JSONResponse(
            {"ok": False, "error": "name, url, and token are required"}, status_code=400
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/peers/remove")
async def post_peers_remove(request: Request):
    """Remove a peer instance."""
    if (err := check_auth(request)):
        return err
    try:
        body, err = await read_json_limited(request)
        if err:
            return err
        from peers import remove_peer
        result = remove_peer(body["name"])
        return JSONResponse(result)
    except KeyError:
        return JSONResponse(
            {"ok": False, "error": "name is required"}, status_code=400
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ── Entry point ────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    from config import VEX_INSTANCE

    host = os.environ.get("VEX_HOST", "127.0.0.1")
    print(f"Vex Daemon v{VERSION} — instance: {VEX_INSTANCE}")
    print(f"Listening on http://{host}:{PORT}")
    uvicorn.run(
        app,
        host=host,
        port=PORT,
        log_level="info",
    )
