"""Test environment — isolate VEX_HOME in a temp dir BEFORE any daemon import.

config.py reads $VEX_HOME at import time; setting it here means the token,
DB, bus file, and diary that tests create never touch the real Vex home.
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="vex-test-"))
(_TMP / "vex_workspace").mkdir(parents=True, exist_ok=True)
os.environ["VEX_HOME"] = str(_TMP)
atexit.register(shutil.rmtree, _TMP, True)

# Daemon modules import each other bare (import tools, from config import ...),
# same as daemon.py's own sys.path insert.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vex_daemon"))

import pytest  # noqa: E402
