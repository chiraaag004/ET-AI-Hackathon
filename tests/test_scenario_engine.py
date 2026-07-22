"""
Real correctness tests for scenario_engine.py — not "does it run," but "is
the arithmetic right" and "does it survive inputs the UI sliders can't
produce but a future caller might."
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import scenario_engine as sceng


@pytest.fixture(scope="module")
def network():
    return sceng.load_network()


# ---------------------------------------------------------------------------
# degraded_capacity — the core disruption primitive
# ---------------------------------------------------------------------------

def test_degraded_capacity_zero_severity_is_noop():
    edge = {"type": "shipping_route", "capacity_kbpd": 500, "via_corridor": "corridor_hormuz",
            "chokepoint_exposure": 1.0}
    assert sceng.degraded_capacity(edge, "corridor_hormuz", 0.0) == 500


def test_degraded_capacity_full_severity_full_exposure_zeroes_out():
    edge = {"type": "shipping_route", "capacity_kbpd": 500, "via_corridor": "corridor_hormuz",
            "chokepoint_exposure": 1.0}
    assert sceng.degraded_capacity(edge, "corridor_hormuz", 1.0) == 0.0


def test_degraded_capacity_wrong_corridor_is_noop():
    edge = {"type": "shipping_route", "capacity_kbpd": 500, "via_corridor": "corridor_hormuz",
            "chokepoint_exposure": 1.0}
    assert sceng.degraded_capacity(edge, "corridor_redsea_suez", 1.0) == 500


def test_degraded_capacity_non_shipping_edge_never_degrades():
    edge = {"type": "port_to_refinery", "capacity_kbpd": 500, "via_corridor": "corridor_hormuz",
            "chokepoint_exposure": 1.0}
    assert sceng.degraded_capacity(edge, "corridor_hormuz", 1.0) == 500


def test_degraded_capacity_never_negative():
    # severity*exposure > 1 shouldn't be reachable via the app's sliders, but
    # nothing in the function signature prevents a future caller from doing it.
    edge = {"type": "shipping_route", "capacity_kbpd": 500, "via_corridor": "corridor_hormuz",
            "chokepoint_exposure": 1.0}
    assert sceng.degraded_capacity(edge, "corridor_hormuz", 1.5) == 0.0  # not negative


def test_degraded_capacity_missing_capacity_field_defaults_zero():
    edge = {"type": "shipping_route", "via_corridor": "corridor_hormuz", "chokepoint_exposure": 1.0}
    assert sceng.degraded_capacity(edge, "corridor_hormuz", 1.0) == 0.0


# ---------------------------------------------------------------------------
# summarize() / incremental gap logic
# ---------------------------------------------------------------------------

def test_baseline_incremental_gap_is_zero_by_construction():
    s = sceng.summarize("baseline")
    assert s["incremental_gap_kbpd"] == 0.0, "baseline vs itself must net to exactly zero"


def test_all_scenarios_summarize_without_error(network):
    for key in sceng.SCENARIOS:
        s = sceng.summarize(key)
        assert s["total_refinery_gap_kbpd"] >= 0
        assert s["incremental_gap_kbpd"] >= 0
        assert s["baseline_gap_kbpd"] >= 0


def test_incremental_gap_never_exceeds_raw_gap():
    """incremental = max(0, raw - baseline), so it can never be larger than
    the raw gap itself — if this ever fails, the netting-out logic (added
    to fix the baseline-artifact complaint) has a sign error."""
    for key in sceng.SCENARIOS:
        s = sceng.summarize(key)
        assert s["incremental_gap_kbpd"] <= s["total_refinery_gap_kbpd"] + 1e-6


def test_more_severe_hormuz_scenario_has_gte_incremental_gap():
    """hormuz_100 (full closure) must be at least as bad as hormuz_50 —
    monotonicity is a basic sanity check on the whole disruption model."""
    s50 = sceng.summarize("hormuz_50")
    s100 = sceng.summarize("hormuz_100")
    assert s100["incremental_gap_kbpd"] >= s50["incremental_gap_kbpd"]


def test_days_of_cover_none_when_no_gap():
    assert sceng.days_of_cover({"nodes": []}, 0.0) is None
    assert sceng.days_of_cover({"nodes": []}, -5.0) is None  # negative gap is nonsensical but shouldn't crash


def test_days_of_cover_handles_zero_spr_gracefully(network):
    """If a network had zero SPR nodes, max_draw_kbpd=0 -> effective_draw=0
    -> must return None (not raise ZeroDivisionError)."""
    empty_spr_network = {"nodes": [n for n in network["nodes"] if n["type"] != "spr"]}
    result = sceng.days_of_cover(empty_spr_network, 100.0)
    assert result is None


def test_refinery_supply_gap_gap_never_negative(network):
    for key in sceng.SCENARIOS:
        result = sceng.apply_scenario(network, key)
        gaps = sceng.refinery_supply_gap(network, result)
        for g in gaps:
            assert g["gap_kbpd"] >= 0
            assert g["utilization_pct"] <= 100.0 + 1e-6


def test_unknown_scenario_key_raises_keyerror():
    """apply_scenario on a bogus key should fail loudly, not silently
    return something wrong — this is desired behavior, asserting it stays
    that way rather than being accidentally swallowed later."""
    with pytest.raises(KeyError):
        sceng.apply_scenario({"nodes": [], "edges": []}, "not_a_real_scenario")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
