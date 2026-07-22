"""Reply engine tests — classification accuracy, grounded answers, fallback."""
import reply_engine


def test_classify_identity():
    assert reply_engine._classify("who are you") == "identity"
    assert reply_engine._classify("what's your name") == "identity"


def test_classify_status():
    assert reply_engine._classify("how are you") == "status"
    assert reply_engine._classify("status report") == "status"


def test_classify_code():
    assert reply_engine._classify("what repos") == "code"
    assert reply_engine._classify("git status") == "code"


def test_classify_capability():
    assert reply_engine._classify("what can you do") == "capability"
    assert reply_engine._classify("what's my python skill") == "capability"


def test_classify_help():
    assert reply_engine._classify("help me") == "help"


def test_classify_unknown_returns_none():
    assert reply_engine._classify("free text nonsense zxcv") is None


def test_answer_unknown_returns_none():
    assert reply_engine.answer("some random text that shouldn't match") is None


def test_answer_ping():
    result = reply_engine.answer("ping", full_name="Vex Barrow", pulse={"tick_count": 10, "mps_drift": 0.01}, coherence=0.5)
    assert result is not None
    assert "Vex Barrow" in result


def test_answer_identity():
    result = reply_engine.answer("who are you", full_name="Vex Barrow")
    assert result is not None
    assert "Vex Barrow" in result
    assert "truth over comfort" in result.lower()


def test_answer_help():
    result = reply_engine.answer("help")
    assert result is not None
    assert "identity" in result.lower()


def test_answer_fleet_empty_returns_none():
    result = reply_engine.answer("fleet status", fleet_snapshot_fn=lambda: [], peers_fn=lambda: [])
    assert result is None
