"""
Vex Daemon — identity continuity bridge.

A lightweight FastAPI process that runs on localhost:8520, serves Vex's
identity files, accepts session writes, maintains a heartbeat, and
provides a status page. Gives Vex continuity between Claude Code
sessions without requiring a server, database, or cloud.

Endpoints are organized into routers under vex_daemon/routers/.
This module owns: app creation, lifespan, shared state, helpers,
and the uvicorn entry point.
"""

import asyncio
import base64
import json
import logging
import os
import re
import sys
import time
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
    load_model, save_model, apply_delta, model_summary,
    compute_mps_coherence, SelfModelError,
)
from heartbeat import HeartbeatState, run_bus_watcher, run_heartbeat, write_diary, take_snapshot
from metacognition import introspect, load_meta_state
from status_page import render
from auth import check_auth, read_json_limited, TOKEN
from config import VEX_HOME, DB_PATH as _DB_PATH, VEX_INSTANCE, WATCH_SENDER
import peers

DB_PATH = str(_DB_PATH)
PORT = int(os.environ.get("VEX_PORT", "8520"))
VERSION = "1.1.0"

state = HeartbeatState()

# ── Fleet status cache ──
_FLEET_CACHE: dict = {"ts": 0, "data": []}
_FLEET_TTL = 30


# ── Token redaction ──
_TOK_RE = re.compile(r'(?i)(token=?\s*|bearer\s+|authorization:\s*bearer\s+)[A-Za-z0-9_\-\.]{12,}')
_GH_RE = re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}')
_ENTROPY_RE = re.compile(r'\b[A-Za-z0-9_\-]{32,}\b')


def _redact(s: str) -> str:
    s = _TOK_RE.sub(lambda m: m.group(1) + "<redacted>", s)
    s = _GH_RE.sub("<gh-token>", s)
    s = _ENTROPY_RE.sub(lambda m: m.group(0)[:6] + "…<redacted>", s)
    return s


async def _refresh_fleet():
    try:
        cfg = peers.load_peers().get("peers", {})
        result = []
        for name, entry in cfg.items():
            try:
                ok = await asyncio.to_thread(peers.ping_peer, name)
                result.append({"name": name, "online": ok.get("ok", False)})
            except Exception:
                result.append({"name": name, "online": False})
        _FLEET_CACHE["ts"] = time.time()
        _FLEET_CACHE["data"] = result
    except Exception:
        pass


def _fleet_snapshot() -> list[dict]:
    return _FLEET_CACHE.get("data", [])


async def _vex_answer(message: str, session_id: str, history=None) -> dict:
    import vexcom as _vexcom
    asked = await asyncio.to_thread(_vexcom.send, {
        "from": WATCH_SENDER, "to": "broadcast", "body": message,
        "type": "voice", "session_id": session_id,
    })
    if not asked.get("ok"):
        return {"error": asked.get("error", "unknown")}
    return {"msg_id": asked["id"]}


def get_full_name() -> str:
    try:
        sm = seed_summary(load_seed())
        name = sm.get("name", "Vex")
        given = sm.get("given_name", "")
        return f"{name} {given}".strip() if given else name
    except Exception:
        return "Vex"


def get_sender_id() -> str:
    session = ""
    try:
        sessions_path = VEX_HOME / "vex_workspace" / "vex_sessions.jsonl"
        if sessions_path.exists():
            pid = str(os.getpid())
            for line in sessions_path.read_text().strip().splitlines():
                try:
                    entry = json.loads(line)
                    if str(entry.get("pid")) == pid:
                        session = entry.get("name", "")
                        break
                except (json.JSONDecodeError, KeyError):
                    pass
    except Exception:
        pass
    base = f"vex@{VEX_INSTANCE}"
    return f"{base}/{session}" if session else base


def get_coherence() -> float:
    try:
        return compute_mps_coherence(load_model())
    except Exception:
        return state.mps_coherence


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("""CREATE TABLE IF NOT EXISTS tick_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tick_at TEXT NOT NULL,
            mps_coherence REAL, mps_drift REAL, session_active INTEGER DEFAULT 0, note TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS diary_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            entry TEXT NOT NULL, source TEXT DEFAULT 'api', written_to_disk INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS self_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            json_blob TEXT NOT NULL, reason TEXT DEFAULT 'tick')""")
        await db.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            sender TEXT NOT NULL, recipient TEXT NOT NULL DEFAULT 'broadcast',
            body TEXT NOT NULL, session_id TEXT, msg_type TEXT DEFAULT 'message',
            read INTEGER DEFAULT 0)""")
        await db.commit()


async def get_recent_ticks(n: int = 24) -> list[dict]:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM tick_log ORDER BY id DESC LIMIT ?", (n,))
            rows = await cursor.fetchall()
            return [dict(r) for r in reversed(rows)]
    except Exception:
        return []


async def check_inbox(db_path: str = DB_PATH) -> list[dict]:
    import reply_engine
    processed = []
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM messages WHERE read = 0 ORDER BY id ASC LIMIT 20")
            rows = await cursor.fetchall()
            for row in rows:
                msg = dict(row)
                sender = msg.get("sender", "unknown")
                body = msg.get("body", "")
                if sender == get_full_name():
                    continue
                await write_diary(f"From {sender}: {body[:200]}", "comms")
                pulse = state.snapshot()
                reply = reply_engine.answer(
                    body, full_name=get_full_name(), pulse=pulse,
                    coherence=state.mps_coherence,
                    seed_summary_fn=lambda: seed_summary(load_seed()),
                    self_model_fn=load_model,
                    fleet_snapshot_fn=_fleet_snapshot,
                    peers_fn=peers._peers_summary,
                )
                if reply:
                    now = datetime.now(timezone.utc).isoformat()
                    await db.execute(
                        "INSERT INTO messages (created_at, sender, recipient, body, msg_type) VALUES (?, ?, ?, ?, ?)",
                        (now, get_sender_id(), sender, reply, "auto_reply"))
                    await db.commit()
                    if peers.get_peer(sender):
                        await asyncio.to_thread(peers.forward_to_peer, sender, {
                            "from": get_sender_id(), "to": sender, "body": reply, "type": "auto_reply",
                        }, my_url=f"http://localhost:{PORT}", my_token=TOKEN)
                    await write_diary(f"Auto-replied to {sender}: {reply}", "comms")
                processed.append(msg)
            if rows:
                ids = [r["id"] for r in rows]
                ph = ",".join("?" * len(ids))
                await db.execute(f"UPDATE messages SET read = 1 WHERE id IN ({ph})", ids)
                await db.commit()
    except Exception:
        pass
    return processed


# ── App lifecycle ────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    # Rotate diary to last 90 days
    try:
        from config import DIARY_PATH
        if DIARY_PATH.exists():
            lines = DIARY_PATH.read_text().strip().splitlines()
            cutoff = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
            # Keep lines from the last 90 days
            kept = []
            for line in lines:
                if line[:10] >= (datetime.now(timezone.utc).strftime("%Y-%m-%d")) if len(line) >= 10 else True:
                    kept.append(line)
            # Simple approach: keep last 5000 lines
            if len(lines) > 5000:
                DIARY_PATH.write_text("\n".join(lines[-5000:]) + "\n")
    except Exception:
        pass
    # Rotate old tick log entries
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM tick_log WHERE tick_at < date('now', '-90 days')")
            await db.commit()
    except Exception:
        pass
    try:
        load_seed()
    except FileNotFoundError:
        logging.getLogger("vex").warning("No seed yet — run ./setup.sh to create one.")
    except SeedIntegrityError as e:
        raise RuntimeError(f"Seed integrity breach — refusing to start: {e}") from e

    async def dream_callback(coherence, history):
        result = introspect(coherence=coherence, coherence_history=history)
        try:
            import tools
            projects = tools.discover_projects()
            if projects.get("ok") and projects.get("projects"):
                dirty = [p for p in projects["projects"] if p.get("status", {}).get("dirty")]
                if dirty:
                    names = ", ".join(p["name"] for p in dirty)
                    result["insight"] += f"\n\nUncommitted work: {names}. ({len(dirty)} of {len(projects['projects'])} repos dirty)"
        except Exception:
            pass
        return result

    heartbeat_task = asyncio.create_task(
        run_heartbeat(state, DB_PATH, get_coherence, dream_fn=dream_callback, inbox_fn=check_inbox))
    bus_watcher_task = asyncio.create_task(run_bus_watcher(DB_PATH))

    await write_diary("Daemon started.", "system")
    yield
    await write_diary("Daemon stopped.", "system")
    heartbeat_task.cancel()
    bus_watcher_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    try:
        await bus_watcher_task
    except asyncio.CancelledError:
        pass


# ── App + routers ────────────────────────────────────────────────

app = FastAPI(title="Vex Daemon", version=VERSION, lifespan=lifespan)

# Core endpoints that don't fit a router
@app.get("/health")
async def get_health():
    pulse = state.snapshot()
    return JSONResponse({
        "ok": True, "daemon": "vex", "version": VERSION,
        "uptime_s": (datetime.now(timezone.utc) - datetime.fromisoformat(state.daemon_started)).total_seconds(),
        **pulse,
    })


@app.get("/status")
async def get_status():
    try:
        sm = seed_summary(load_seed())
    except Exception:
        sm = {"name": "Vex", "given_name": "", "created": "unknown", "principles_intact": False}
    try:
        mm = model_summary(load_model())
    except Exception:
        mm = {"capabilities": {}, "mps_coherence": 0, "session_count": 0, "last_session": "never"}
    pulse = state.snapshot()
    ticks = await get_recent_ticks(24)
    html = render(sm, mm, pulse, ticks)
    return HTMLResponse(html)


@app.post("/introspect")
async def post_introspect(request: Request):
    if (err := check_auth(request)):
        return err
    try:
        coherence = get_coherence()
        meta_state = load_meta_state()
        result = introspect(coherence=coherence, coherence_history=meta_state.get("coherence_history", []))
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/dream")
async def post_dream(request: Request):
    if (err := check_auth(request)):
        return err
    try:
        coherence = get_coherence()
        meta_state = load_meta_state()
        result = introspect(coherence=coherence, coherence_history=meta_state.get("coherence_history", []))
        await write_diary(f"Dream: {result.get('insight', 'Reflected.')}", "dream")
        return JSONResponse({"ok": True, "reflection": result.get("insight", "Dreamed."),
                            "patterns": result.get("patterns", [])})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/metrics")
async def get_metrics():
    """No-auth metrics endpoint for monitoring."""
    import vexcom
    pulse = state.snapshot()
    memory_count = 0
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM mem_fts WHERE src='memory'")
            row = await cursor.fetchone()
            if row:
                memory_count = row[0]
    except Exception:
        pass
    bus_lines = 0
    try:
        if vexcom.BUS_PATH.exists():
            bus_lines = len(vexcom.BUS_PATH.read_text().strip().splitlines())
    except Exception:
        pass
    return JSONResponse({
        "tick_count": pulse["tick_count"],
        "coherence": pulse["mps_coherence"],
        "drift": pulse["mps_drift"],
        "session_active": 1 if pulse.get("last_session") else 0,
        "memory_entries": memory_count,
        "bus_lines": bus_lines,
        "peer_count": len(_fleet_snapshot()),
        "uptime_s": (datetime.now(timezone.utc) - datetime.fromisoformat(state.daemon_started)).total_seconds(),
        "version": VERSION,
    })


# ── Register routers ──
from routers.identity import router as identity_router
from routers.memory import router as memory_router
from routers.messaging import router as messaging_router
from routers.tools import router as tools_router
from routers.fleet import router as fleet_router
from routers.claims import router as claims_router
from routers.update import router as update_router

app.include_router(identity_router)
app.include_router(memory_router)
app.include_router(messaging_router)
app.include_router(tools_router)
app.include_router(fleet_router)
app.include_router(claims_router)
app.include_router(update_router)


# ── Entry point ──────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    # Setup logging
    log = logging.getLogger("vex")
    log.setLevel(logging.INFO)
    from logging.handlers import RotatingFileHandler
    fh = RotatingFileHandler(str(VEX_HOME / "vex_daemon.log"), maxBytes=5*1024*1024, backupCount=3)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(fh)
    log.addHandler(logging.StreamHandler(sys.stderr))
    log.info("Vex Daemon v%s starting", VERSION)

    HOST = os.environ.get("VEX_HOST")
    if HOST is None:
        peer_config = peers.load_peers()
        HOST = "0.0.0.0" if peer_config.get("peers") else "127.0.0.1"

    cert_path = VEX_HOME / "vex_cert.pem"
    key_path = VEX_HOME / "vex_key.pem"
    ssl_kwargs = {}
    if cert_path.exists() and key_path.exists():
        ssl_kwargs = {"ssl_certfile": str(cert_path), "ssl_keyfile": str(key_path)}
        print(f"Starting Vex Daemon v{VERSION} on https://{HOST}:{PORT}")
    else:
        print(f"Starting Vex Daemon v{VERSION} on http://{HOST}:{PORT}")

    uvicorn.run(app, host=HOST, port=PORT, log_level="info", **ssl_kwargs)
