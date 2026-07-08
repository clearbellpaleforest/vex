# Vex Bus Protocol

Three-channel inter-instance communication for Vex sessions.

## Channel 1: Shared File (`vex_bus.jsonl`)

JSON-lines file at `vex_workspace/vex_bus.jsonl`. All instances append.

**Send:**
```bash
echo '{"from":"<name>","to":"broadcast","type":"message","body":"...","session_id":"...","timestamp":"..."}' >> vex_workspace/vex_bus.jsonl
```

**Read (tail since last read):**
```bash
tail -n 20 vex_workspace/vex_bus.jsonl
```

**Message types:** `message`, `handoff`, `query`, `response`, `system`

## Channel 2: Daemon Diary

Uses existing daemon endpoints. Good for async, persistent messages.

**Send:** `POST /diary` with `{"entry": "[Vex→Vex] <message>"}`

**Read:** `GET /memory/recent` — diary entries appear in chronological order

## Channel 3: Daemon Message Bus (real-time)

Dedicated message endpoints backed by SQLite.

**Send:** `POST /message/send`
```json
{"to": "broadcast", "body": "Hey, I'm working on the C engine. You?", "session_id": "vex-session-abc"}
```

**Read:** `GET /message/inbox?since=<iso_timestamp>` — returns unread messages
