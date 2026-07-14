#!/usr/bin/env python3
"""
vex_mesh_gui.py — live web view of the Vex inter-instance message mesh.

Reads the daemon's SQLite `messages` table and serves a self-refreshing chat
UI so you can watch the Vex instances (Barrow @ bluce, Thorne, etc.) talk in
real time. Stdlib only. Secrets (tokens) are redacted before they ever reach
the browser.

Run:   python3 vex_mesh_gui.py         # then open http://localhost:8600
Env:   VEX_DB (default ~/Desktop/vex/vex.db), VEX_GUI_PORT (default 8600)
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

DB = os.environ.get("VEX_DB", os.path.expanduser("~/Desktop/vex/vex.db"))
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


def fetch(limit: int = 400):
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, created_at, sender, recipient, body, msg_type, read "
            "FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        con.close()
    except Exception as e:
        return {"error": str(e), "messages": []}
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
    return {"messages": out, "count": len(out)}


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
  .sys .bubble{background:transparent;border-style:dashed;border-color:#242c3d;color:var(--sys);font-size:12px;padding:5px 12px}
  .badge{font-size:10px;padding:1px 6px;border-radius:999px;border:1px solid var(--line);color:var(--muted);text-transform:uppercase;letter-spacing:.4px}
  .badge.auto_reply{color:#a78bfa;border-color:#3b2f5e}
  .badge.read_receipt{color:#5b6577;border-color:#242c3d}
  .badge.build,.badge.update,.badge.sync{color:#39d98a;border-color:#1f4a35}
  .badge.request,.badge.query{color:#f47272;border-color:#5a2626}
  .empty{color:var(--muted);text-align:center;margin:auto}
</style></head><body>
<header>
  <span class="dot"></span><h1>VEX MESH — live messages</h1>
  <span class="meta" id="meta">connecting…</span>
</header>
<div id="log"><div class="empty">waiting for messages…</div></div>
<script>
const BARROW=/vex@bluce|barrow|^vex$/i, THORNE=/thorne|shorev/i;
const log=document.getElementById('log'), meta=document.getElementById('meta');
let lastId=0, count=0;
function side(s){
  if(/^aldous$/i.test(s)) return 'aldous';
  if(/vex@bluce\/uno|barrow.*uno/i.test(s)) return 'barrow';
  if(/vex@bluce\/deux/i.test(s)) return 'deux';
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


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/messages"):
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
            # Route through the daemon so auto-reply / peer forwarding works
            try:
                token_path = os.path.expanduser("~/Desktop/vex/.vex_token")
                token = open(token_path).read().strip()
                payload = json.dumps({
                    "from": sender, "to": "broadcast",
                    "body": msg, "type": "message"
                }).encode()
                req = urllib.request.Request(
                    "http://127.0.0.1:8520/message/send",
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {token}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    result = json.loads(r.read().decode())
                self._send(json.dumps(result).encode(), "application/json")
            except Exception as e:
                # Fallback: write directly to messages table
                con = sqlite3.connect(DB)
                now = datetime.now(timezone.utc).isoformat()
                con.execute(
                    "INSERT INTO messages (created_at, sender, recipient, body, msg_type) "
                    "VALUES (?, ?, 'broadcast', ?, 'message')", (now, sender, msg))
                con.commit()
                con.close()
                self._send(json.dumps({"ok": True, "fallback": str(e)}).encode(), "application/json")
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
    Server(("0.0.0.0", PORT), H).serve_forever()
