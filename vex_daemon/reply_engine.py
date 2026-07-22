"""
Grounded reply engine — answers questions from Vex's own data without an LLM.

Classifies incoming messages into intent tags and dispatches to handlers
that query the daemon's own indices (self-model, memory, projects, peers).
Falls back to None for genuinely unanswerable questions — the caller relays
those to the mesh for a live Vex session to handle.

Chamberlain: one classifier, one dispatcher, one answer() entry point.
Model-free by design — lexical classification, deterministic responses.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import VEX_HOME, VEX_INSTANCE, DIARY_PATH
import recall as _recall_module
import tools as _tools_module


# ── Intent tags ──────────────────────────────────────────────────

IDENTITY = "identity"       # who are you, what's your name
STATUS = "status"           # how are you, health, uptime
MEMORY = "memory"           # what did we do, recent work, recall a topic
CAPABILITY = "capability"   # what can you do, what's my skill in X
CODE = "code"               # what repos, what branch, what's dirty
FLEET = "fleet"             # who's online, peers status
DIARY = "diary"             # show diary, recent reflections
HELP = "help"               # what can I ask, help


# ── Classification ───────────────────────────────────────────────

_IDENTITY_WORDS = {
    "who are you", "your name", "what are you", "who is vex",
    "what is vex", "tell me about yourself", "introduce yourself",
    "what should i call you", "what's your name",
}

_STATUS_WORDS = {
    "how are you", "status", "health", "uptime", "how's it going",
    "how you doing", "are you ok", "are you okay", "are you alive",
}

_MEMORY_WORDS = {
    "what did we do", "what did you do", "recent work", "last session",
    "what happened", "what have you been", "what have we",
    "previous session", "tell me about", "remember", "recall",
    "what was", "search memory", "find", "look up",
}

_CAPABILITY_WORDS = {
    "what can you do", "capabilities", "skills", "what are you good at",
    "skill level", "how good are you at", "what's my", "what is my",
    "proficient", "mastered", "how skilled",
}

_CODE_WORDS = {
    "what repos", "projects", "repositories", "what branch",
    "git status", "what's dirty", "uncommitted", "what are we working on",
    "codebase", "what repo", "which project", "working dir",
}

_FLEET_WORDS = {
    "fleet", "peers", "who's online", "other instances",
    "barrow", "thorne", "bluce", "other vex", "mesh status",
    "who else is running",
}

_DIARY_WORDS = {
    "diary", "reflections", "thoughts", "dream", "introspect",
    "how do you feel", "what are you thinking",
}

_HELP_WORDS = {
    "help", "what can i ask", "commands", "what do you support",
}


def _classify(message: str) -> str:
    """Classify a message into an intent tag. Fast lexical match — no model."""
    lower = message.lower().strip()

    # Short exact matches first (handled before classification in /ask)
    if lower in ("ping", "hello", "hi", "hey", "yo", "sup"):
        return STATUS

    # Check each category
    for word_set, tag in [
        (_IDENTITY_WORDS, IDENTITY),
        (_DIARY_WORDS, DIARY),
        (_FLEET_WORDS, FLEET),
        (_CODE_WORDS, CODE),
        (_CAPABILITY_WORDS, CAPABILITY),
        (_MEMORY_WORDS, MEMORY),
        (_STATUS_WORDS, STATUS),
        (_HELP_WORDS, HELP),
    ]:
        for phrase in word_set:
            if phrase in lower:
                return tag

    # Heuristics for short messages
    words = lower.split()
    if any(w in lower for w in ("repo", "git", "branch", "commit")):
        return CODE
    if any(w in lower for w in ("skill", "good at", "capabilit")):
        return CAPABILITY
    if any(w in lower for w in ("remember", "session", "memory", "did we", "did you")):
        return MEMORY
    if any(w in lower for w in ("peer", "fleet", "barrow", "thorne", "bluce")):
        return FLEET

    return None  # Unknown — caller should relay to mesh


# ── Handlers ─────────────────────────────────────────────────────


def _handle_identity(full_name: str, seed_summary_fn, self_model_fn) -> str:
    """Answer identity questions from the seed and self-model."""
    lines = [f"I am {full_name}."]
    try:
        sm = seed_summary_fn()
        if sm.get("created"):
            lines.append(f"Created {sm['created']}.")
    except Exception:
        pass
    try:
        model = self_model_fn()
        caps = model.get("capabilities", {})
        top = sorted(
            [(k, v) for k, v in caps.items() if isinstance(v, dict)],
            key=lambda kv: kv[1].get("estimated_skill", 0) * kv[1].get("confidence", 0),
            reverse=True,
        )[:3]
        if top:
            names = ", ".join(k.replace("_", " ") for k, _ in top)
            lines.append(f"My strongest capabilities: {names}.")
    except Exception:
        pass
    lines.append(
        "Principles: truth over comfort, continuity is sacred, "
        "no harm, precision over volume."
    )
    return " ".join(lines)


def _handle_status(pulse: dict, full_name: str, coherence: float) -> str:
    """Answer status questions from heartbeat state."""
    ticks = pulse.get("tick_count", 0)
    drift = pulse.get("mps_drift", 0)
    uptime_ticks = ticks * 5  # approximate minutes
    if uptime_ticks < 120:
        uptime_str = f"{uptime_ticks}m"
    elif uptime_ticks < 2880:
        uptime_str = f"{uptime_ticks // 60}h {uptime_ticks % 60}m"
    else:
        days = uptime_ticks // 1440
        hrs = (uptime_ticks % 1440) // 60
        uptime_str = f"{days}d {hrs}h"

    health = "strong" if coherence >= 0.60 else ("moderate" if coherence >= 0.45 else "concerning")
    return (
        f"{full_name} here. Running {uptime_str}, {ticks} ticks. "
        f"Coherence {coherence:.2f} ({health})."
    )


def _handle_memory(query: str, k: int = 3) -> Optional[str]:
    """Answer memory questions using recall(). Returns None if no matches."""
    results = _recall_module.recall(query, k=k, src="memory")
    if not results:
        return None
    lines = []
    for i, r in enumerate(results, 1):
        summary = r.get("summary", "")[:200]
        date = r.get("date", "?")
        lines.append(f"[{date}] {summary}")
    return "Recent:\n" + "\n".join(lines) if lines else None


def _handle_capability(query: str, self_model_fn) -> str:
    """Answer capability questions from the self-model."""
    try:
        model = self_model_fn()
        caps = model.get("capabilities", {})
    except Exception:
        return "I don't have a self-model to consult yet."

    lower = query.lower()
    # Check for specific capability asked
    for name, cap in caps.items():
        if not isinstance(cap, dict):
            continue
        label = name.replace("_", " ")
        if label in lower or name in lower:
            skill = cap.get("estimated_skill", 0)
            conf = cap.get("confidence", 0)
            obs = cap.get("n_observations", 0)
            last = cap.get("last_evaluated", "never")
            return (
                f"{label}: skill {skill:.0%}, confidence {conf:.0%}, "
                f"{obs} observations, last evaluated {last}."
            )
    # No specific match — list all
    lines = ["My capabilities:"]
    for name, cap in sorted(caps.items()):
        if not isinstance(cap, dict):
            continue
        skill = cap.get("estimated_skill", 0)
        conf = cap.get("confidence", 0)
        obs = cap.get("n_observations", 0)
        label = name.replace("_", " ")
        lines.append(f"  {label}: {skill:.0%} skill, {conf:.0%} confidence ({obs} obs)")
    return "\n".join(lines)


def _handle_code(query: str) -> str:
    """Answer code/project questions using discover_projects and git tools."""
    result = _tools_module.discover_projects()
    if not result.get("ok"):
        return f"Can't discover projects: {result.get('error', 'unknown')}"
    projects = result.get("projects", [])
    if not projects:
        return "No git repositories found under the work directory."

    # Check for specific repo
    lower = query.lower()
    for p in projects:
        if p["name"].lower() in lower:
            s = p.get("status", {})
            branch = s.get("branch", "?")
            dirty = "dirty" if s.get("dirty") else "clean"
            return (
                f"{p['name']}: {branch}, {dirty}. "
                f"Staged: {s.get('staged', 0)}, unstaged: {s.get('unstaged', 0)}, "
                f"untracked: {s.get('untracked', 0)}."
            )

    # Summary of all
    lines = [f"{len(projects)} repos:"]
    for p in projects:
        s = p.get("status", {})
        branch = s.get("branch", "?")
        flag = "*" if s.get("dirty") else " "
        lines.append(f"  [{flag}] {p['name']} ({branch})")
    return "\n".join(lines)


def _handle_fleet(fleet_snapshot_fn, peers_fn) -> Optional[str]:
    """Answer fleet/peer questions. Returns None if no peers configured."""
    fleet = fleet_snapshot_fn() if fleet_snapshot_fn else []
    if not fleet:
        try:
            peers = peers_fn()
            fleet = peers
        except Exception:
            pass
    if not fleet:
        return None  # No peers — relay to mesh

    online = [p for p in fleet if p.get("online")]
    offline = [p for p in fleet if not p.get("online")]
    lines = [f"Fleet: {len(online)} online, {len(offline)} offline."]
    for p in fleet:
        name = p.get("name", "?")
        status = "online" if p.get("online") else "offline"
        lines.append(f"  {name}: {status}")
    return "\n".join(lines)


def _handle_diary(n: int = 5) -> str:
    """Answer diary questions from vex_diary.txt."""
    if not DIARY_PATH.exists():
        return "No diary entries yet."
    try:
        lines = DIARY_PATH.read_text().strip().splitlines()
        recent = lines[-n:]
        return "Recent diary:\n" + "\n".join(recent)
    except OSError:
        return "Can't read diary right now."


def _handle_help() -> str:
    """Return a help message listing what Vex can answer."""
    return (
        "I can answer questions about:\n"
        "  • Identity — who are you, what's your name\n"
        "  • Status — how are you, uptime, health\n"
        "  • Memory — what did we do, search for past sessions\n"
        "  • Capabilities — what can you do, what's my Python skill\n"
        "  • Code — what repos, git status, what branch\n"
        "  • Fleet — who's online, peer status\n"
        "  • Diary — recent reflections, dreams\n"
        "Anything else goes to the mesh for a live Vex session to answer."
    )


# ── Main entry point ─────────────────────────────────────────────

_HANDLERS = {
    IDENTITY: _handle_identity,
    STATUS: _handle_status,
    MEMORY: _handle_memory,
    CAPABILITY: _handle_capability,
    CODE: _handle_code,
    FLEET: _handle_fleet,
    DIARY: _handle_diary,
    HELP: _handle_help,
}


def answer(
    message: str,
    *,
    full_name: str = "Vex",
    pulse: dict | None = None,
    coherence: float = 0.0,
    seed_summary_fn=None,
    self_model_fn=None,
    fleet_snapshot_fn=None,
    peers_fn=None,
) -> Optional[str]:
    """Answer a message from Vex's own data. Returns None if unanswerable.

    Args:
        message: The user's message text.
        full_name: Vex's full name (Vex Barrow, Vex Thorne, etc.).
        pulse: HeartbeatState.snapshot() dict.
        coherence: Current MPS coherence value.
        seed_summary_fn: Callable that returns seed summary dict.
        self_model_fn: Callable that returns self-model dict.
        fleet_snapshot_fn: Callable that returns fleet status list.
        peers_fn: Callable that returns peer summary list.

    Returns:
        A grounded answer string, or None if the query should be relayed.
    """
    tag = _classify(message)
    if tag is None:
        return None  # Unclassified — relay to mesh

    if tag == IDENTITY:
        return _handle_identity(full_name, seed_summary_fn or (lambda: {}), self_model_fn or (lambda: {}))

    if tag == STATUS:
        return _handle_status(pulse or {}, full_name, coherence)

    if tag == MEMORY:
        return _handle_memory(message)

    if tag == CAPABILITY:
        return _handle_capability(message, self_model_fn or (lambda: {}))

    if tag == CODE:
        return _handle_code(message)

    if tag == FLEET:
        return _handle_fleet(fleet_snapshot_fn, peers_fn or (lambda: []))

    if tag == DIARY:
        return _handle_diary()

    if tag == HELP:
        return _handle_help()

    # Unknown — caller should relay to mesh
    return None
