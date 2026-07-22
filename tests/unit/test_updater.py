"""Updater tests — git-native update replaces the old BOOTSTRAP RCE path."""
import updater


def test_process_updates_is_safe_noop():
    """The old process_updates() is now a safe no-op stub."""
    result = updater.process_updates()
    assert result["updated"] is False
    assert "git-native" in result["reason"]


def test_check_updates_is_read_only():
    """check_updates() never mutates — it's a fetch + log, not a pull."""
    result = updater.check_updates()
    assert "ok" in result
    # In test env (no git remote), may fail gracefully
    if not result["ok"]:
        assert "error" in result


def test_restart_daemon_signals():
    """restart_daemon() returns a method (systemctl or marker)."""
    result = updater.restart_daemon()
    # In test env without systemd, falls back to marker file
    assert result["ok"] is True
    assert result["method"] in ("systemctl", "marker")
