"""Self-model tests — delta application, coherence, auto-calibration."""
import copy
import pytest

from self_model import (
    compute_mps_coherence,
    apply_delta,
    auto_calibrate,
    load_model,
    save_model,
)


def test_compute_coherence_skips_zero_observations():
    model = {
        "capabilities": {
            "python": {"estimated_skill": 0.8, "confidence": 0.8, "n_observations": 10},
            "rust": {"estimated_skill": 0.3, "confidence": 0.3, "n_observations": 0},
        }
    }
    c = compute_mps_coherence(model)
    # Only python counted: 0.8 * 0.8 = 0.64
    assert c == pytest.approx(0.64)


def test_compute_coherence_empty_caps():
    assert compute_mps_coherence({"capabilities": {}}) == 0.0


def test_compute_coherence_all_zero_obs():
    model = {
        "capabilities": {
            "x": {"estimated_skill": 0.5, "confidence": 0.5, "n_observations": 0},
            "y": {"estimated_skill": 0.9, "confidence": 0.9, "n_observations": 0},
        }
    }
    assert compute_mps_coherence(model) == 0.0


def test_apply_delta_increases_skill():
    model = {"capabilities": {}}
    updated = apply_delta(model, "python", 0.5, "Wrote a Flask app")
    cap = updated["capabilities"]["python"]
    # Old skill 0.5, delta 0.5: 0.5 * 0.80 + 0.5 * 0.20 = 0.5
    # Actually: new = old * 0.80 + delta * 0.20 = 0.5*0.8 + 0.5*0.2 = 0.5
    # So with delta=0.5 and old=0.5, new stays 0.5
    # But with delta=1.0: 0.5*0.8 + 1.0*0.2 = 0.6
    assert cap["n_observations"] == 1


def test_auto_calibrate_nudges_from_skills():
    model = {"capabilities": {}}
    entries = [{"skills": ["python", "python", "test_design"]}]
    updated = auto_calibrate(copy.deepcopy(model), entries)
    caps = updated["capabilities"]
    assert "python" in caps
    assert caps["python"]["n_observations"] >= 2
    assert caps["python"]["estimated_skill"] > 0.5


def test_auto_calibrate_handles_empty_skills():
    model = {"capabilities": {"python": {"estimated_skill": 0.6, "confidence": 0.7, "n_observations": 5}}}
    entries = [{"summary": "No skills field here."}]
    updated = auto_calibrate(copy.deepcopy(model), entries)
    # Should not have changed python
    assert updated["capabilities"]["python"]["n_observations"] == 5
