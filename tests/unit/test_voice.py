"""POST /voice — audio boundary. STT is mocked; we test the seams.

Negative path first (docs/test-plan.md): no body 400, oversized 413,
undecodable 400, STT missing 503 — never a bare 500.
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

import daemon
import voice
from auth import TOKEN
from config import DB_PATH, WATCH_SENDER


@pytest.fixture()
def client():
    return TestClient(daemon.app)


def _auth():
    return {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/octet-stream"}


def test_voice_without_token_is_401(client):
    assert client.post("/voice", content=b"xx").status_code == 401


def test_voice_empty_body_is_400(client):
    assert client.post("/voice", content=b"", headers=_auth()).status_code == 400


def test_voice_oversized_is_413(client):
    blob = b"\0" * (voice.MAX_AUDIO_BYTES + 1)
    assert client.post("/voice", content=blob, headers=_auth()).status_code == 413


def test_voice_stt_unavailable_is_503(client, monkeypatch):
    def boom(_):
        raise voice.STTUnavailable("faster-whisper not installed")
    monkeypatch.setattr(voice, "transcribe", boom)
    r = client.post("/voice", content=b"opus-ish", headers=_auth())
    assert r.status_code == 503


def test_voice_undecodable_is_400(client, monkeypatch):
    def boom(_):
        raise voice.AudioDecodeError("audio decode/transcribe failed")
    monkeypatch.setattr(voice, "transcribe", boom)
    r = client.post("/voice", content=b"not audio", headers=_auth())
    assert r.status_code == 400


def test_voice_silence_does_not_relay(client, monkeypatch):
    monkeypatch.setattr(voice, "transcribe",
                        lambda _: {"text": "", "duration": 1.0, "language": "en"})
    r = client.post("/voice", content=b"quiet", headers=_auth())
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "empty"
    assert "msg_id" not in data


def test_voice_transcript_relays_as_watch_sender(client, monkeypatch):
    monkeypatch.setattr(voice, "transcribe",
                        lambda _: {"text": "hello vex from the wrist",
                                   "duration": 2.0, "language": "en"})
    r = client.post("/voice?session_id=w777", content=b"opus", headers=_auth())
    assert r.status_code == 200
    data = r.json()
    assert data["transcribed"] == "hello vex from the wrist"
    assert data["mode"] == "relay"
    assert data["session_id"] == "w777"

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM messages WHERE id = ?",
                           (data["msg_id"],)).fetchone()
    finally:
        conn.close()
    assert row["sender"] == WATCH_SENDER
    assert row["body"] == "hello vex from the wrist"
    assert row["msg_type"] == "voice"
    assert row["session_id"] == "w777"


def test_transcribe_rejects_empty_bytes():
    with pytest.raises(voice.AudioDecodeError):
        voice.transcribe(b"")


# ── base64 JSON variant (Zepp side-fetch can't send binary bodies) ──

def test_voice_b64_json_relays(client, monkeypatch):
    import base64
    monkeypatch.setattr(voice, "transcribe",
                        lambda _: {"text": "b64 path works",
                                   "duration": 1.0, "language": "en"})
    payload = {"b64": base64.b64encode(b"opus bytes").decode()}
    r = client.post("/voice?session_id=w888", json=payload,
                    headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.json()["transcribed"] == "b64 path works"


def test_voice_invalid_b64_is_400(client):
    r = client.post("/voice", json={"b64": "!!!not base64!!!"},
                    headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 400


def test_voice_empty_b64_is_400(client):
    r = client.post("/voice", json={"b64": ""},
                    headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 400
