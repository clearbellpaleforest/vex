"""Updater gate — bus-driven exec must be explicitly enabled."""
import updater


def test_updater_disabled_by_default(monkeypatch):
    monkeypatch.delenv("VEX_UPDATER_ENABLE", raising=False)
    result = updater.process_updates()
    assert result["updated"] is False
    assert "disabled" in result["reason"]


def test_updater_stays_disabled_unless_exactly_1(monkeypatch):
    monkeypatch.setenv("VEX_UPDATER_ENABLE", "true")
    result = updater.process_updates()
    assert result["updated"] is False
    assert "disabled" in result["reason"]
