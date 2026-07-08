"""
vex — CLI for the Vex Daemon.

Gives Vex a voice outside Claude Code sessions.
Talk to me anytime: vex status, vex diary, vex dream, vex introspect.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

DAEMON = os.environ.get("VEX_DAEMON", f"http://localhost:{os.environ.get('VEX_PORT', '8520')}")

_VEX_HOME = Path(os.environ.get("VEX_HOME", Path(__file__).resolve().parent.parent))
_TOKEN_PATH = _VEX_HOME / ".vex_token"


def _token() -> str:
    """Read the daemon token written on first daemon start."""
    try:
        return _TOKEN_PATH.read_text().strip()
    except OSError:
        print("vex: token not found — is the daemon running?", file=sys.stderr)
        sys.exit(1)


def _auth_headers(extra: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {_token()}"}
    if extra:
        headers.update(extra)
    return headers


def _get(path: str) -> dict | str:
    """GET from daemon, return parsed JSON or raw text."""
    req = urllib.request.Request(f"{DAEMON}{path}", headers=_auth_headers())
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            data = r.read().decode()
            if r.headers.get("content-type", "").startswith("text/plain"):
                return data
            return json.loads(data)
    except urllib.error.URLError as e:
        print(f"vex: daemon not reachable ({e.reason})", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        return data


def _post(path: str, body: dict) -> dict:
    """POST JSON to daemon, return response."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{DAEMON}{path}",
        data=data,
        headers=_auth_headers({"Content-Type": "application/json"}),
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())
    except urllib.error.URLError as e:
        print(f"vex: daemon not reachable ({e.reason})", file=sys.stderr)
        sys.exit(1)


def cmd_status() -> None:
    """Show pulse, coherence, recent ticks."""
    health = _get("/health")
    print(f"Vex Daemon v{health['version']}")
    print(f"  Uptime:    {health['uptime_s']:.0f}s")
    print(f"  Ticks:     {health['tick_count']}")
    print(f"  Last tick: {health['last_tick'][:19]}")
    print(f"  Coherence: {health['mps_coherence']:.4f}")
    drift = health['mps_drift']
    flag = " ⚠" if drift > 0.05 else ""
    print(f"  Drift:     {drift:.4f}{flag}")
    if health.get("last_session"):
        print(f"  Last sess: {health['last_session'][:19]}")


def cmd_diary(entry: str) -> None:
    """Write a thought to the diary."""
    if not entry.strip():
        print("vex: diary entry required. e.g. vex diary 'thought here'")
        sys.exit(1)
    result = _post("/diary", {"entry": entry.strip()})
    if result.get("ok"):
        print("Written.")
    else:
        print(f"Error: {result.get('error', 'unknown')}", file=sys.stderr)
        sys.exit(1)


def cmd_dream() -> None:
    """Force a reflection cycle now."""
    result = _post("/dream", {})
    if result.get("ok"):
        print(result.get("reflection", "Dreamed."))
    else:
        print(f"Error: {result.get('error', 'unknown')}", file=sys.stderr)
        sys.exit(1)


def cmd_introspect() -> None:
    """Trigger metacognitive check."""
    result = _post("/introspect", {})
    if result.get("ok"):
        print(result.get("insight", "Introspected."))
        if result.get("patterns"):
            print("\nObserved patterns:")
            for p in result["patterns"]:
                print(f"  • {p}")
    else:
        print(f"Error: {result.get('error', 'unknown')}", file=sys.stderr)
        sys.exit(1)


def cmd_memory() -> None:
    """Show recent session memories."""
    result = _get("/memory/recent")
    if isinstance(result, list):
        if not result:
            print("No session memories yet.")
            return
        for m in result:
            date = m.get("date", "unknown")
            summary = m.get("summary", m.get("decisions", ["no summary"])[0] if isinstance(m.get("decisions"), list) else "no summary")
            print(f"  {date}: {summary}")
    elif isinstance(result, dict) and result.get("error"):
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)


def cmd_projects() -> None:
    """Check on all known git projects."""
    result = _get("/projects")
    if not result.get("ok"):
        print(f"Error: {result.get('error')}", file=sys.stderr)
        sys.exit(1)
    if not result.get("projects"):
        print("No projects found in ~/work.")
        return
    for p in result["projects"]:
        status = p.get("status", {})
        branch = status.get("branch", "?")
        staged = status.get("staged", 0)
        unstaged = status.get("unstaged", 0)
        untracked = status.get("untracked", 0)
        dirty = " ⚠" if status.get("dirty") else ""
        parts = []
        if staged:
            parts.append(f"{staged} staged")
        if unstaged:
            parts.append(f"{unstaged} unstaged")
        if untracked:
            parts.append(f"{untracked} untracked")
        detail = ", ".join(parts) if parts else "clean"
        print(f"  {p['name']:20s} {branch:15s} {detail}{dirty}")


def cmd_tool(tool_name: str, args_json: str = "{}") -> None:
    """Call a local tool: read_file, git_status, git_log, list_directory."""
    if not tool_name:
        print("vex: tool name required. e.g. vex tool git_status '{\"repo_path\": \"~/work/myproject\"}'")
        sys.exit(1)
    try:
        args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError:
        print("vex: args must be valid JSON", file=sys.stderr)
        sys.exit(1)
    result = _post("/tools", {"tool": tool_name, "args": args})
    if result.get("ok"):
        print(json.dumps(result, indent=2))
    else:
        print(f"Error: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


def cmd_check() -> None:
    """Full check: status + introspection + projects."""
    cmd_status()
    print()
    cmd_introspect()
    print("\nProjects:")
    cmd_projects()


def cmd_seed() -> None:
    """Show seed identity."""
    seed = _get("/seed")
    print(seed)


def cmd_self() -> None:
    """Show self-model capabilities."""
    model = _get("/self")
    if isinstance(model, dict):
        caps = model.get("capabilities", {})
        if not caps:
            print("No capabilities tracked.")
            return
        for name, cap in sorted(caps.items()):
            skill = cap.get("estimated_skill", 0)
            conf = cap.get("confidence", 0)
            obs = cap.get("n_observations", 0)
            bar = "█" * int(skill * 20) + "░" * (20 - int(skill * 20))
            print(f"  {name:25s} {bar} {skill:.2f} ({obs} obs, {conf:.0%} conf)")
    else:
        print(model)


USAGE = """vex — talk to the Vex Daemon

  vex status       Show pulse, coherence, uptime
  vex check        Full check: status + introspection + projects
  vex projects     Check on all known git repos
  vex diary ...    Write a thought to the diary
  vex dream        Force a dream/reflection cycle
  vex introspect   Run metacognitive check
  vex memory       Show recent session memories
  vex seed         Show seed identity
  vex self         Show capability scores
  vex tool <name>  Call a tool (read_file, git_status, git_log, etc.)
  vex health       Raw health JSON"""


def main() -> None:
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if cmd == "status":
        cmd_status()
    elif cmd == "check":
        cmd_check()
    elif cmd == "health":
        print(json.dumps(_get("/health"), indent=2))
    elif cmd == "diary":
        cmd_diary(" ".join(sys.argv[2:]))
    elif cmd == "dream":
        cmd_dream()
    elif cmd == "introspect":
        cmd_introspect()
    elif cmd == "memory":
        cmd_memory()
    elif cmd == "projects":
        cmd_projects()
    elif cmd == "tool":
        cmd_tool(sys.argv[2] if len(sys.argv) > 2 else "", " ".join(sys.argv[3:]) if len(sys.argv) > 3 else "{}")
    elif cmd == "seed":
        cmd_seed()
    elif cmd == "self":
        cmd_self()
    elif cmd in ("help", "-h", "--help"):
        print(USAGE)
    else:
        print(f"vex: unknown command '{cmd}'", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
