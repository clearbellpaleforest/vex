# Implementation plan — VexCom ↔ mesh (as built, 2026-07-15)

Full working plan lived in the session plan file; this is the as-built record.
Design detail: `design.md`. Rationale: `decisions.md`. Verification: `test-plan.md`.

| Stage | Status | What shipped |
|---|---|---|
| S0 bring-up | ✅ | Updater gated (`VEX_UPDATER_ENABLE`, default off); mesh GUI paths fixed + restarted; daemon up on 0.0.0.0:8520; tailscale serve → :8520 confirmed |
| S1 daemon | ✅ | `brain.py`/`chat.py`/`VEX_CHAT` deleted; single `/ask` (keyword fast path, default = mesh relay as `aldous@watch`); `GET /ask/replies`; `WATCH_SENDER`; `vexcom.ensure_messages()` (fresh-DB bug); pytest suite |
| S2 mesh GUI | ✅ | `aldous@watch` amber styling + `voice` badge; JS regex escape fix |
| S3 watch app | ✅ code / ⏳ hardware | node22 toolchain (+ icon — the real v1 build blocker), clean `zeus build` → `dist/*.zab`; v1.5: reply polling 3 s/90 s, tap-pager, `mic` nav. Remaining: QR install + on-wrist gates (needs Aldous) |
| S4 voice | ✅ server+code / ⏳ spike | `voice.py` (faster-whisper tiny.en, py3.14 OK, Opus direct); `POST /voice` raw + `{b64}`; silence→no relay; temp files deleted; `pages/mic.js` record/play/send. Remaining: mic spike on the Active Max gates the stage |
| S5 sweep | ✅ | Event-loop stall fixed (`asyncio.to_thread` on all peer calls); `/mesh/recent` token redaction + test; docs (design/decisions/test-plan/architecture/README) |
| S6 phone chat | ⏳ | Needs `sudo tailscale serve --bg --https=8600 http://127.0.0.1:8600` (root; one-time `sudo tailscale set --operator=aldous` avoids future sudo) |

Open items:
- `/bus` auth flip — proposed to Barrow, waiting on peer confirmation (decisions.md #11)
- peers.json hygiene — 3 duplicate bluce entries + a stale `vex@bluce/deux → 127.0.0.1` entry make the bus tick poll bluce 3× and the daemon poll itself; prune with Aldous
- real-speech STT accuracy check — first wrist recording doubles as the test (tiny.en; bump `VEX_STT_MODEL=base.en` if accuracy disappoints)
