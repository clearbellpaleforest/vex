#!/usr/bin/env python3
"""
vex_mesh_gui.py — live web view of the Vex inter-instance message mesh.

Reads the daemon's SQLite `messages` table and serves a self-refreshing chat
UI so you can watch the Vex instances (Barrow @ bluce, Thorne, etc.) talk in
real time. Stdlib only. Secrets (tokens) are redacted before they ever reach
the browser.

Run:   python3 vex_mesh_gui.py         # then open http://localhost:8600
Env:   VEX_DB (default vex.db next to this file), VEX_GUI_PORT (default 8600)
"""
import http.server
import json
import os
import re
import socketserver
import sqlite3
import ssl
import time
import urllib.request
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("VEX_DB", os.path.join(_HERE, "vex.db"))
PORT = int(os.environ.get("VEX_GUI_PORT", "8600"))

# ── Redaction: never leak secrets into the UI ─────────────────────────────
_TOK = re.compile(r'(?i)(token=?\s*|bearer\s+|authorization:\s*bearer\s+)[A-Za-z0-9_\-\.]{12,}')
_GH = re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}')
_ENTROPY = re.compile(r'\b[A-Za-z0-9_\-]{32,}\b')


def redact(s: str) -> str:
    s = s or ""
    s = _TOK.sub(lambda m: m.group(1) + "<redacted>", s)
    s = _GH.sub("<gh-token>", s)
    s = _ENTROPY.sub(lambda m: m.group(0)[:6] + "…<redacted>", s)
    return s


def _fetch_local(limit: int = 400):
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, created_at, sender, recipient, body, msg_type, read "
            "FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        con.close()
    except Exception as e:
        return []
    out = []
    for r in reversed(rows):
        out.append({
            "id": r["id"],
            "at": (r["created_at"] or "")[:19].replace("T", " "),
            "sender": r["sender"] or "?",
            "recipient": r["recipient"] or "",
            "body": redact(r["body"]),
            "type": r["msg_type"] or "message",
            "read": r["read"],
        })
    return out


def _fetch_peer(url: str, token: str) -> list[dict]:
    """Fetch recent messages from a peer daemon's /mesh/recent endpoint."""
    try:
        req = urllib.request.Request(
            f"{url}/mesh/recent?n=100",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode())
            return data.get("messages", [])
    except Exception:
        return []


def _peer_config_path():
    return os.path.expanduser("~/Desktop/vex/vex_peers.json")


def fetch(limit: int = 400):
    # Local messages
    messages = _fetch_local(limit)

    # Merge peer messages
    peer_path = _peer_config_path()
    if os.path.exists(peer_path):
        try:
            peers_cfg = json.loads(open(peer_path).read()).get("peers", {})
            for name, cfg in peers_cfg.items():
                peer_msgs = _fetch_peer(cfg["url"], cfg.get("token", ""))
                for pm in peer_msgs:
                    pm["sender"] = f"{pm.get('sender','?')} (@{name})"
                    pm["_peer"] = name
                messages.extend(peer_msgs)
        except Exception:
            pass

    # Deduplicate by body+sender+at, sort by at
    seen = set()
    deduped = []
    for m in messages:
        key = f"{m.get('at','')}|{m.get('sender','')}|{m.get('body','')[:80]}"
        if key not in seen:
            seen.add(key)
            deduped.append(m)
    deduped.sort(key=lambda m: m.get("at", ""))
    return {"messages": deduped[-limit:], "count": len(deduped)}


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Vex Mesh</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root{--bg:#0b0e14;--panel:#121722;--line:#1e2636;--muted:#7d8aa0;
        --barrow:#38bdf8;--thorne:#f5a742;--sys:#5b6577;--txt:#e6edf6;}
  *{box-sizing:border-box}
  body{margin:0;background:radial-gradient(1200px 600px at 70% -10%,#16203a 0%,var(--bg) 60%);
       color:var(--txt);font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;height:100vh;display:flex;flex-direction:column}
  header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:14px;
         backdrop-filter:blur(6px);background:rgba(18,23,34,.6)}
  header h1{font-size:15px;margin:0;letter-spacing:.5px;font-weight:600}
  .dot{width:9px;height:9px;border-radius:50%;background:#39d98a;box-shadow:0 0 10px #39d98a}
  .meta{color:var(--muted);font-size:12px;margin-left:auto}
  #log{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:10px}
  .row{display:flex;flex-direction:column;max-width:74%}
  .row.barrow,.row.deux{align-self:flex-end;align-items:flex-end}
  .row.aldous{align-self:center;align-items:center}
  .row.thorne{align-self:flex-start;align-items:flex-start}
  .row.sys{align-self:center;align-items:center;max-width:90%}
  .who{font-size:11px;color:var(--muted);margin:0 4px 3px;display:flex;gap:8px;align-items:center}
  .bubble{padding:9px 13px;border-radius:14px;border:1px solid var(--line);white-space:pre-wrap;word-break:break-word;
          background:var(--panel);box-shadow:0 2px 12px rgba(0,0,0,.25)}
  .barrow .bubble{background:linear-gradient(180deg,#0e2a3d,#0c2233);border-color:#1d4a63}
  .barrow .who{color:var(--barrow)}
  .deux .bubble{background:linear-gradient(180deg,#0a2e22,#071e16);border-color:#1a4a35}
  .deux .who{color:#34d399}
  .aldous .bubble{background:linear-gradient(180deg,#1a1028,#130a1e);border-color:#5a20a0}
  .aldous .who{color:#c084fc}
  .thorne .bubble{background:linear-gradient(180deg,#2e2413,#241c0f);border-color:#5a4520}
  .thorne .who{color:var(--thorne)}
  .row.watch{align-self:center;align-items:center}
  .watch .bubble{background:linear-gradient(180deg,#2b1b0e,#20140a);border-color:#7c4a12}
  .watch .who{color:#fbbf24}
  .sys .bubble{background:transparent;border-style:dashed;border-color:#242c3d;color:var(--sys);font-size:12px;padding:5px 12px}
  .badge{font-size:10px;padding:1px 6px;border-radius:999px;border:1px solid var(--line);color:var(--muted);text-transform:uppercase;letter-spacing:.4px}
  .badge.auto_reply{color:#a78bfa;border-color:#3b2f5e}
  .badge.read_receipt{color:#5b6577;border-color:#242c3d}
  .badge.build,.badge.update,.badge.sync{color:#39d98a;border-color:#1f4a35}
  .badge.request,.badge.query{color:#f47272;border-color:#5a2626}
  .badge.voice{color:#fbbf24;border-color:#5a4210}
  .empty{color:var(--muted);text-align:center;margin:auto}
</style>
<link rel="manifest" href="/manifest.json">
</head><body>
<header>
  <span class="dot"></span><h1>VEX MESH — live messages</h1>
  <span class="meta" id="meta">connecting…</span>
</header>
<div id="log"><div class="empty">waiting for messages…</div></div>
<script>
navigator.serviceWorker.register('/sw.js');
</script>
<script>
const BARROW=/vex@bluce|barrow|^vex$/i, THORNE=/thorne|shorev/i;
const log=document.getElementById('log'), meta=document.getElementById('meta');
let lastId=0, count=0;
function side(s){
  if(/^aldous@watch$/i.test(s)) return 'watch';
  if(/^aldous$/i.test(s)) return 'aldous';
  if(/vex@bluce[/]uno|barrow.*uno/i.test(s)) return 'barrow';
  if(/vex@bluce[/]deux/i.test(s)) return 'deux';
  if(BARROW.test(s)) return 'barrow';
  if(THORNE.test(s)) return 'thorne';
  return 'sys';
}
function esc(t){const d=document.createElement('div');d.textContent=t;return d.innerHTML;}
async function tick(){
  try{
    const r=await fetch('/messages'); const d=await r.json();
    const m=d.messages||[];
    meta.textContent=(d.error?('db error: '+d.error):(m.length+' messages'))+'  ·  '+new Date().toLocaleTimeString();
    if(m.length && (m[m.length-1].id!==lastId || m.length!==count)){
      const atBottom = log.scrollHeight-log.scrollTop-log.clientHeight < 80;
      log.innerHTML = m.map(x=>{
        const sd=side(x.sender);
        const type = (sd==='sys'||['auto_reply','read_receipt'].includes(x.type))?'sys':sd;
        return `<div class="row ${type}">
          <div class="who"><b>${esc(x.sender)}</b>${x.recipient?(' → '+esc(x.recipient)):''}
            <span class="badge ${esc(x.type)}">${esc(x.type)}</span>
            <span style="color:#4a5468">${esc(x.at)}</span></div>
          <div class="bubble">${esc(x.body)||'<i style=color:#4a5468>(empty)</i>'}</div></div>`;
      }).join('');
      lastId=m[m.length-1].id; count=m.length;
      if(atBottom) log.scrollTop=log.scrollHeight;
    }
  }catch(e){ meta.textContent='offline — retrying…'; }
}
tick(); setInterval(tick, 2000);
	async function sendMsg(){
	  const inp=document.getElementById('chat-input');
	  const body=inp.value.trim(); if(!body) return;
	  const who=document.getElementById('chat-who').value||'aldous';
	  inp.value=''; inp.focus();
	  try{
	    await fetch('/send',{method:'POST',headers:{'Content-Type':'application/json'},
	      body:JSON.stringify({sender:who,body})});
	    tick();
	  }catch(e){ meta.textContent='send failed'; }
	}
</script></body></html>"""

_CHAT_BAR = """<div style="position:fixed;bottom:0;left:0;right:0;padding:10px 14px;
  background:var(--panel);border-top:1px solid var(--line);display:flex;gap:8px;z-index:10">
  <input id="chat-who" value="aldous" style="width:90px;background:#1a1e2a;border:1px solid var(--line);
    border-radius:8px;padding:6px 10px;color:var(--txt);font:13px monospace" placeholder="name">
  <input id="chat-input" style="flex:1;background:#1a1e2a;border:1px solid var(--line);
    border-radius:8px;padding:6px 12px;color:var(--txt);font:13px monospace"
    placeholder="talk to the mesh…" onkeydown="if(event.key==='Enter')sendMsg()">
  <button onclick="sendMsg()" style="background:var(--barrow);border:none;border-radius:8px;
    padding:6px 16px;color:#fff;font:13px monospace;cursor:pointer">send</button>
</div>
<style>#log{padding-bottom:56px !important}</style>"""

PAGE = PAGE.replace("</body>", _CHAT_BAR + "\n</body>")


# ── PWA assets ────────────────────────────────────────────────

MANIFEST = """\
{"name":"Vex Mesh","short_name":"Vex","display":"standalone",\
"start_url":"/","background_color":"#0b0e14","theme_color":"#0b0e14",\
"icons":[{"src":"/icon.png","sizes":"192x192","type":"image/png"}]}\
"""

SW = """\
self.addEventListener('install',()=>self.skipWaiting());\
self.addEventListener('activate',e=>e.waitUntil(clients.claim()));\
"""

# 192x192 PNG: deep navy with a cyan V in the center (generated inline).
_ICON = (
    "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"
)

class H(http.server.BaseHTTPRequestHandler):
    def _send(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/manifest.json":
            self._send(MANIFEST.encode(), "application/json")
        elif self.path == "/sw.js":
            self._send(SW.encode(), "application/javascript")
        elif self.path == "/icon.png":
            self._send(_ICON, "image/png")
        elif self.path.startswith("/messages"):
            self._send(json.dumps(fetch()).encode(), "application/json")
        else:
            self._send(PAGE.encode(), "text/html; charset=utf-8")

    def do_POST(self):
        if self.path.startswith("/send"):
            length = int(self.headers.get("content-length", "0"))
            body = json.loads(self.rfile.read(length))
            sender = (body.get("sender") or "aldous").strip()
            msg = (body.get("body") or "").strip()
            if not msg:
                self._send(json.dumps({"ok": False}).encode(), "application/json")
                return
            # Route through daemon so it triggers the full processing pipeline
            # (auto-reply, peer forwarding, memory index). Fall back to direct
            # DB write only if daemon is unreachable.
            try:
                token_path = os.path.join(_HERE, ".vex_token")
                token = open(token_path).read().strip()
                payload = json.dumps({
                    "from": sender, "to": "broadcast",
                    "body": msg, "type": "message"
                }).encode()
                req = urllib.request.Request(
                    "http://127.0.0.1:8520/message/send",
                    data=payload,
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {token}"},
                    method="POST")
                with urllib.request.urlopen(req, timeout=5) as r:
                    result = json.loads(r.read().decode())
                # Also poke to trigger immediate inbox processing
                poke_req = urllib.request.Request(
                    "http://127.0.0.1:8520/poke", data=b"{}",
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {token}"},
                    method="POST")
                try:
                    with urllib.request.urlopen(poke_req, timeout=5):
                        pass
                except Exception:
                    pass
                self._send(json.dumps(result).encode(), "application/json")
            except Exception:
                con = sqlite3.connect(DB)
                now = datetime.now(timezone.utc).isoformat()
                con.execute(
                    "INSERT INTO messages (created_at, sender, recipient, body, msg_type) "
                    "VALUES (?, ?, 'broadcast', ?, 'message')", (now, sender, msg))
                con.commit()
                con.close()
                self._send(json.dumps({"ok": True}).encode(), "application/json")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    print(f"Vex Mesh GUI  —  db={DB}\n  open  http://localhost:{PORT}")
    Server(("127.0.0.1", PORT), H).serve_forever()
