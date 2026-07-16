"""POST /ask and GET /ask/replies — the watch's two endpoints.

Envelope contract (docs/design.md):
  watch -> mesh: sender=WATCH_SENDER, recipient=broadcast, msg_type=voice
  mesh -> watch: recipient=WATCH_SENDER, collected via /ask/replies?since_id=N
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

import daemon
import vexcom
from auth import TOKEN
from config import DB_PATH, WATCH_SENDER


@pytest.fixture()
def client():
    return TestClient(daemon.app)


def _auth():
    return {"Authorization": f"Bearer {TOKEN}"}


# ── auth boundary ──

def test_ask_without_token_is_401(client):
    assert client.post("/ask", json={"message": "ping"}).status_code == 401


def test_ask_with_wrong_token_is_401(client):
    r = client.post("/ask", json={"message": "ping"},
                    headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_replies_without_token_is_401(client):
    assert client.get("/ask/replies").status_code == 401


# ── input validation ──

def test_ask_empty_message_is_400(client):
    r = client.post("/ask", json={"message": "   "}, headers=_auth())
    assert r.status_code == 400


def test_ask_oversized_body_is_413(client):
    r = client.post("/ask", json={"message": "x" * (300 * 1024)}, headers=_auth())
    assert r.status_code == 413


def test_replies_non_integer_since_id_is_400(client):
    r = client.get("/ask/replies?since_id=abc", headers=_auth())
    assert r.status_code == 400


# ── keyword fast path ──

def test_ask_ping_answers_instantly(client):
    r = client.post("/ask", json={"message": "ping"}, headers=_auth())
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "echo"
    assert data["reply"].startswith("Hello from")


def test_ask_identity_is_grounded(client):
    r = client.post("/ask", json={"message": "who are you"}, headers=_auth())
    assert r.json()["mode"] == "grounded"


# ── default: relay onto the mesh ──

def test_ask_default_relays_as_watch_sender(client):
    r = client.post("/ask", json={"message": "what's the plan today",
                                  "session_id": "w123"}, headers=_auth())
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "relay"
    assert data["session_id"] == "w123"
    assert isinstance(data["msg_id"], int)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM messages WHERE id = ?",
                           (data["msg_id"],)).fetchone()
    finally:
        conn.close()
    assert row["sender"] == WATCH_SENDER
    assert row["recipient"] == "broadcast"
    assert row["msg_type"] == "voice"
    assert row["session_id"] == "w123"


def test_ask_generates_session_id_when_absent(client):
    r = client.post("/ask", json={"message": "free text, no session"}, headers=_auth())
    assert r.json()["session_id"].startswith("w")


# ── reply polling ──

def test_replies_returns_watch_addressed_only(client):
    sent = vexcom.send({"from": "vex@test/uno", "to": WATCH_SENDER,
                        "body": "reply for the wrist", "type": "message",
                        "session_id": "w123"})
    chatter = vexcom.send({"from": "vex@test/uno", "to": "broadcast",
                           "body": "mesh chatter", "type": "message"})
    r = client.get("/ask/replies?since_id=0", headers=_auth())
    assert r.status_code == 200
    data = r.json()
    ids = [m["id"] for m in data["replies"]]
    assert sent["id"] in ids
    assert chatter["id"] not in ids
    assert data["last_id"] >= sent["id"]

    r2 = client.get(f"/ask/replies?since_id={data['last_id']}", headers=_auth())
    assert r2.json()["replies"] == []


# ── the fleet is the brain — relay to mesh, no brain.py ──

def test_ask_default_relays_to_mesh_with_message_id(client):
    r = client.post("/ask", json={"message": "free text, fleet answers",
                                  "session_id": "wfleet1"}, headers=_auth())
    data = r.json()
    assert data["mode"] == "relay"
    assert "mesh" in data["reply"]
    assert isinstance(data["msg_id"], int)
    # ask row lands in messages
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM messages WHERE session_id = 'wfleet1' "
                           "ORDER BY id").fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["sender"] == WATCH_SENDER
    assert row["msg_type"] == "voice"


# ── no-auth feed must not leak tokens ──

def test_mesh_recent_redacts_tokens(client):
    vexcom.send({"from": "vex@test/uno", "to": "broadcast",
                 "body": "token=abc123def456ghi789 and ghp_abcdefghij1234567890KLMN and "
                         "uGm2NvgixLkuD4AzlOviV8Q1RhfzVhNc0vA1yaHj3do",
                 "type": "message"})
    r = client.get("/mesh/recent?n=10")
    assert r.status_code == 200
    text = r.text
    assert "abc123def456ghi789" not in text
    assert "ghp_abcdefghij1234567890KLMN" not in text
    assert "uGm2NvgixLkuD4AzlOviV8Q1RhfzVhNc0vA1yaHj3do" not in text
    assert "redacted" in text or "gh-token" in text
