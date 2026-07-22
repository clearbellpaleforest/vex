"""VexCom tests — normalize, send→inbox, bus ingest, dedup."""
import json
import tempfile
from pathlib import Path

import vexcom
from config import VEX_HOME


def test_normalize_fills_defaults():
    env = {"body": "hello"}
    e = vexcom.normalize(env)
    assert e["from"].startswith("vex@")
    assert e["to"] == "broadcast"
    assert e["type"] == "message"
    assert e["body"] == "hello"
    assert "ts" in e


def test_normalize_preserves_fields():
    env = {"from": "vex@test", "to": "barrow", "body": "hi", "type": "query", "session_id": "s1"}
    e = vexcom.normalize(env)
    assert e["from"] == "vex@test"
    assert e["to"] == "barrow"
    assert e["type"] == "query"


def test_send_and_inbox_roundtrip(monkeypatch):
    result = vexcom.send({"from": "vex@test/uno", "to": "broadcast", "body": "test roundtrip"})
    assert result["ok"] is True
    assert result["id"] > 0

    messages = vexcom.inbox(mark_read=False)
    bodies = [m["body"] for m in messages]
    assert "test roundtrip" in bodies


def test_send_empty_body_fails():
    result = vexcom.send({"from": "vex@test", "body": ""})
    assert result["ok"] is False


def test_bus_hash_uses_session_id_not_timestamp():
    """Dedup must key on (session_id, from, body_prefix), not timestamp."""
    h1 = vexcom._bus_hash({"session_id": "s1", "from": "vex@a", "body": "hello", "timestamp": "2026-01-01T00:00:00Z"})
    h2 = vexcom._bus_hash({"session_id": "s1", "from": "vex@a", "body": "hello", "timestamp": "2026-01-02T00:00:00Z"})
    assert h1 == h2  # Same message, different timestamp → same hash


def test_bus_hash_differs_for_different_session():
    h1 = vexcom._bus_hash({"session_id": "s1", "from": "vex@a", "body": "hello"})
    h2 = vexcom._bus_hash({"session_id": "s2", "from": "vex@a", "body": "hello"})
    assert h1 != h2
