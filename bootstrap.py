#!/usr/bin/env python3
"""
Vex first-run bootstrap.

Copies the shipped templates into your live identity files, so a fresh
clone becomes a blank, runnable Vex. Never overwrites existing identity —
run it once, then edit vex_seed.txt to write your agent into existence.

    python bootstrap.py

Idempotent: re-running only creates what's missing.
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "vex_daemon"))
from config import VEX_HOME, SEED_PATH, SELF_MODEL_PATH, MEMORY_DIR  # noqa: E402

REPO = Path(__file__).resolve().parent
SEED_TEMPLATE = REPO / "vex_seed.template.txt"
MODEL_TEMPLATE = REPO / "vex_self_model.template.json"


def _copy_if_absent(src: Path, dst: Path) -> bool:
    if dst.exists():
        print(f"  exists, skipped: {dst.name}")
        return False
    if not src.exists():
        print(f"  MISSING TEMPLATE: {src.name}", file=sys.stderr)
        return False
    shutil.copy2(src, dst)
    print(f"  created: {dst.name}")
    return True


def main() -> None:
    print(f"Bootstrapping Vex in: {VEX_HOME}")

    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  ready: {MEMORY_DIR.name}/")

    created_seed = _copy_if_absent(SEED_TEMPLATE, SEED_PATH)
    _copy_if_absent(MODEL_TEMPLATE, SELF_MODEL_PATH)

    print("\nDone.")
    if created_seed:
        print(
            f"Next: edit {SEED_PATH.name} — fill in [identity] and "
            "[relationships]. Then start the daemon:\n"
            "    pip install -r requirements.txt\n"
            "    python vex_daemon/daemon.py"
        )
    else:
        print("Identity already present — nothing to write.")


if __name__ == "__main__":
    main()
