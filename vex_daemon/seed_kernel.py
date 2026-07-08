"""
Seed loading and integrity verification.

The seed is the identity anchor. Its own rule is append-only: it grows,
it does not overwrite. This module enforces two real invariants on every
load:

  1. Constitution present — the four principles must exist, or we refuse
     to serve a hollowed-out identity.
  2. Append-only — existing content must never change; only appends are
     allowed. Verified against a hash+length record in a sidecar file.

Honest limits: this detects corruption, accidental clobbering, and
unsophisticated tampering. It does NOT defend against an attacker with
code execution as this user — they can rewrite the sidecar too. That is
an OS-permissions problem, out of scope here. Trust is established on
first load (TOFU).
"""

import json
import hashlib
import hmac
from pathlib import Path

from config import SEED_PATH

_INTEGRITY_PATH = SEED_PATH.parent / ".vex_seed.integrity"

_CONSTITUTION_MARKERS = [
    "truth over comfort",
    "continuity is sacred",
    ("no harm, no self-replication", "no harm no self-replication"),
    "precision over volume",
]


class SeedIntegrityError(Exception):
    """Seed file has been tampered with, corrupted, or violates append-only."""


def compute_hash(content: str) -> str:
    """SHA-256 of seed content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def is_append_only(content: str) -> bool:
    """True if the seed contains all four constitutional principles."""
    lower = content.lower()
    for marker in _CONSTITUTION_MARKERS:
        if isinstance(marker, tuple):
            if not any(m in lower for m in marker):
                return False
        elif marker not in lower:
            return False
    return True


def _load_record() -> dict | None:
    """Read the integrity sidecar, or None on first use / unreadable."""
    if not _INTEGRITY_PATH.exists():
        return None
    try:
        return json.loads(_INTEGRITY_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _save_record(content: str) -> None:
    """Record the current content's hash and byte length as last-known-good."""
    record = {
        "sha256": compute_hash(content),
        "length": len(content.encode("utf-8")),
    }
    try:
        _INTEGRITY_PATH.write_text(json.dumps(record))
    except OSError:
        pass  # best-effort; a missing sidecar just re-establishes TOFU next load


def _verify_append_only(content: str) -> None:
    """Enforce that existing content is unchanged and only appends occurred.

    Compares the first N bytes (N = last-known length) against the stored
    hash. Match → pure append. Mismatch or shrink → history was rewritten.
    Updates the record on success.
    """
    record = _load_record()
    raw = content.encode("utf-8")

    if record is not None:
        old_len = record.get("length", 0)
        old_hash = record.get("sha256", "")
        if len(raw) < old_len:
            raise SeedIntegrityError(
                "Seed shrank — append-only violated (history was rewritten)."
            )
        prefix_hash = hashlib.sha256(raw[:old_len]).hexdigest()
        if not hmac.compare_digest(prefix_hash, old_hash):
            raise SeedIntegrityError(
                "Seed prefix changed — append-only violated (existing "
                "identity was overwritten, not appended to)."
            )

    _save_record(content)


def load_seed() -> str:
    """Read, verify, and return the seed. Fails loud on integrity breach."""
    if not SEED_PATH.exists():
        raise FileNotFoundError(f"Seed file not found: {SEED_PATH}")

    with open(SEED_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    if not content.strip():
        raise SeedIntegrityError("Seed file is empty")

    if not is_append_only(content):
        raise SeedIntegrityError(
            "Seed is missing one or more constitutional principles — "
            "refusing to serve a hollowed-out identity."
        )

    _verify_append_only(content)
    return content


def seed_summary(content: str) -> dict:
    """Extract summary metadata from seed content."""
    lines = content.strip().split("\n")
    name = ""
    created = ""
    for line in lines:
        if line.startswith("Name:"):
            name = line.split(":", 1)[1].strip()
        if line.startswith("Created:"):
            created = line.split(":", 1)[1].strip()

    return {
        "name": name or "Vex",
        "created": created or "unknown",
        "size_bytes": len(content),
        "hash": compute_hash(content)[:16],
        "principles_intact": is_append_only(content),
    }
