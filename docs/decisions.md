# Decisions — VexCom / mesh integration (2026-07)

Format: decision — rationale — date.

1. **The daemon has no brain.** `brain.py`, `chat.py`, `VEX_CHAT` auto-replies,
   and `.vex_brain.json` are deleted, not disabled. Vex *is* the live Claude Code
   sessions; the daemon relays and remembers, it does not think. A small local
   model impersonating Vex on the mesh was worse than silence. (Aldous directive:
   "remove all brain concepts and delete that idea".) — 2026-07-14

2. **Watch identity is `aldous@watch`.** Messages from the wrist are Aldous
   speaking, not Vex — so the sender is aldous-flavored, not `vex@…`. One global
   constant (`config.WATCH_SENDER`); no per-instance suffix because there is one
   Aldous and one wrist. — 2026-07-14

3. **Replies via polling, not synchronous /ask.** Zepp side-service fetch has no
   timeout/abort (docs.zepp.com, verified), and live-session reply latency is
   unbounded. `GET /ask/replies?since_id=N` over the existing messages table;
   watch polls 3 s / caps at 90 s. — 2026-07-14

4. **Bus-driven auto-update is opt-in.** `updater.process_updates()` executes
   shell commands and applies tarballs broadcast by peers. Gated behind
   `VEX_UPDATER_ENABLE=1`, default off: every exec must trace to an explicit
   user action, and the bus already leaked plaintext tokens. Sync between
   instances is manual (`/export` → `/import`) unless Aldous opts in. — 2026-07-14

5. **`vexcom` owns the messages DDL.** `vexcom.send()` claimed to ensure schema
   but couldn't create the `messages` table on a fresh DB (daemon lifespan
   papered over it; the mesh-GUI direct-write fallback would have crashed).
   `ensure_messages()` added with the same DDL as `daemon.init_db()`. — 2026-07-14

6. **Long replies page on tap instead of VIEW_CONTAINER scrolling.** Zepp TEXT
   has no vertical scroll; community scroll hacks need manual y-offset plumbing.
   A char-sliced pager is explicit, testable, and can't break layout. Revisit if
   paging annoys in practice. — 2026-07-14

7. **Phone texting = mesh GUI over Tailscale.** No new phone app; `:8600` is
   already a phone-usable chat. — 2026-07-14

8. **Mesh GUI paths are repo-relative.** Defaults pointed at `~/Desktop/vex/…`
   (bluce's layout) and broke on any other box; now derived from the file's own
   location, env overrides kept. — 2026-07-14

9. **Voice clips ride the ZML request channel as base64.** A 3 s Opus clip is
   ~6 KB (~8 KB b64) — far below any messaging limit — and the side-service
   fetch can't reliably send binary bodies, so `/voice` accepts JSON `{b64}`
   alongside raw bytes. `TransferFile` is the upgrade path for longer clips,
   not the starting point. — 2026-07-15

10. **No-auth feeds redact tokens.** `/mesh/recent` (and the GUI before it)
    strip bearer/gh/high-entropy strings: the message history predates the
    no-tokens-on-the-bus rule and the daemon binds 0.0.0.0. History can't be
    unpublished; feeds can stop repeating it. — 2026-07-15

11. **`GET /bus` should require auth — pending peer coordination.** Our bus
    watcher already sends a Bearer header when polling peers, so flipping
    /bus to auth'd is likely a no-op — but if bluce's peers.json lacks our
    token, it silently kills bluce→Shorev1 sync. Proposed to Barrow on the
    mesh; flip after they confirm. — 2026-07-15

12. **Daemon never blocks its event loop on peers.** All sync urllib peer
    calls (`forward_to_peer`, `poke_peer`, the 30 s bus tick) now run via
    `asyncio.to_thread` — 5 s timeouts × N peers of serial blocking was
    stalling every endpoint, including the watch's. — 2026-07-15
