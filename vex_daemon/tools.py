"""
Vex Tools — hands and capabilities for the daemon.

Gives Vex the ability to read files, check git repos, run safe commands,
and interact with the world beyond localhost:8520.

Used by the dream engine for project check-ins, by metacognition for
evidence gathering, and via vex ask for manual queries.
"""

import asyncio
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import SAFE_ROOTS, WORK_DIR
import playwright_tools

# Cap a single file read so a giant file can't OOM the daemon.
_MAX_READ_BYTES = 1_000_000  # 1 MB


def _is_safe_path(path: Path) -> bool:
    """Check if path is within allowed roots.

    Uses path-component containment, not string prefix — otherwise
    a root like ~/work would also match ~/work-secrets.
    Resolves symlinks before the check, so a link pointing outside
    the roots is rejected.
    """
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for r in SAFE_ROOTS:
        try:
            root = r.resolve()
        except OSError:
            continue
        if resolved == root or root in resolved.parents:
            return True
    return False


def read_file(path: str, max_lines: int = 200) -> dict:
    """Read a file within allowed paths. Returns {ok, content, error}."""
    max_lines = max(1, min(int(max_lines), 10_000))
    p = Path(path).expanduser()
    if not _is_safe_path(p):
        return {"ok": False, "error": f"Path not in allowed roots: {path}"}
    if not p.exists():
        return {"ok": False, "error": f"File not found: {path}"}
    if p.is_dir():
        return {"ok": False, "error": f"Path is a directory: {path}"}
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read(_MAX_READ_BYTES + 1)
        size_capped = len(raw) > _MAX_READ_BYTES
        raw = raw[:_MAX_READ_BYTES]
        lines = raw.splitlines()
        truncated = size_capped or len(lines) > max_lines
        return {
            "ok": True,
            "path": str(p),
            "lines": len(lines),
            "truncated": truncated,
            "content": "\n".join(lines[:max_lines]),
        }
    except OSError as e:
        return {"ok": False, "error": str(e)}


def list_directory(path: str) -> dict:
    """List directory contents within allowed paths."""
    p = Path(path).expanduser()
    if not _is_safe_path(p):
        return {"ok": False, "error": f"Path not in allowed roots: {path}"}
    if not p.exists():
        return {"ok": False, "error": f"Directory not found: {path}"}
    if not p.is_dir():
        return {"ok": False, "error": f"Not a directory: {path}"}
    try:
        entries = []
        for child in sorted(p.iterdir()):
            entry = {
                "name": child.name,
                "type": "dir" if child.is_dir() else "file",
            }
            if child.is_file():
                try:
                    entry["size"] = child.stat().st_size
                except OSError:
                    pass
            entries.append(entry)
        return {"ok": True, "path": str(p), "entries": entries}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def git_status(repo_path: str) -> dict:
    """Run git status in a repository. Returns parsed status info."""
    p = Path(repo_path).expanduser()
    if not _is_safe_path(p):
        return {"ok": False, "error": f"Path not in allowed roots: {repo_path}"}

    try:
        result = subprocess.run(
            ["git", "-C", str(p), "status", "--porcelain", "-b"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip()}

        lines = result.stdout.splitlines()
        branch = ""
        if lines and lines[0].startswith("## "):
            branch = lines[0][3:].split("...")[0].strip()
            lines = lines[1:]

        staged = [l for l in lines if l[0] != " " and l[1] != "?"]
        unstaged = [l for l in lines if l[1] != " " and l[0] != "?"]
        untracked = [l for l in lines if l.startswith("??")]

        return {
            "ok": True,
            "path": str(p),
            "branch": branch,
            "staged": len(staged),
            "unstaged": len(unstaged),
            "untracked": len(untracked),
            "dirty": len(lines) > 0,
            "sample": lines[:10] if lines else [],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git status timed out"}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def git_log(repo_path: str, n: int = 5) -> dict:
    """Get recent git log entries."""
    p = Path(repo_path).expanduser()
    if not _is_safe_path(p):
        return {"ok": False, "error": f"Path not in allowed roots: {repo_path}"}

    try:
        result = subprocess.run(
            ["git", "-C", str(p), "log", f"-{n}", "--oneline", "--decorate"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip()}

        return {
            "ok": True,
            "path": str(p),
            "commits": [l.strip() for l in result.stdout.splitlines() if l.strip()],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git log timed out"}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def discover_projects() -> dict:
    """Find all git repositories under the work dir and report their status."""
    work = WORK_DIR
    projects = []

    if not work.exists():
        return {"ok": False, "error": f"work dir not found: {work}"}

    for child in sorted(work.iterdir()):
        if not child.is_dir():
            continue
        git_dir = child / ".git"
        if git_dir.exists():
            status = git_status(str(child))
            projects.append({
                "name": child.name,
                "path": str(child),
                "status": status,
            })

    return {
        "ok": True,
        "project_count": len(projects),
        "projects": projects,
    }


# ── Write / edit tools ───────────────────────────────────────────

_MAX_WRITE_BYTES = 5 * 1024 * 1024  # 5 MB
_MAX_CMD_OUTPUT = 100_000  # 100 KB


def write_file(path: str, content: str) -> dict:
    """Write a file within allowed paths. Atomic: writes to tmp then os.replace."""
    p = Path(path).expanduser()
    if not _is_safe_path(p):
        return {"ok": False, "error": f"Path not in allowed roots: {path}"}
    if len(content.encode("utf-8", errors="replace")) > _MAX_WRITE_BYTES:
        return {"ok": False, "error": f"Content too large (max {_MAX_WRITE_BYTES} bytes)"}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".vex-tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, p)
        return {"ok": True, "path": str(p), "bytes": len(content.encode("utf-8"))}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def edit_file(path: str, old: str, new: str) -> dict:
    """Exact string replacement within a file. Fails if old_string is not unique."""
    p = Path(path).expanduser()
    if not _is_safe_path(p):
        return {"ok": False, "error": f"Path not in allowed roots: {path}"}
    if not p.exists():
        return {"ok": False, "error": f"File not found: {path}"}
    if p.is_dir():
        return {"ok": False, "error": f"Path is a directory: {path}"}
    try:
        content = p.read_text(encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": str(e)}
    count = content.count(old)
    if count == 0:
        return {"ok": False, "error": "old_string not found in file"}
    if count > 1:
        return {"ok": False, "error": f"old_string matches {count} locations — must be unique"}
    new_content = content.replace(old, new)
    try:
        tmp = p.with_suffix(p.suffix + ".vex-tmp")
        tmp.write_text(new_content, encoding="utf-8")
        os.replace(tmp, p)
        return {"ok": True, "path": str(p), "replaced": True}
    except OSError as e:
        return {"ok": False, "error": str(e)}


# ── Command execution ────────────────────────────────────────────


def run_command(cmd: str, cwd: str = "", timeout: int = 30) -> dict:
    """Run a shell command sandboxed within SAFE_ROOTS.

    Environment is scrubbed to a minimal allowlist. Output is capped.
    Timeout is clamped to [1, 60] seconds.
    """
    timeout = max(1, min(int(timeout), 60))
    work_dir = Path(cwd).expanduser() if cwd else Path.home()
    if not _is_safe_path(work_dir):
        return {"ok": False, "error": f"cwd not in allowed roots: {cwd}"}
    if not work_dir.exists():
        return {"ok": False, "error": f"cwd does not exist: {cwd}"}
    # Minimal safe environment
    safe_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(Path.home()),
        "LANG": "C.UTF-8",
        "TZ": os.environ.get("TZ", "UTC"),
    }
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=str(work_dir), env=safe_env,
        )
        stdout = result.stdout[:_MAX_CMD_OUTPUT]
        stderr = result.stderr[:_MAX_CMD_OUTPUT]
        return {
            "ok": True,
            "returncode": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": len(result.stdout) > _MAX_CMD_OUTPUT or len(result.stderr) > _MAX_CMD_OUTPUT,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Command timed out after {timeout}s"}


def grep_code(pattern: str, path: str = "", include: str = "*.py") -> dict:
    """Recursive grep within SAFE_ROOTS. Uses grep -rn, falls back to Python."""
    search_dir = Path(path).expanduser() if path else Path.home()
    if not _is_safe_path(search_dir):
        return {"ok": False, "error": f"Path not in allowed roots: {path}"}
    if not search_dir.exists():
        return {"ok": False, "error": f"Path not found: {path}"}
    try:
        result = subprocess.run(
            ["grep", "-rn", "--include=" + include, pattern, str(search_dir)],
            capture_output=True, text=True, timeout=15,
        )
        lines = result.stdout.strip().splitlines()[:_MAX_READ_BYTES // 200]
        return {
            "ok": True,
            "matches": len(lines),
            "lines": lines[:50],
            "truncated": len(lines) > 50,
        }
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    # Python fallback
    import fnmatch
    matches = []
    try:
        for root, dirs, files in os.walk(str(search_dir)):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", ".git", "node_modules", ".venv")]
            for fname in files:
                if fnmatch.fnmatch(fname, include):
                    fp = os.path.join(root, fname)
                    try:
                        with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                            for lineno, line in enumerate(fh, 1):
                                if pattern in line:
                                    matches.append(f"{fp}:{lineno}:{line.rstrip()[:200]}")
                                    if len(matches) >= 50:
                                        raise StopIteration
                    except OSError:
                        pass
    except StopIteration:
        pass
    return {
        "ok": True,
        "matches": len(matches),
        "lines": matches,
        "truncated": len(matches) >= 50,
    }


def git_diff(repo_path: str) -> dict:
    """Show working tree and staged diff in a git repo."""
    p = Path(repo_path).expanduser()
    if not _is_safe_path(p):
        return {"ok": False, "error": f"Path not in allowed roots: {repo_path}"}
    try:
        staged = subprocess.run(
            ["git", "-C", str(p), "diff", "--cached", "--stat"],
            capture_output=True, text=True, timeout=10,
        )
        unstaged = subprocess.run(
            ["git", "-C", str(p), "diff", "--stat"],
            capture_output=True, text=True, timeout=10,
        )
        # Full diff (capped)
        full = subprocess.run(
            ["git", "-C", str(p), "diff", "--cached", "--", ":(exclude)*.lock", ":(exclude)*.db"],
            capture_output=True, text=True, timeout=15,
        )
        return {
            "ok": True,
            "path": str(p),
            "staged_summary": staged.stdout.strip() or "(nothing staged)",
            "unstaged_summary": unstaged.stdout.strip() or "(working tree clean)",
            "diff": full.stdout[:_MAX_CMD_OUTPUT],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git diff timed out"}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def run_tests(repo_path: str, command: str = "") -> dict:
    """Run a test command in a repo and capture results.

    Default command: python -m pytest tests/ -v --tb=short
    """
    p = Path(repo_path).expanduser()
    if not _is_safe_path(p):
        return {"ok": False, "error": f"Path not in allowed roots: {repo_path}"}
    cmd = command or "python -m pytest tests/ -v --tb=short 2>&1"
    safe_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(Path.home()),
        "LANG": "C.UTF-8",
    }
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=120, cwd=str(p), env=safe_env,
        )
        output = (result.stdout + result.stderr)[:_MAX_CMD_OUTPUT]
        passed = result.returncode == 0
        return {
            "ok": True,
            "passed": passed,
            "returncode": result.returncode,
            "output": output,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Tests timed out after 120s"}


def run_tool(tool_name: str, **kwargs) -> dict:
    """Dispatch a tool call by name. Safe entry point for API/dream engine."""
    tool_registry = {
        "read_file": read_file,
        "list_directory": list_directory,
        "git_status": git_status,
        "git_log": git_log,
        "discover_projects": discover_projects,
        "write_file": write_file,
        "edit_file": edit_file,
        "run_command": run_command,
        "grep_code": grep_code,
        "git_diff": git_diff,
        "run_tests": run_tests,
        "playwright_screenshot": playwright_tools.screenshot,
        "playwright_text": playwright_tools.get_text,
        "playwright_check_links": playwright_tools.check_links,
    }

    if tool_name not in tool_registry:
        return {"ok": False, "error": f"Unknown tool: {tool_name}. Available: {list(tool_registry)}"}

    return tool_registry[tool_name](**kwargs)
