"""
Streamlit AppTest-based stress tests for the 5-tab dashboard redesign
(Current system / Scenarios / News / Details & charts / Data & methods).
Widget indices below were captured by actually running AppTest and
printing every widget's index+key/label, not assumed from source order —
Streamlit's AppTest lists elements in DOM/tree order, and pills/radio/etc
across tabs all coexist in one tree since every tab body executes on
every rerun regardless of which tab is visually active.

Confirmed layout as of this rewrite:
  pills[0]    = key "scn_pill" (Scenarios tab scenario picker)
  pills[1]    = key "det_pill" (Details & charts tab scenario picker)
  radio[0]    = "Headlines" (News tab headline picker)
  button[0]   = "See what this means for India →" (News tab)
  button[1]   = "Run robustness check" (Details & charts tab)
  button[2]   = "Apply filters" (sidebar form)
  slider[0]   = risk-aversion ("How cautious...") — Details & charts tab
  slider[1..4]= the 4 robustness sliders (shortfall penalty, spot premium,
                take-or-pay, P(Hormuz full closure)) — Details & charts tab
  checkbox[0] = "Animated map (client-side)" (sidebar)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).parent.parent / "app.py")


def _fresh():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=60)
    assert not at.exception, f"initial load raised: {at.exception}"
    return at


def _combined_markdown(at):
    return "\n".join(m.value for m in at.markdown)


def test_initial_load_shows_all_five_tabs_without_crashing():
    at = _fresh()
    combined = _combined_markdown(at)
    assert "What this is" in combined  # Current system
    assert "Oil imported daily" in combined
    assert at.pills[0].value is not None  # Scenarios tab pill rendered
    assert at.pills[1].value is not None  # Details tab pill rendered


def test_bold_text_renders_as_real_html_not_markdown_asterisks():
    """Regression test for the reported 'stars look weird' bug: the
    plain-language narrative cards are raw HTML <div>s, so emphasis must
    use <strong>, not Markdown '**' (which Streamlit does not re-process
    inside a raw HTML block and would render as literal asterisks)."""
    at = _fresh()
    combined = _combined_markdown(at)
    impact_idx = combined.find("Impact</h4>")
    assert impact_idx != -1
    window = combined[impact_idx:impact_idx + 400]
    assert "<strong>" in window
    assert "**" not in window


def test_every_scenario_survives_full_pipeline_in_scenarios_tab():
    at = _fresh()
    for key in ("baseline", "hormuz_50", "hormuz_100", "redsea_suspend"):
        at.pills[0].set_value(key).run(timeout=90)
        assert not at.exception, f"scenario {key} raised: {at.exception}"
        combined = _combined_markdown(at)
        assert "Impact" in combined and "Effect on India" in combined


def test_baseline_scenario_has_no_incident_story():
    at = _fresh()
    at.pills[0].set_value("baseline").run(timeout=90)
    assert not at.exception
    combined = _combined_markdown(at)
    assert "No supply gap" in combined or "Nothing is disrupted" in combined


def test_hormuz_100_shows_realworld_validation_banner():
    at = _fresh()
    at.pills[0].set_value("hormuz_100").run(timeout=90)
    assert not at.exception
    infos = [i.value for i in at.info]
    assert any("isn't hypothetical" in i for i in infos)


def test_scenarios_tab_pointer_mentions_details_and_data_tabs():
    """Independent-review request: nothing should feel like it disappeared
    — the Scenarios tab must point a curious reader toward where the
    technical numbers and sources actually live now."""
    at = _fresh()
    combined = _combined_markdown(at)
    assert "Details" in combined and "charts" in combined
    assert "Data" in combined and "methods" in combined


def test_details_tab_has_its_own_independent_scenario_picker():
    """Details & charts must work standalone — switching its own pill must
    not require (or be affected by) the Scenarios tab's pill."""
    at = _fresh()
    at.pills[0].set_value("baseline").run(timeout=90)  # Scenarios tab -> baseline
    assert not at.exception
    at.pills[1].set_value("hormuz_100").run(timeout=90)  # Details tab -> hormuz_100, independently
    assert not at.exception
    combined = _combined_markdown(at)
    assert "Full technical briefing" in combined


def test_details_tab_lambda_slider_extremes():
    at = _fresh()
    at.pills[1].set_value("hormuz_100").run(timeout=90)
    at.slider[0].set_value(0.0).run(timeout=90)
    assert not at.exception
    at.slider[0].set_value(6.0).run(timeout=90)
    assert not at.exception


def test_details_tab_has_full_briefing_and_charts():
    """The old Prescription tab's content must still exist — restored to
    its own tab per user feedback, not just demoted into an expander."""
    at = _fresh()
    at.pills[1].set_value("hormuz_100").run(timeout=90)
    assert not at.exception
    combined = _combined_markdown(at)
    assert "Full technical briefing" in combined
    assert "Recommended actions" in combined


def test_robustness_panel_extreme_sliders_simultaneously():
    at = _fresh()
    at.pills[1].set_value("hormuz_100").run(timeout=90)
    at.slider[1].set_value(225).run(timeout=30)
    at.slider[2].set_value(9.0).run(timeout=30)
    at.slider[3].set_value(1.0).run(timeout=30)
    at.slider[4].set_value(0.075).run(timeout=30)
    assert not at.exception
    at.button[1].click().run(timeout=90)
    assert not at.exception
    at.slider[1].set_value(75).run(timeout=30)
    at.slider[2].set_value(3.0).run(timeout=30)
    at.slider[3].set_value(0.35).run(timeout=30)
    at.slider[4].set_value(0.025).run(timeout=30)
    at.button[1].click().run(timeout=90)
    assert not at.exception


def test_every_headline_survives_full_pipeline_in_news_tab():
    at = _fresh()
    n_headlines = len(at.radio[0].options)
    for i in range(n_headlines):
        at.radio[0].set_value(at.radio[0].options[i]).run(timeout=60)
        assert not at.exception, f"headline index {i} selection raised: {at.exception}"
        at.button[0].click().run(timeout=90)
        assert not at.exception, f"headline index {i} extraction raised: {at.exception}"
        combined = _combined_markdown(at)
        assert "Impact" in combined


def test_news_tab_shows_full_story_not_just_summary_metrics():
    at = _fresh()
    at.radio[0].set_value("h5_full_closure").run(timeout=60)
    at.button[0].click().run(timeout=90)
    assert not at.exception
    combined = _combined_markdown(at)
    for section in ("Impact", "Effect on India", "What to do", "The plan"):
        assert section in combined, f"missing section: {section}"


def test_extract_headline_twice_in_a_row_different_headlines():
    at = _fresh()
    at.radio[0].set_value("h1_strikes").run(timeout=60)
    at.button[0].click().run(timeout=90)
    assert not at.exception
    at.radio[0].set_value("h5_full_closure").run(timeout=60)
    at.button[0].click().run(timeout=90)
    assert not at.exception
    combined = _combined_markdown(at)
    assert "closed" in combined.lower() or "Strait of Hormuz" in combined


def test_switching_scenarios_pill_after_a_news_lookup_does_not_crash():
    at = _fresh()
    at.radio[0].set_value("h5_full_closure").run(timeout=60)
    at.button[0].click().run(timeout=90)
    assert not at.exception
    at.pills[0].set_value("redsea_suspend").run(timeout=90)
    assert not at.exception


def test_static_map_fallback_no_crash_across_tabs():
    at = _fresh()
    at.checkbox[0].uncheck().run(timeout=60)
    assert not at.exception
    at.pills[0].set_value("hormuz_100").run(timeout=90)
    assert not at.exception
    at.pills[1].set_value("redsea_suspend").run(timeout=90)
    assert not at.exception
    at.radio[0].set_value("h5_full_closure").run(timeout=60)
    at.button[0].click().run(timeout=90)
    assert not at.exception


def test_data_and_methods_tab_content_present():
    at = _fresh()
    combined = _combined_markdown(at)
    assert "Data assumptions" in combined
    assert "Node table" in combined
    assert "real-world" in combined.lower() or "real world" in combined.lower()


def test_sidebar_filters_do_not_crash_any_tab():
    at = _fresh()
    at.button[2].click().run(timeout=60)  # "Apply filters" with defaults (no-op)
    assert not at.exception


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
