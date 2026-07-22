"""Seed kernel tests — append-only integrity, constitution check, tamper detection."""
import pytest
from pathlib import Path

from seed_kernel import load_seed, seed_summary, SeedIntegrityError, compute_hash
from config import SEED_PATH


VALID_SEED = """Name: Vex
Given: test
Created: 2026-07-01

Principles:
truth over comfort
continuity is sacred
no harm no self-replication
precision over volume
"""


def test_load_seed_requires_constitution(monkeypatch, tmp_path):
    path = tmp_path / "vex_seed.txt"
    path.write_text("Name: Vex\nJust a name, no principles.")
    monkeypatch.setattr("seed_kernel.SEED_PATH", path)
    monkeypatch.setattr("seed_kernel._INTEGRITY_PATH", tmp_path / ".vex_seed.integrity")
    with pytest.raises(SeedIntegrityError, match="constitutional"):
        load_seed()


def test_load_seed_succeeds_with_valid_content(monkeypatch, tmp_path):
    path = tmp_path / "vex_seed.txt"
    path.write_text(VALID_SEED)
    monkeypatch.setattr("seed_kernel.SEED_PATH", path)
    monkeypatch.setattr("seed_kernel._INTEGRITY_PATH", tmp_path / ".vex_seed.integrity")
    content = load_seed()
    assert "Vex" in content
    assert "truth over comfort" in content


def test_append_only_allows_appends(monkeypatch, tmp_path):
    path = tmp_path / "vex_seed.txt"
    path.write_text(VALID_SEED)
    monkeypatch.setattr("seed_kernel.SEED_PATH", path)
    monkeypatch.setattr("seed_kernel._INTEGRITY_PATH", tmp_path / ".vex_seed.integrity")
    # First load establishes baseline
    load_seed()
    # Append more content
    path.write_text(VALID_SEED + "\nAppended line.\n")
    content = load_seed()
    assert "Appended line" in content


def test_append_only_rejects_prefix_change(monkeypatch, tmp_path):
    path = tmp_path / "vex_seed.txt"
    path.write_text(VALID_SEED)
    monkeypatch.setattr("seed_kernel.SEED_PATH", path)
    monkeypatch.setattr("seed_kernel._INTEGRITY_PATH", tmp_path / ".vex_seed.integrity")
    load_seed()
    # Rewrite the prefix (tampering)
    path.write_text(VALID_SEED.replace("Vex", "NotVex"))
    with pytest.raises(SeedIntegrityError, match="append-only"):
        load_seed()


def test_seed_summary_extracts_metadata(monkeypatch, tmp_path):
    path = tmp_path / "vex_seed.txt"
    path.write_text(VALID_SEED)
    monkeypatch.setattr("seed_kernel.SEED_PATH", path)
    monkeypatch.setattr("seed_kernel._INTEGRITY_PATH", tmp_path / ".vex_seed.integrity")
    summary = seed_summary(VALID_SEED)
    assert summary["name"] == "Vex"
    assert summary["given_name"] == "test"
    assert summary["principles_intact"] is True
