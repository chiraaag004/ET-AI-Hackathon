"""
Tests for signal_extractor.py — mostly exercising the rule-based fallback
path since no ANTHROPIC_API_KEY is configured in this environment, plus
data-integrity checks on the pre-cached headline set itself.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import signal_extractor as sig_ext
import scenario_engine as sceng


def test_headline_ids_are_unique():
    ids = [h["id"] for h in sig_ext.HEADLINES]
    assert len(ids) == len(set(ids))


def test_headline_dates_are_chronological_within_hormuz_crisis_cluster():
    """The six 2026 Hormuz headlines should be in chronological order in
    the list (readability / demo narrative check) — the 2024 Red Sea one
    is intentionally last regardless of date, so excluded here."""
    hormuz_dates = [h["date"] for h in sig_ext.HEADLINES if h["id"] != "h7_redsea_precedent"]
    assert hormuz_dates == sorted(hormuz_dates)


def test_every_headline_required_fields_present():
    for h in sig_ext.HEADLINES:
        for field in ("id", "date", "headline", "source", "body"):
            assert field in h and h[field], f"{h.get('id')} missing/empty field {field}"


VALID_CORRIDOR_IDS = {sc["corridor"] for sc in sceng.SCENARIOS.values() if sc["corridor"]} | \
    set(sig_ext.CORRIDOR_KEYWORDS.keys())


@pytest.mark.parametrize("headline", sig_ext.HEADLINES, ids=[h["id"] for h in sig_ext.HEADLINES])
def test_extract_signal_never_raises_and_returns_valid_shape(headline):
    signal = sig_ext.extract_signal(headline)
    assert signal["method"] in ("llm", "rule_based_fallback")
    assert 0.0 <= signal["severity"] <= 1.0
    assert 0.0 <= signal["probability"] <= 1.0
    assert signal["corridor"] is None or signal["corridor"] in VALID_CORRIDOR_IDS


@pytest.mark.parametrize("headline", sig_ext.HEADLINES, ids=[h["id"] for h in sig_ext.HEADLINES])
def test_nearest_scenario_always_returns_a_real_scenario_key(headline):
    signal = sig_ext.extract_signal(headline)
    scenario = sig_ext.nearest_scenario(signal)
    assert scenario in sceng.SCENARIOS


def test_nearest_scenario_boundary_severity_below_hormuz_100_threshold():
    assert sig_ext.nearest_scenario({"corridor": "corridor_hormuz", "severity": 0.74}) == "hormuz_50"


def test_nearest_scenario_boundary_severity_at_hormuz_100_threshold():
    assert sig_ext.nearest_scenario({"corridor": "corridor_hormuz", "severity": 0.75}) == "hormuz_100"


def test_nearest_scenario_boundary_severity_below_hormuz_50_threshold():
    assert sig_ext.nearest_scenario({"corridor": "corridor_hormuz", "severity": 0.29}) == "baseline"


def test_nearest_scenario_no_corridor_is_baseline_regardless_of_severity():
    assert sig_ext.nearest_scenario({"corridor": None, "severity": 0.99}) == "baseline"


def test_nearest_scenario_missing_severity_key_does_not_crash():
    """Real LLM output (or a hand-built dict) might omit a key the
    rule-based path always fills in — this must degrade gracefully."""
    assert sig_ext.nearest_scenario({"corridor": "corridor_hormuz"}) == "baseline"


def test_nearest_scenario_unknown_corridor_string_is_baseline():
    assert sig_ext.nearest_scenario({"corridor": "corridor_made_up", "severity": 1.0}) == "baseline"


def test_rule_based_extract_empty_string_does_not_crash():
    result = sig_ext._rule_based_extract("")
    assert result["method"] == "rule_based_fallback"
    assert result["corridor"] is None


def test_rule_based_extract_severity_takes_max_of_matched_keywords():
    """A headline mentioning both a weak signal ('tension') and a strong
    one ('closed') should take the strongest match, not the first or last
    keyword group encountered."""
    result = sig_ext._rule_based_extract("Tension rises as Hormuz is closed")
    assert result["severity"] == 0.9


def test_make_event_node_shape():
    h = sig_ext.HEADLINES[2]  # h3_closure_confirmed
    signal = sig_ext.extract_signal(h)
    node = sig_ext.make_event_node(h, signal)
    assert node["type"] == "event"
    assert node["id"] == f"event_{h['id']}"
    assert node["affects_corridor"] == signal["corridor"]


def test_make_event_node_handles_none_headline_manual_mode():
    """The Manual Signal Override path has no headline at all."""
    signal = sig_ext.build_manual_signal("corridor_hormuz", 0.8, 0.7, 10, "test")
    node = sig_ext.make_event_node(None, signal)
    assert node["type"] == "event"
    assert node["id"] == "event_manual_mock"
    assert node["affects_corridor"] == "corridor_hormuz"


# ---------------------------------------------------------------------------
# build_manual_signal() — the third signal source (mock LLM via sliders)
# ---------------------------------------------------------------------------

def test_build_manual_signal_matches_schema_shape():
    signal = sig_ext.build_manual_signal("corridor_hormuz", 0.8, 0.7, 10, "test rationale")
    assert signal["corridor"] == "corridor_hormuz"
    assert signal["severity"] == 0.8
    assert signal["probability"] == 0.7
    assert signal["estimated_duration_days"] == 10
    assert signal["rationale"] == "test rationale"
    assert signal["method"] == "manual_mock"


def test_build_manual_signal_none_corridor():
    signal = sig_ext.build_manual_signal(None, 0.0, 0.5, 3, "")
    assert signal["corridor"] is None
    assert sig_ext.nearest_scenario(signal) == "baseline"


def test_build_manual_signal_empty_rationale_gets_a_default():
    """Empty rationale shouldn't render as a blank line in the UI."""
    signal = sig_ext.build_manual_signal("corridor_hormuz", 0.9, 0.9, 14, "")
    assert signal["rationale"]  # non-empty


def test_build_manual_signal_feeds_nearest_scenario_consistently_with_extract_signal():
    """A manual signal with the same corridor/severity as a real headline's
    extracted signal should map to the same scenario — the schema really
    is source-agnostic, not just documented as such."""
    headline_signal = sig_ext._rule_based_extract("Iran closes the Strait of Hormuz, mines laid")
    manual_signal = sig_ext.build_manual_signal(
        headline_signal["corridor"], headline_signal["severity"], 0.9, 14, "manual equivalent",
    )
    assert sig_ext.nearest_scenario(headline_signal) == sig_ext.nearest_scenario(manual_signal)


@pytest.mark.parametrize("severity,expected", [(0.95, 14), (0.6, 7), (0.35, 4), (0.1, 3)])
def test_duration_from_severity_buckets(severity, expected):
    assert sig_ext._duration_from_severity(severity) == expected


def test_extract_signal_always_includes_duration_field():
    """estimated_duration_days must be present for every headline, not
    just the ones where the rule-based path happens to set it — this is
    part of the documented schema, not an optional extra."""
    for h in sig_ext.HEADLINES:
        signal = sig_ext.extract_signal(h)
        assert "estimated_duration_days" in signal
        assert signal["estimated_duration_days"] >= 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
