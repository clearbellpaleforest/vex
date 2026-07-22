"""Recall tests — coverage-first ranking, recency pad, empty query, src filter."""
import json
import sqlite3
from pathlib import Path

import recall
from config import VEX_HOME
from memory_index import ensure_schema, build_index


def _seed_memory(monkeypatch, entries):
    """Write fake memory entries to the test VEX_HOME and rebuild index."""
    memory_dir = VEX_HOME / "vex_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    today = "2026-07-22"
    path = memory_dir / f"{today}.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    build_index()


def test_recall_returns_empty_for_no_matches(monkeypatch):
    _seed_memory(monkeypatch, [{"summary": "Built metacognition module with coherence tracking."}])
    results = recall.recall("zqxwzqxw nonexistent term", k=3, src="memory")
    assert results == []


def test_recall_finds_exact_term(monkeypatch):
    _seed_memory(monkeypatch, [{"summary": "Fixed the 3-pane vim bug in vproj."}])
    results = recall.recall("pane vim", k=3)
    assert len(results) >= 1
    assert any("pane" in r.get("summary", "").lower() for r in results)


def test_recall_respects_src_filter(monkeypatch):
    _seed_memory(monkeypatch, [{"summary": "Memory-only entry about Python testing."}])
    results = recall.recall("python testing", k=3, src="memory")
    assert len(results) >= 1
    # src='message' should NOT match memory-only entries
    results_msg = recall.recall("python testing", k=3, src="message")
    assert all(r.get("src") == "message" for r in results_msg)


def test_recall_pads_with_recent_on_few_matches(monkeypatch):
    _seed_memory(monkeypatch, [
        {"summary": "Entry one."},
        {"summary": "Entry two."},
        {"summary": "Entry three."},
        {"summary": "Entry four."},
        {"summary": "Entry five."},
    ])
    results = recall.recall("zqxwzqxw", k=3)
    # Should pad with recent entries
    assert len(results) == 3
    for r in results:
        assert r["coverage"] == 0  # No term overlap


def test_recall_empty_query_returns_recent(monkeypatch):
    _seed_memory(monkeypatch, [{"summary": "Recent entry."}])
    results = recall.recall("", k=5)
    assert len(results) >= 1
