"""
HTML status page rendered at GET /status.

Dark-background minimal page showing identity, pulse, capabilities,
recent sessions, drift trend, and diary lines.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from config import VEX_HOME, DIARY_PATH, MEMORY_DIR

_CSS = """
body {
    background: #1a1a2e; color: #e0e0e0; font-family: monospace;
    max-width: 720px; margin: 2em auto; padding: 0 1em;
}
h1 { color: #ffaf00; font-size: 1.4em; }
h2 { color: #7ec8e3; font-size: 1.1em; margin-top: 2em; }
.block { background: #16213e; border-radius: 6px; padding: 1em; margin: 1em 0; }
.label { color: #888; }
.value { color: #e0e0e0; }
.bar { height: 8px; background: #333; border-radius: 4px; margin: 4px 0 12px; }
.bar-fill { height: 8px; background: #ffaf00; border-radius: 4px; }
.warn { color: #ff6b6b; }
.ok { color: #51cf66; }
table { width: 100%; border-collapse: collapse; }
td { padding: 4px 8px; border-bottom: 1px solid #333; }
.diary { color: #aaa; font-style: italic; }
"""


def _last_diary_lines(n: int = 5) -> list[str]:
    if not DIARY_PATH.exists():
        return ["(no diary entries yet)"]
    try:
        with open(DIARY_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [l.strip() for l in lines[-n:]] if lines else ["(empty)"]
    except OSError:
        return ["(cannot read diary)"]


def _recent_sessions(n: int = 3) -> list[dict]:
    sessions = []
    if not MEMORY_DIR.exists():
        return sessions

    files = sorted(
        [f for f in MEMORY_DIR.iterdir() if f.suffix == ".jsonl"],
        reverse=True,
    )
    for f in files[:n]:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    sessions.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            pass
    return sessions[:n]


def render(
    seed_summary: dict,
    model_summary: dict,
    pulse: dict,
    tick_log: list[dict],
) -> str:
    """Render the full HTML status page."""

    # Compute full two-part name
    name_val = seed_summary.get("name", "Vex")
    given_val = seed_summary.get("given_name", "")
    full_name = f"{name_val} {given_val}".strip() if given_val else name_val

    # Capability bars
    caps_html = ""
    for name, cap in model_summary.get("capabilities", {}).items():
        pct = int(cap["skill"] * 100)
        caps_html += f"""
        <div>{name} <span class="label">({pct}%, {cap['observations']} obs)</span></div>
        <div class="bar"><div class="bar-fill" style="width:{pct}%"></div></div>
        """

    # Recent sessions
    sessions_html = ""
    for s in _recent_sessions():
        date = s.get("date", "unknown")
        summary = s.get("summary", s.get("decisions", ["no summary"])[0] if isinstance(s.get("decisions"), list) else "no summary")
        sessions_html += f'<tr><td>{date}</td><td>{summary}</td></tr>'

    if not sessions_html:
        sessions_html = '<tr><td colspan="2" class="label">No sessions recorded yet.</td></tr>'

    # Drift trend
    drift_html = ""
    for t in tick_log[-6:]:
        coherence = t.get("mps_coherence", 0)
        drift = t.get("mps_drift", 0)
        tick_at = t.get("tick_at", "")[:16]
        cls = "warn" if drift > 0.05 else "ok"
        drift_html += f'<tr><td>{tick_at}</td><td>{coherence:.3f}</td><td class="{cls}">{drift:.3f}</td></tr>'

    if not drift_html:
        drift_html = '<tr><td colspan="3" class="label">No ticks recorded yet.</td></tr>'

    # Diary lines
    diary_html = "<br>".join(_last_diary_lines(5))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Vex Daemon — Status</title>
    <style>{_CSS}</style>
    <meta http-equiv="refresh" content="60">
</head>
<body>
<h1>Vex Daemon</h1>

<h2>Identity</h2>
<div class="block">
    <div><span class="label">Name:</span> <span class="value">{full_name}</span></div>
    {f'''<div><span class="label">Given:</span> <span class="value">{given_val}</span></div>''' if given_val else ''}
    <div><span class="label">Created:</span> <span class="value">{seed_summary.get('created', 'unknown')}</span></div>
    <div><span class="label">Principles intact:</span> <span class="{'ok' if seed_summary.get('principles_intact') else 'warn'}">{'yes' if seed_summary.get('principles_intact') else 'NO — CHECK SEED'}</span></div>
</div>

<h2>Pulse</h2>
<div class="block">
    <div><span class="label">Ticks:</span> <span class="value">{pulse.get('tick_count', 0)}</span></div>
    <div><span class="label">Last tick:</span> <span class="value">{pulse.get('last_tick', 'never')[:19]}</span></div>
    <div><span class="label">Last session:</span> <span class="value">{pulse.get('last_session', 'never')[:19]}</span></div>
    <div><span class="label">Coherence:</span> <span class="value">{pulse.get('mps_coherence', 0):.4f}</span></div>
    <div><span class="label">Drift:</span> <span class="{'warn' if pulse.get('mps_drift', 0) > 0.05 else 'ok'}">{pulse.get('mps_drift', 0):.4f}</span></div>
</div>

<h2>Capabilities</h2>
<div class="block">
    {caps_html or '<span class="label">No capabilities tracked yet.</span>'}
</div>

<h2>Recent Sessions</h2>
<div class="block">
    <table>
    <tr><th>Date</th><th>Summary</th></tr>
    {sessions_html}
    </table>
</div>

<h2>Drift Trend</h2>
<div class="block">
    <table>
    <tr><th>Tick</th><th>Coherence</th><th>Drift</th></tr>
    {drift_html}
    </table>
</div>

<h2>Diary</h2>
<div class="block diary">
    {diary_html}
</div>

</body>
</html>"""
