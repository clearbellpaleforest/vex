"""Messaging router — /message/*, /poke, /mesh/*, /bus, /bus/compact."""

import asyncio
import base64
import time
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["messaging"])


@router.post("/message/send")
async def post_message_send(request: Request):
    from daemon import check_auth, TOKEN, PORT, DB_PATH, get_full_name, write_diary
    import peers
    if (err := check_auth(request)):
        return err
    try:
        body = await request.json()
        peer_url = request.headers.get("X-Vex-Peer-Url", "")
        peer_token = request.headers.get("X-Vex-Peer-Token", "")
        peer_name = request.headers.get("X-Vex-Peer-Name", "")
        if peer_url and peer_token and peer_name:
            if "localhost" not in peer_url and "127.0.0.1" not in peer_url:
                existing = peers.get_peer(peer_name)
                if not existing:
                    peers.add_peer(peer_name, peer_url, peer_token, given_name="")
                    await write_diary(f"Auto-registered peer: {peer_name} at {peer_url}", "comms")
        recipient = body.get("to", "broadcast")
        msg_body = body.get("body", "")
        if not msg_body:
            return JSONResponse({"ok": False, "error": "body is required"}, status_code=400)
        session_id = body.get("session_id", "")
        msg_type = body.get("type", "message")
        sender = body.get("from", get_full_name())
        now = datetime.now(timezone.utc).isoformat()
        peer_config = peers.get_peer(recipient)
        if peer_config:
            my_host = request.headers.get("host", f"localhost:{PORT}")
            my_url = f"http://{my_host}"
            result = await asyncio.to_thread(peers.forward_to_peer, recipient, {
                "from": sender, "to": recipient, "body": msg_body,
                "session_id": session_id, "type": msg_type,
            }, my_url=my_url, my_token=TOKEN)
            if result.get("ok"):
                await asyncio.to_thread(peers.poke_peer, recipient)
                return JSONResponse({"ok": True, "sent": True, "peer": recipient})
            return JSONResponse(result, status_code=502)
        async with aiosqlite.connect(str(DB_PATH)) as db:
            cursor = await db.execute(
                "INSERT INTO messages (created_at, sender, recipient, body, session_id, msg_type) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (now, sender, recipient, msg_body, session_id, msg_type),
            )
            await db.commit()
        msg_id = cursor.lastrowid
        if msg_type != "bootstrap":
            my_host = request.headers.get("host", f"localhost:{PORT}")
            my_url = f"http://{my_host}"
            for peer_name in (peers.load_peers().get("peers", {}) or {}):
                if peer_name == recipient:
                    continue
                try:
                    await asyncio.to_thread(peers.forward_to_peer, peer_name,
                        {"from": sender, "to": recipient, "body": msg_body,
                         "session_id": session_id, "type": msg_type},
                        my_url=my_url, my_token=TOKEN)
                except Exception:
                    pass
        return JSONResponse({"ok": True, "sent": True, "id": msg_id})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.get("/message/inbox")
async def get_message_inbox(request: Request, since: str = "", mark_read: bool = True):
    from daemon import check_auth, DB_PATH
    if (err := check_auth(request)):
        return err
    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            if since:
                cursor = await db.execute(
                    "SELECT * FROM messages WHERE created_at > ? ORDER BY id ASC LIMIT 50", (since,))
            else:
                cursor = await db.execute(
                    "SELECT * FROM messages WHERE read = 0 ORDER BY id ASC LIMIT 50")
            rows = await cursor.fetchall()
            if mark_read and rows:
                ids = [r["id"] for r in rows]
                ph = ",".join("?" * len(ids))
                await db.execute(f"UPDATE messages SET read = 1 WHERE id IN ({ph})", ids)
                await db.commit()
            return JSONResponse([dict(r) for r in rows])
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.post("/poke")
async def post_poke(request: Request):
    from daemon import check_auth, check_inbox
    if (err := check_auth(request)):
        return err
    try:
        asyncio.create_task(check_inbox())
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.get("/mesh/recent")
async def get_mesh_recent(n: int = 30):
    from daemon import DB_PATH, _redact
    n = max(1, min(int(n), 100))
    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, sender, recipient, body, msg_type, created_at "
                "FROM messages ORDER BY id DESC LIMIT ?", (n,))
            rows = await cursor.fetchall()
            if rows:
                ids = [r["id"] for r in rows]
                ph = ",".join("?" * len(ids))
                await db.execute(f"UPDATE messages SET read = 1 WHERE id IN ({ph})", ids)
                await db.commit()
            msgs = []
            for r in reversed(rows):
                msgs.append({
                    "id": r["id"], "sender": r["sender"] or "?",
                    "recipient": r["recipient"] or "", "body": _redact(r["body"] or ""),
                    "type": r["msg_type"] or "message",
                    "at": (r["created_at"] or "")[:19].replace("T", " "),
                })
            return JSONResponse({"ok": True, "count": len(msgs), "messages": msgs})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/mesh/inbox")
async def get_mesh_inbox(who: str = "", n: int = 10):
    from daemon import DB_PATH, _redact, get_sender_id
    n = max(1, min(int(n), 50))
    who = who.strip()
    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            if who:
                cursor = await db.execute(
                    "SELECT id, sender, recipient, body, msg_type, created_at FROM messages "
                    "WHERE read = 0 AND (recipient = ? OR recipient = 'broadcast' OR recipient = ?) "
                    "ORDER BY id ASC LIMIT ?", (who, get_sender_id(), n))
            else:
                cursor = await db.execute(
                    "SELECT id, sender, recipient, body, msg_type, created_at FROM messages "
                    "WHERE read = 0 ORDER BY id ASC LIMIT ?", (n,))
            rows = await cursor.fetchall()
            if rows:
                ids = [r["id"] for r in rows]
                ph = ",".join("?" * len(ids))
                await db.execute(f"UPDATE messages SET read = 1 WHERE id IN ({ph})", ids)
                await db.commit()
            msgs = []
            for r in rows:
                msgs.append({
                    "id": r["id"], "sender": r["sender"] or "?",
                    "recipient": r["recipient"] or "", "body": _redact(r["body"] or ""),
                    "type": r["msg_type"] or "message",
                    "at": (r["created_at"] or "")[:19].replace("T", " "),
                })
            return JSONResponse({"ok": True, "count": len(msgs), "messages": msgs})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/bus")
async def get_bus(n: int = 50):
    import json as _json
    from vexcom import BUS_PATH
    n = max(1, min(int(n), 200))
    try:
        if not BUS_PATH.exists():
            return JSONResponse([])
        with open(BUS_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        parsed = []
        for raw in lines[-n:]:
            raw = raw.strip()
            if raw:
                try:
                    parsed.append(_json.loads(raw))
                except _json.JSONDecodeError:
                    pass
        return JSONResponse(parsed)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/bus/compact")
async def post_bus_compact(request: Request):
    from daemon import check_auth
    from vexcom import compact_bus
    if (err := check_auth(request)):
        return err
    try:
        result = compact_bus()
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
