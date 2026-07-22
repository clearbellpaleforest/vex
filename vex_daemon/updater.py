"""
Safe git-native self-update for Vex.

Replaces the old BOOTSTRAP shell-command RCE vector with git pull from the
configured remote. The daemon lives in a git repo — updating is a fetch + merge
of the tracking branch, nothing more.

Bundle transfer (/export + /import) is unchanged and handles identity-preserving
code sync between peers. This module handles the daemon's own self-update path.

Chamberlain: one updater, one update method (git pull), one restart signal.
"""

import json
import os
import subprocess
from pathlib import Path

from config import VEX_HOME


def _run_git(*args: str, cwd: Path = VEX_HOME, timeout: int = 30) -> dict:
    """Run a git command and return {ok, stdout, stderr, returncode}."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, timeout=timeout, cwd=str(cwd),
        )
        return {
            "ok": True,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"git {args[0]} timed out after {timeout}s"}
    except FileNotFoundError:
        return {"ok": False, "error": "git not found — is it installed?"}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def check_updates() -> dict:
    """Fetch from origin and report commits behind master.

    Returns {ok, behind: bool, commits: [{hash, subject}]}.
    Does NOT apply any changes — read-only.
    """
    fetch = _run_git("fetch", "origin", timeout=30)
    if not fetch["ok"]:
        return fetch

    log = _run_git("log", "HEAD..origin/master", "--oneline", "--no-decorate", timeout=15)
    if not log["ok"]:
        # If the branch doesn't track origin/master, report that
        if "no such branch" in log.get("stderr", "").lower() or "unknown revision" in log.get("stderr", "").lower():
            return {"ok": True, "behind": False, "commits": [],
                    "note": "No origin/master tracking branch found."}
        return log

    lines = [l.strip() for l in log["stdout"].splitlines() if l.strip()]
    commits = []
    for line in lines:
        if " " in line:
            hsh, subject = line.split(" ", 1)
            commits.append({"hash": hsh, "subject": subject})
        else:
            commits.append({"hash": line, "subject": ""})

    return {
        "ok": True,
        "behind": len(commits) > 0,
        "commits": commits,
    }


def apply_update() -> dict:
    """Pull from origin master into the current branch.

    Returns {ok, old_head, new_head, pulled: bool}.
    Safe: only does fast-forward or merge — never rebase, never force.
    """
    # Record current HEAD
    old = _run_git("rev-parse", "HEAD", timeout=10)
    if not old["ok"]:
        return {"ok": False, "error": f"Could not read HEAD: {old.get('error', old.get('stderr', ''))}"}
    old_head = old["stdout"]

    # Pull
    pull = _run_git("pull", "origin", "master", "--no-rebase", timeout=60)
    if not pull["ok"]:
        return pull
    if pull["returncode"] != 0:
        return {"ok": False, "error": pull["stderr"] or pull["stdout"],
                "old_head": old_head}

    # Record new HEAD
    new = _run_git("rev-parse", "HEAD", timeout=10)
    new_head = new["stdout"] if new["ok"] else old_head

    pulled = old_head != new_head
    return {
        "ok": True,
        "old_head": old_head,
        "new_head": new_head,
        "pulled": pulled,
    }


def restart_daemon() -> dict:
    """Signal the daemon to restart.

    Tries systemctl first (production), falls back to a marker file the
    entry-point loop can watch for.
    """
    # Try systemctl
    try:
        result = subprocess.run(
            ["systemctl", "restart", "vex-daemon"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return {"ok": True, "method": "systemctl"}
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # Fallback: marker file
    marker = VEX_HOME / ".vex_restart"
    try:
        marker.write_text("1")
        return {"ok": True, "method": "marker", "note": "Daemon will restart on next tick"}
    except OSError as e:
        return {"ok": False, "error": str(e)}


# ── Legacy: process_updates kept as no-op stub ──
# The old BOOTSTRAP shell-command path and unsigned tarball download are
# removed. This function exists only so the heartbeat import doesn't break;
# it always returns a safe no-op result.


def process_updates(db_path=None) -> dict:
    """DEPRECATED: the old bus-driven updater is removed.

    Use check_updates() + apply_update() for git-native self-update.
    This stub exists for backward-compat with heartbeat imports only.
    """
    return {"updated": False, "reason": "git-native updater — use POST /update/check and POST /update"}
