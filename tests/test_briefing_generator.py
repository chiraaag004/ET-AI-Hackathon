"""
Tests for briefing_generator.py, focused on edge cases the happy-path demo
click never exercises: no supplier shifts, no incremental gap (so no
days-of-cover), no triggering headline (manual scenario pick).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import briefing_generator as briefing
import optimizer as opt
import scenario_engine as sceng


@pytest.fixture(scope="module")
def network():
    return sceng.load_network()


@pytest.fixture(scope="module")
def solved_pair():
    r0 = opt.run_full_network(lam=0.0, scenario_keys=["baseline", "hormuz_100"])
    r1 = opt.run_full_network(lam=3.0, scenario_keys=["baseline", "hormuz_100"])
    return r0, r1


def test_briefing_with_headline_and_signal(network, solved_pair):
    r0, r1 = solved_pair
    snapshot = sceng.summarize("hormuz_100")
    headline = {"headline": "Test headline", "date": "2026-01-01"}
    signal = {"corridor": "corridor_hormuz", "severity": 0.9}
    text, method = briefing.generate_briefing(
        headline=headline, signal=signal, scenario_key="hormuz_100",
        scenario_label=sceng.SCENARIOS["hormuz_100"]["label"], snapshot=snapshot,
        r0=r0, r1=r1, network=network,
    )
    assert method == "template"  # no ANTHROPIC_API_KEY in this environment
    assert "Test headline" in text
    assert "2026-01-01" in text


def test_briefing_without_headline_manual_trigger(network, solved_pair):
    """The manual scenario-picker flow passes headline=None, signal=None —
    this must not crash or leave a literal 'None' floating in the text."""
    r0, r1 = solved_pair
    snapshot = sceng.summarize("hormuz_100")
    text, method = briefing.generate_briefing(
        headline=None, signal=None, scenario_key="hormuz_100",
        scenario_label=sceng.SCENARIOS["hormuz_100"]["label"], snapshot=snapshot,
        r0=r0, r1=r1, network=network,
    )
    assert "None" not in text
    assert "Manually selected scenario" in text


def test_briefing_baseline_zero_incremental_gap_no_crash(network):
    """Baseline has incremental_gap_kbpd == 0 and days_of_cover == None —
    the template's cover_line branch must handle this without a crash or
    printing 'None days of cover'."""
    r0 = opt.run_full_network(lam=0.0, scenario_keys=["baseline"])
    r1 = opt.run_full_network(lam=3.0, scenario_keys=["baseline"])
    snapshot = sceng.summarize("baseline")
    assert snapshot["days_of_cover_if_unmitigated"] is None
    text, method = briefing.generate_briefing(
        headline=None, signal=None, scenario_key="baseline",
        scenario_label=sceng.SCENARIOS["baseline"]["label"], snapshot=snapshot,
        r0=r0, r1=r1, network=network,
    )
    assert "None" not in text


def test_briefing_no_supplier_shifts_at_lam_zero(network):
    """At lam=0 for both r0 and r1 (identical run), supplier_shifts should
    be empty — confirms the template's 'no shifts' fallback line renders
    instead of an empty bullet list."""
    r0 = opt.run_full_network(lam=0.0, scenario_keys=["baseline"])
    r1 = opt.run_full_network(lam=0.0, scenario_keys=["baseline"])  # same lam -> no shift
    snapshot = sceng.summarize("baseline")
    text, method = briefing.generate_briefing(
        headline=None, signal=None, scenario_key="baseline",
        scenario_label=sceng.SCENARIOS["baseline"]["label"], snapshot=snapshot,
        r0=r0, r1=r1, network=network,
    )
    assert "No supplier shifted" in text


def test_briefing_has_four_labeled_sections(network, solved_pair):
    """Independent-review request: the briefing must explicitly answer (1)
    what's the impact, (2) how does it affect India, (3) what to do, (4)
    what's the plan — not just cost deltas buried in prose. Verify the
    four required headers are present and in order."""
    r0, r1 = solved_pair
    snapshot = sceng.summarize("hormuz_100")
    text, _ = briefing.generate_briefing(
        headline=None, signal=None, scenario_key="hormuz_100",
        scenario_label=sceng.SCENARIOS["hormuz_100"]["label"], snapshot=snapshot,
        r0=r0, r1=r1, network=network,
    )
    for header in ("### Impact", "### Effect on India", "### Recommended actions", "### Response plan"):
        assert header in text
    order = [text.index(h) for h in ("### Impact", "### Effect on India", "### Recommended actions", "### Response plan")]
    assert order == sorted(order), "sections must appear in Impact -> Effect -> Actions -> Plan order"


def test_briefing_action_list_numbered_sequentially():
    """Regression test for a real bug: the numbered action list used to
    hardcode '1.'/'2.'/'3.' literals, so skipping an inapplicable action
    (e.g. no spot purchases needed) left a numbering gap, and the
    'Specific reallocation' sub-list separately hardcoded '1.' on every
    line instead of incrementing."""
    facts = {
        "trigger": "t", "trigger_date": "2026-01-01", "scenario_label": "Test",
        "disruption_gap_kbpd": 100.0, "days_of_cover": 10.0, "spr_coverage_fraction": 1.0,
        "expected_cost_risk_neutral": 1000.0, "expected_cost_risk_averse": 1010.0,
        "expected_cost_delta_pct": 1.0, "worst_scenario": "hormuz_100",
        "worst_case_cost_delta_pct": 2.0, "worst_case_shortfall_kbpd": 50.0,
        "supplier_shifts": [("A", 10.0, 20.0), ("B", 20.0, 5.0)],
        "supplier_gainers": [("A", 10.0, 20.0)], "supplier_losers": [("B", 20.0, 5.0)],
        "spr_draw_kbpd": 30.0, "spot_purchase_kbpd": 0.0,  # spot purchases deliberately zero
        "worst_hit_refineries": [], "estimated_duration_days": 7,
    }
    text = briefing._template_briefing(facts)
    assert "1. **Draw the SPR**" in text
    assert "2. **Re-contract toward diversified suppliers**" in text  # no gap left by skipped spot-cargo step
    assert "1. **Buy spot cargo**" not in text  # confirms it was actually skipped, not just renumbered
    # reallocation sub-list uses bullets, not a second competing "1." sequence
    assert "- Increase contracted volume from **A**" in text


def test_facts_never_invent_numbers_not_in_r0_r1(network, solved_pair):
    """Every numeric figure quoted in the template must trace back to r0/r1
    — spot check a couple of the money figures appear verbatim."""
    r0, r1 = solved_pair
    snapshot = sceng.summarize("hormuz_100")
    text, _ = briefing.generate_briefing(
        headline=None, signal=None, scenario_key="hormuz_100",
        scenario_label=sceng.SCENARIOS["hormuz_100"]["label"], snapshot=snapshot,
        r0=r0, r1=r1, network=network,
    )
    assert f"{r0['expected_cost_usd_per_day']:,.0f}" in text
    assert f"{r1['expected_cost_usd_per_day']:,.0f}" in text


def test_plain_language_story_uses_html_bold_not_markdown_asterisks(network, solved_pair):
    """Regression test for a real bug: plain_language_story()'s strings get
    embedded inside raw HTML <div> cards in app.py via
    st.markdown(..., unsafe_allow_html=True). Streamlit does not
    re-process Markdown syntax found inside a raw HTML block, so a literal
    '**word**' rendered as literal asterisks around the word on screen
    instead of bold text. Every emphasized figure must use a real <strong>
    tag, and none of the returned strings may contain '**'."""
    r0, r1 = solved_pair
    snapshot = sceng.summarize("hormuz_100")
    headline = {"headline": "Test headline", "date": "2026-01-01"}
    signal = {"corridor": "corridor_hormuz", "severity": 0.9, "estimated_duration_days": 14}
    facts = briefing._build_facts(
        headline, signal, "hormuz_100", sceng.SCENARIOS["hormuz_100"]["label"], snapshot, r0, r1, network,
        {n["id"]: n["name"] for n in network["nodes"]},
    )
    story = briefing.plain_language_story(facts, network)
    for key, value in story.items():
        if isinstance(value, list):
            for item in value:
                assert "**" not in item, f"{key} item still has markdown asterisks: {item!r}"
        else:
            assert "**" not in value, f"{key} still has markdown asterisks: {value!r}"
    assert "<strong>" in story["impact"]


def test_plain_language_story_baseline_has_no_markdown_asterisks(network):
    """Same check for the zero-gap (baseline) branch, which has its own
    separate literal strings."""
    r0 = opt.run_full_network(lam=0.0, scenario_keys=["baseline"])
    r1 = opt.run_full_network(lam=3.0, scenario_keys=["baseline"])
    snapshot = sceng.summarize("baseline")
    facts = briefing._build_facts(
        None, None, "baseline", sceng.SCENARIOS["baseline"]["label"], snapshot, r0, r1, network,
        {n["id"]: n["name"] for n in network["nodes"]},
    )
    story = briefing.plain_language_story(facts, network)
    for key, value in story.items():
        if isinstance(value, list):
            for item in value:
                assert "**" not in item
        else:
            assert "**" not in value


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
