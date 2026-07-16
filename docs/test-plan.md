# Test plan — daemon + VexCom watch app

## Daemon unit tests (automated)

Run: `.venv/bin/python3 -m pytest tests/ -v`  (from repo root; deps: pytest, httpx)

Isolation: `tests/conftest.py` points `VEX_HOME` at a throwaway temp dir before
any daemon import — token, DB, bus file and diary never touch the real home.

Covered (tests/unit/):
- `test_ask.py` — auth boundary (401 ×3), input validation (400 empty, 413
  oversized, 400 bad since_id), keyword fast path (ping/echo, identity/grounded),
  mesh relay envelope (sender=aldous@watch, recipient=broadcast, msg_type=voice,
  session_id correlation, msg_id returned), reply polling (recipient filter,
  since_id watermark, empty-after-last), brain stays deleted (ImportError).
- `test_updater.py` — bus-driven exec disabled by default; only exactly
  `VEX_UPDATER_ENABLE=1` enables.

## Daemon integration gates (manual, run 2026-07-15, all passed)

```bash
TOK=$(cat .vex_token)
curl -s http://localhost:8520/health                                  # ok:true
curl -s -X POST http://localhost:8520/peers/ping -H "Authorization: Bearer $TOK" \
     -H 'Content-Type: application/json' -d '{"name":"bluce"}'        # peer ok
curl -s -X POST http://localhost:8520/ask ... -d '{"message":"ping"}' # mode:echo
curl -s -X POST http://localhost:8520/ask ... -d '{"message":"free text"}'
                                          # mode:relay + msg_id + session_id
curl -s "http://localhost:8520/mesh/recent?n=3"   # relay row visible, sender aldous@watch
curl -s -X POST .../message/send -d '{"to":"aldous@watch","body":"..."}'
curl -s ".../ask/replies?since_id=<msg_id>" -H "Authorization: Bearer $TOK"
                                          # reply returned, last_id advances
```

## Watch app (manual — no simulator harness on this box)

Stage gate order; do not proceed past a failing gate:
1. **Build**: `bash build_zepp.sh` → `vex_voice/zepp/dist/*.zab` exists.
2. **Install**: `npx zeus preview` in `vex_voice/zepp/` → QR → Zepp phone app
   (developer mode ON) → installs to Active Max.
3. **Settings**: enter `https://shorev1.tail41a911.ts.net` + `~/vex/.vex_token`
   contents. Phone must be on the tailnet (Tailscale app, same account).
4. **Fast path**: tap `status` → reply within ~2 s, no polling.
5. **Relay path**: tap `tell Barrow hi` → relay ack. Then a free prompt →
   "Sent — waiting for Vex…" → post a reply in the mesh GUI addressed to
   `aldous@watch` → lands on the wrist within one 3 s poll.
6. **Give-up path**: free prompt, reply with nothing for 90 s → "Vex is away —
   check the mesh later."
7. **Pager**: send a >200-char reply → tap the reply text → pages cycle.

## Voice stage (S4 — gated)

1. Mic spike page: record 3 s (`@zos/media` RECORDER, Opus) and play back on the
   Active Max. **If this fails, the voice stage stops** (fallback: phone
   dictation into the mesh GUI).
2. `/voice` negative paths (unit): no body 400, >5 MB 413, garbage audio 400,
   STT missing 503 — never a 500.
3. End-to-end: speak "hello vex" → transcript on mesh as aldous@watch →
   reply on wrist.

## Known issues

- Daemon event loop stalls intermittently under peer-poll load (sync `urllib`
  peer calls inside async handlers). Symptom: sporadic empty/timed-out local
  responses. Watch polling tolerates it (transient failures keep polling).
  Fix queued: move peer HTTP to a thread executor. — logged 2026-07-15
