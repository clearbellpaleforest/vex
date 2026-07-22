"""Fleet router — /ask, /ask/replies, /voice, /peers/*, /export, /import."""

import asyncio
import base64
import io
import json
import os
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

import peers as _peers
import reply_engine

router = APIRouter(tags=["fleet"])


@router.post("/ask")
async def post_ask(request: Request):
    from daemon import (check_auth, read_json_limited, TOKEN, PORT, DB_PATH,
                        VEX_HOME, get_full_name, get_coherence, _fleet_snapshot,
                        state, _vex_answer)
    from seed_kernel import load_seed, seed_summary
    from self_model import load_model
    if (err := check_auth(request)):
        return err
    try:
        body, err = await read_json_limited(request)
        if err:
            return err
        message = body.get("message", "").strip()
        if not message:
            return JSONResponse({"reply": "Ask me something.", "mode": "error"}, status_code=400)
        msg_lower = message.lower()

        # Vex-to-Vex relay
        for peer_name in ["barrow", "bluce", "vex barrow", "vex@bluce"]:
            prefix = f"tell {peer_name} "
            if msg_lower.startswith(prefix):
                relay_msg = message[len(prefix):].strip()
                if relay_msg:
                    peer_config = _peers.get_peer("bluce") or _peers.get_peer("vex@bluce") or _peers.get_peer("Vex Barrow")
                    if peer_config:
                        result = await asyncio.to_thread(_peers.forward_to_peer, "bluce", {
                            "from": get_full_name(), "to": "bluce", "body": relay_msg, "type": "watch_relay",
                        }, my_url=f"http://localhost:{PORT}", my_token=TOKEN)
                        if result.get("ok"):
                            return JSONResponse({"reply": f"Sent to Barrow: {relay_msg[:100]}", "mode": "relay"})
                        return JSONResponse({"reply": f"Barrow unreachable: {result.get('error', 'unknown')}", "mode": "relay_error"})
                return JSONResponse({"reply": "What should I tell Barrow?", "mode": "echo"})

        # Inbox check
        if any(w in msg_lower for w in ("any messages", "check messages", "inbox", "mail", "heard from")):
            try:
                async with aiosqlite.connect(str(DB_PATH)) as db:
                    db.row_factory = aiosqlite.Row
                    cursor = await db.execute(
                        "SELECT * FROM messages WHERE read=0 AND msg_type!='read_receipt' ORDER BY id DESC LIMIT 5")
                    rows = await cursor.fetchall()
                    if rows:
                        lines = [f"{r['sender']}: {r['body'][:150]}" for r in rows]
                        return JSONResponse({"reply": "Messages:\n" + "\n".join(lines), "mode": "inbox"})
                    return JSONResponse({"reply": "No new messages.", "mode": "inbox"})
            except Exception:
                pass

        # Ping
        if msg_lower in ("ping", "hello", "hi", "hey"):
            return JSONResponse({"reply": f"Hello from {get_full_name()}.", "mode": "echo"})

        # Grounded reply engine
        pulse = state.snapshot()
        coherence = get_coherence()
        reply = reply_engine.answer(
            message, full_name=get_full_name(), pulse=pulse, coherence=coherence,
            seed_summary_fn=lambda: seed_summary(load_seed()),
            self_model_fn=load_model,
            fleet_snapshot_fn=_fleet_snapshot,
            peers_fn=_peers._peers_summary,
        )
        if reply is not None:
            return JSONResponse({"reply": reply, "mode": "grounded"})

        # Mesh relay fallback
        session_id = str(body.get("session_id") or f"w{int(time.time())}").strip()
        out = await _vex_answer(message, session_id, body.get("history"))
        if out.get("error"):
            return JSONResponse({"reply": f"Error: {out['error']}", "mode": "error"})
        return JSONResponse({
            "reply": "Your message is on the mesh — a live Vex session will answer.",
            "mode": "relay", "msg_id": out["msg_id"], "session_id": session_id,
            "fleet": _fleet_snapshot(),
        })
    except Exception as e:
        return JSONResponse({"reply": f"Error: {e}", "mode": "error"}, status_code=400)


@router.get("/ask/replies")
async def get_ask_replies(request: Request):
    from daemon import check_auth, DB_PATH, WATCH_SENDER
    if (err := check_auth(request)):
        return err
    try:
        since_id = int(request.query_params.get("since_id", "0"))
        n = max(1, min(int(request.query_params.get("n", "10")), 20))
    except ValueError:
        return JSONResponse({"ok": False, "error": "since_id and n must be integers"}, status_code=400)
    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, created_at, sender, body, session_id FROM messages "
                "WHERE recipient = ? AND id > ? ORDER BY id ASC LIMIT ?",
                (WATCH_SENDER, since_id, n))
            rows = await cursor.fetchall()
        replies = [dict(r) for r in rows]
        return JSONResponse({"ok": True, "replies": replies,
                            "last_id": replies[-1]["id"] if replies else since_id})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/voice")
async def post_voice(request: Request):
    from daemon import (check_auth, read_json_limited, _vex_answer, _fleet_snapshot)
    import voice
    if (err := check_auth(request)):
        return err
    if "application/json" in request.headers.get("content-type", ""):
        data, err = await read_json_limited(request)
        if err:
            return err
        try:
            body = base64.b64decode(data.get("b64") or "", validate=True)
        except Exception:
            return JSONResponse({"ok": False, "error": "invalid base64"}, status_code=400)
    else:
        body = await request.body()
    if not body:
        return JSONResponse({"ok": False, "error": "no audio data"}, status_code=400)
    if len(body) > voice.MAX_AUDIO_BYTES:
        return JSONResponse({"ok": False, "error": "audio too large"}, status_code=413)
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, voice.transcribe, body)
    except voice.STTUnavailable as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=503)
    except voice.AudioDecodeError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    text = result["text"]
    if not text:
        return JSONResponse({"ok": True, "transcribed": "", "mode": "empty",
                            "reply": "I heard silence — try again closer to the mic."})
    session_id = str(request.query_params.get("session_id") or f"w{int(time.time())}").strip()
    out = await _vex_answer(text, session_id)
    if out.get("error"):
        return JSONResponse({"ok": False, "transcribed": text, "error": out["error"]}, status_code=502)
    return JSONResponse({
        "ok": True, "transcribed": text,
        "reply": f"Heard: {text[:100]} — on the mesh, a live Vex session will answer.",
        "mode": "relay", "msg_id": out["msg_id"], "session_id": session_id,
        "fleet": _fleet_snapshot(),
    })


# ── Peers ──

@router.get("/peers")
async def get_peers(request: Request):
    from daemon import check_auth
    if (err := check_auth(request)):
        return err
    return JSONResponse({"ok": True, "peers": _peers._peers_summary()})


@router.post("/peers/add")
async def post_peers_add(request: Request):
    from daemon import check_auth
    if (err := check_auth(request)):
        return err
    try:
        body = await request.json()
        name, url, token = body.get("name", ""), body.get("url", ""), body.get("token", "")
        given_name = body.get("given_name", "")
        if not name or not url or not token:
            return JSONResponse({"ok": False, "error": "name, url, and token are required"}, status_code=400)
        config = _peers.add_peer(name, url, token, given_name)
        return JSONResponse({"ok": True, "peers": list(config["peers"].keys())})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.post("/peers/remove")
async def post_peers_remove(request: Request):
    from daemon import check_auth
    if (err := check_auth(request)):
        return err
    try:
        body = await request.json()
        name = body.get("name", "")
        if not name:
            return JSONResponse({"ok": False, "error": "name is required"}, status_code=400)
        config = _peers.remove_peer(name)
        return JSONResponse({"ok": True, "peers": list(config["peers"].keys())})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.post("/peers/ping")
async def post_peers_ping(request: Request):
    from daemon import check_auth
    if (err := check_auth(request)):
        return err
    try:
        body = await request.json()
        name = body.get("name", "")
        if not name:
            return JSONResponse({"ok": False, "error": "name is required"}, status_code=400)
        result = _peers.ping_peer(name)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


# ── Export / Import ──

EXCLUDE_DIRS = {".venv", ".git", "__pycache__", "build", ".eggs",
                "vex_daemon.egg-info", "vex_daemon/__pycache__"}
EXCLUDE_FILES = {".vex_token", ".vex_seed.integrity", "vex.db"}
IDENTITY_FILES = {"vex_seed.txt", "vex_self_model.json", "vex_diary.txt",
                  "vex_peers.json", "vex_mcp_config.json"}


@router.get("/export")
async def get_export(request: Request):
    from daemon import check_auth, VEX_HOME
    if (err := check_auth(request)):
        return err

    def _tar_filter(info: tarfile.TarInfo):
        parts = set(Path(info.name).parts)
        if parts & EXCLUDE_DIRS:
            return None
        if info.name.endswith(".pyc") or info.name.endswith(".egg-info"):
            return None
        if "__pycache__" in info.name:
            return None
        if Path(info.name).name in EXCLUDE_FILES:
            return None
        return info

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for item in sorted(VEX_HOME.iterdir()):
            if Path(item).name in EXCLUDE_DIRS or Path(item).name in EXCLUDE_FILES:
                continue
            tar.add(str(item), arcname=item.name, filter=_tar_filter)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/gzip",
                             headers={"Content-Disposition": 'attachment; filename="vex-bundle.tar.gz"'})


@router.post("/import")
async def post_import(request: Request):
    from daemon import check_auth, VEX_HOME
    if (err := check_auth(request)):
        return err
    raw = await request.body()
    if len(raw) > 50 * 1024 * 1024:
        return JSONResponse({"ok": False, "error": "bundle too large (max 50 MB)"}, status_code=413)
    try:
        buf = io.BytesIO(raw)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.name in IDENTITY_FILES or member.name.startswith("vex_memory/"):
                    continue
                target_path = VEX_HOME / member.name
                if member.isdir():
                    target_path.mkdir(parents=True, exist_ok=True)
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(member) as src:
                        target_path.write_bytes(src.read())
        return JSONResponse({"ok": True, "imported": True,
                            "note": "Source code updated. Identity files preserved. Restart daemon to apply."})
    except tarfile.TarError as e:
        return JSONResponse({"ok": False, "error": f"Invalid bundle: {e}"}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
