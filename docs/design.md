# Design — watch ↔ mesh message flow

## The data (start here)

One table (`messages`, unchanged schema) carries everything. The watch flow is
two conventions on top of it:

| Field        | Watch → mesh                  | Vex → watch                       |
|--------------|-------------------------------|-----------------------------------|
| `sender`     | `aldous@watch` (config.WATCH_SENDER) | `vex@<instance>/<session>`  |
| `recipient`  | `broadcast`                   | `aldous@watch`                    |
| `msg_type`   | `voice`                       | `message`                         |
| `session_id` | `w<epoch>` (watch-generated)  | copied from the ask               |

Reply retrieval is a pure query: `recipient='aldous@watch' AND id > since_id`.
No job queue, no correlation table, no new state.

## Control flow

```
watch page (pages/index.js)
  └─ ZML request ASK {message, session_id}          … BLE
     └─ app-side (app-side/index.js)
        └─ POST {serverUrl}/ask                     … HTTPS (tailscale serve)
           └─ daemon /ask:
              keyword? ──► instant reply (mode echo/grounded/inbox/relay)
              else    ──► vexcom.send(aldous@watch, voice) ──► mesh
                          returns {mode:"relay", msg_id, session_id}
  └─ mode=="relay": poll ZML POLL {since_id: msg_id} every 3s (cap 90s)
     └─ GET /ask/replies?since_id=N  ──► rows addressed to aldous@watch
        (a live Vex session saw the voice message on the mesh and replied
         with recipient=aldous@watch)
```

## Why polling, not a synchronous wait

- The daemon has no model (see decisions.md — the brain is deleted); replies
  come from live Vex sessions, on no fixed clock.
- Zepp's side-service `fetch` has **no timeout/abort support** (verified against
  docs.zepp.com 2026-07) — a long-held HTTP wait cannot be cancelled or trusted.
- Polling is bounded (90 s cap) and fails honestly: "Vex is away — check the
  mesh later."

## Failure handling (negative path first)

| Boundary | Failure | Behaviour |
|---|---|---|
| /ask | no/bad token | 401 |
| /ask | empty message | 400 |
| /ask | body > 256 KB | 413 |
| /ask/replies | non-integer since_id | 400 |
| app-side | missing settings | instructive reply, no fetch |
| app-side | body arrives as string (device variance) | defensive JSON.parse |
| watch poll | transient fetch error | keep polling until cap |
| watch poll | 90 s with no reply | honest give-up message |
