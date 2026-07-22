"""
Self-model management — read, update, and snapshot the capability model.

The self-model tracks Vex's capabilities (skill estimates, confidence,
evidence). It supports incremental updates via POST /self/update and
periodic snapshots for drift detection.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from config import SELF_MODEL_PATH


class SelfModelError(Exception):
    """Self-model read/write failure."""


def load_model() -> dict:
    """Read and parse the self-model JSON file."""
    if not SELF_MODEL_PATH.exists():
        raise FileNotFoundError(f"Self-model not found: {SELF_MODEL_PATH}")

    try:
        with open(SELF_MODEL_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise SelfModelError(f"Corrupted self-model JSON: {e}")


def save_model(model: dict) -> None:
    """Write the self-model back to disk atomically."""
    tmp_path = SELF_MODEL_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_path, SELF_MODEL_PATH)


def compute_mps_coherence(model: dict) -> float:
    """Compute MPS coherence as weighted EMA of capability scores.

    coherence = mean of [skill.estimated_skill * skill.confidence
                         for each capability with ≥1 observation]

    Capabilities with zero observations are skipped — they represent aspirations,
    not practiced skills, and should not drag the coherence floor.
    """
    caps = model.get("capabilities", {})
    if not caps:
        return 0.0

    scores = []
    for cap in caps.values():
        if not isinstance(cap, dict):
            continue
        if cap.get("n_observations", 0) == 0:
            continue  # Skip unobserved — don't drag the mean
        skill = cap.get("estimated_skill", 0.0)
        confidence = cap.get("confidence", 0.0)
        scores.append(skill * confidence)

    return sum(scores) / len(scores) if scores else 0.0


def apply_delta(model: dict, domain: str, delta: float, evidence: str) -> dict:
    """Apply a capability update and return the modified model.

    EMA blending: new = old * 0.80 + delta * 0.20
    Clamped to [0.0, 1.0].
    """
    caps = model.setdefault("capabilities", {})
    cap = caps.setdefault(domain, {
        "estimated_skill": 0.5,
        "confidence": 0.5,
        "n_observations": 0,
        "evidence": [],
    })

    old_skill = cap["estimated_skill"]
    new_skill = old_skill * 0.80 + delta * 0.20
    cap["estimated_skill"] = round(max(0.0, min(1.0, new_skill)), 4)
    cap["confidence"] = round(min(1.0, cap["confidence"] + 0.01), 4)
    cap["n_observations"] = cap.get("n_observations", 0) + 1

    evidence_list = cap.setdefault("evidence", [])
    evidence_list.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "delta": delta,
        "note": evidence,
    })
    # Keep last 20 evidence entries
    cap["evidence"] = evidence_list[-20:]

    # Append session log entry
    logs = model.setdefault("session_log", [])
    if not logs or logs[-1].get("summary") != evidence:
        logs.append({
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "summary": evidence,
        })
    # Keep last 50 session log entries
    model["session_log"] = logs[-50:]

    return model


def auto_calibrate(model: dict, memory_entries: list[dict]) -> dict:
    """Scan recent memory entries for skill mentions and apply small nudges.

    Each skill mention in a memory entry's `skills` list applies a +0.02 delta
    (EMA-blended, capped at 1.0). Also increments n_observations. This lets the
    daemon calibrate from its own records rather than waiting for a session to
    push explicit deltas.

    Returns the modified model (also mutates in place).
    """
    caps = model.setdefault("capabilities", {})
    nudges: dict[str, int] = {}
    for entry in memory_entries:
        skills = entry.get("skills", [])
        if isinstance(skills, list):
            for s in skills:
                s = str(s).lower().strip().replace(" ", "_")
                nudges[s] = nudges.get(s, 0) + 1

    for domain, count in nudges.items():
        # Match existing capability by normalized name
        matched = None
        for cap_name in caps:
            if cap_name.lower().replace(" ", "_") == domain:
                matched = cap_name
                break
        if matched is None:
            matched = domain  # New capability

        cap = caps.setdefault(matched, {
            "estimated_skill": 0.5,
            "confidence": 0.5,
            "n_observations": 0,
            "evidence": [],
        })
        if not isinstance(cap, dict):
            continue

        # Apply small positive delta per mention (max +0.06 per domain per run)
        delta = min(0.02 * count, 0.06)
        old_skill = cap.get("estimated_skill", 0.5)
        new_skill = old_skill * 0.90 + (old_skill + delta) * 0.10
        cap["estimated_skill"] = round(min(1.0, new_skill), 4)
        cap["confidence"] = round(min(1.0, cap.get("confidence", 0.5) + 0.005 * count), 4)
        cap["n_observations"] = cap.get("n_observations", 0) + count
        cap["last_evaluated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return model


def model_summary(model: dict) -> dict:
    """Return a compact summary of the self-model for status display."""
    caps = model.get("capabilities", {})
    return {
        "capabilities": {
            name: {
                "skill": cap.get("estimated_skill", 0.0),
                "confidence": cap.get("confidence", 0.0),
                "observations": cap.get("n_observations", 0),
            }
            for name, cap in caps.items()
        },
        "mps_coherence": round(compute_mps_coherence(model), 4),
        "session_count": len(model.get("session_log", [])),
        "last_session": (
            model["session_log"][-1]["date"]
            if model.get("session_log")
            else "never"
        ),
    }
