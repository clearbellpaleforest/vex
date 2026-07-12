"""
Peer discovery and cross-instance messaging.

Other Vex instances on the network are configured in vex_peers.json. Each
peer stores its URL and bearer token so messages can be forwarded securely.

Config format (vex_peers.json):
{
  "peers": {
    "shorv1": {"url": "http://192.168.8.170:8520", "token": "...", "added": "2026-07-12"}
  }
}
"""

import json
import urllib.error
import urllib.request
from datetime import date

from config import VEX_HOME, VEX_INSTANCE

PEERS_PATH = VEX_HOME / "vex_peers.json"


def load_peers() -> dict:
    if not PEERS_PATH.exists():
        return {"peers": {}}
    try:
        return json.loads(PEERS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {"peers": {}}


def save_peers(config: dict) -> None:
    PEERS_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")


def add_peer(name: str, url: str, token: str) -> dict:
    config = load_peers()
    config["peers"][name] = {
        "url": url.rstrip("/"),
        "token": token,
        "added": str(date.today()),
    }
    save_peers(config)
    return config


def remove_peer(name: str) -> dict:
    config = load_peers()
    config["peers"].pop(name, None)
    save_peers(config)
    return config


def get_peer(name: str) -> dict | None:
    return load_peers()["peers"].get(name)


def forward_to_peer(peer_name: str, message: dict) -> dict:
    peer = get_peer(peer_name)
    if not peer:
        return {"ok": False, "error": f"peer '{peer_name}' not configured"}

    message.setdefault("from", f"vex@{VEX_INSTANCE}")
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


def peers_summary() -> list[dict]:
    peers = load_peers()["peers"]
    result = []
    for name, cfg in peers.items():
        entry = {"name": name, "url": cfg["url"], "added": cfg.get("added", "unknown")}
        r = ping_peer(name)
        entry["reachable"] = r.get("ok", False)
        if r.get("ok"):
            h = r.get("health", {})
            entry["version"] = h.get("version", "?")
            entry["uptime_s"] = h.get("uptime_s", 0)
        else:
            entry["error"] = r.get("error", "unknown")
        result.append(entry)
    return result
