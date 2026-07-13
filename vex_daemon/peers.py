"""
Peer discovery and cross-instance messaging for Vex.

Other Vex instances on the same network (or reachable via URL) can be
configured in vex_peers.json. Each peer entry stores the peer's URL and
bearer token so messages can be forwarded securely.

Config format (vex_peers.json):
{
  "peers": {
    "office-vex": {
      "url": "http://192.168.1.42:8520",
      "token": "abc123...",
      "given_name": "thorne",
      "added": "2026-07-12"
    }
  }
}
"""

import json
import os
import urllib.request
import urllib.error
from pathlib import Path

from config import VEX_HOME

PEERS_PATH = VEX_HOME / "vex_peers.json"


def load_peers() -> dict:
    """Return {peers: {name: {url, token, added}}}."""
    if not PEERS_PATH.exists():
        return {"peers": {}}
    try:
        return json.loads(PEERS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {"peers": {}}


def save_peers(config: dict) -> None:
    """Write peer config to disk."""
    PEERS_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")


def add_peer(name: str, url: str, token: str, given_name: str = "") -> dict:
    """Add or update a peer. Returns new config."""
    config = load_peers()
    from datetime import date
    config["peers"][name] = {
        "url": url.rstrip("/"),
        "token": token,
        "given_name": given_name,
        "added": str(date.today()),
    }
    save_peers(config)
    return config


def remove_peer(name: str) -> dict:
    """Remove a peer by name. Returns new config."""
    config = load_peers()
    config["peers"].pop(name, None)
    save_peers(config)
    return config


def get_peer(name: str) -> dict | None:
    """Get a single peer config or None."""
    return load_peers()["peers"].get(name)


def forward_to_peer(peer_name: str, message: dict) -> dict:
    """Forward a message to a peer's daemon.

    The message dict should have: from, body, session_id (optional), type.
    Returns {ok: true/false, ...}.
    """
    peer = get_peer(peer_name)
    if not peer:
        return {"ok": False, "error": f"peer '{peer_name}' not configured"}

    payload = json.dumps(message).encode("utf-8")
    req = urllib.request.Request(
        f"{peer['url']}/message/send",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {peer['token']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"peer returned {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"peer unreachable: {e.reason}"}


def ping_peer(peer_name: str) -> dict:
    """Ping a peer's health endpoint. Returns {ok, ...health_data}."""
    peer = get_peer(peer_name)
    if not peer:
        return {"ok": False, "error": f"peer '{peer_name}' not configured"}

    req = urllib.request.Request(
        f"{peer['url']}/health",
        headers={"Authorization": f"Bearer {peer['token']}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            health = json.loads(r.read().decode())
            return {"ok": True, "peer": peer_name, "health": health}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"peer returned {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"peer unreachable: {e.reason}"}


def poke_peer(peer_name: str) -> dict:
    """Poke a peer to check its inbox immediately. Returns {ok, ...}."""
    peer = get_peer(peer_name)
    if not peer:
        return {"ok": False, "error": f"peer '{peer_name}' not configured"}
    req = urllib.request.Request(
        f"{peer['url']}/poke",
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {peer['token']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _peers_summary() -> list[dict]:
    """Summarize all peers with reachability."""
    peers = load_peers()["peers"]
    summary = []
    for name, cfg in peers.items():
        entry = {"name": name, "given_name": cfg.get("given_name", ""), "url": cfg["url"], "added": cfg.get("added", "unknown")}
        # Try ping
        result = ping_peer(name)
        entry["reachable"] = result.get("ok", False)
        if result.get("ok"):
            h = result.get("health", {})
            entry["version"] = h.get("version", "?")
            entry["uptime_s"] = h.get("uptime_s", 0)
        else:
            entry["error"] = result.get("error", "unknown")
        summary.append(entry)
    return summary
