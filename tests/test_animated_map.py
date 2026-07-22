"""
Tests for animated_map.py — the client-side deck.gl component had zero
dedicated coverage before this. build_map_html() is pure Python (no
Streamlit dependency), so it's cheap to test directly and thoroughly: does
it produce valid embeddable HTML/JS for every payload shape app.py can
actually hand it (no solve yet, baseline, a disrupted scenario with flows,
missing optional fields), and does the JSON payload round-trip cleanly
through the generated script rather than being mangled by string
concatenation.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from animated_map import build_map_html


def _minimal_payload(**overrides):
    payload = {
        "nodes": [
            {"id": "sup_russia", "name": "Russia", "type": "supplier", "lon": 60.0, "lat": 55.0,
             "color": [230, 57, 70], "radius": 60000},
            {"id": "port_sikka", "name": "Sikka", "type": "port", "lon": 70.0, "lat": 22.0,
             "color": [42, 157, 143], "radius": 30000},
        ],
        "edges": [
            {"id": "e_russia_sikka", "name": "Russia → Sikka", "path": [[60.0, 55.0], [70.0, 22.0]],
             "type": "shipping_route", "color": [42, 157, 143], "cap": 500.0,
             "day0": 400.0, "shock": 400.0, "adapted": 420.0, "disrupted": False},
        ],
        "corridor": None,
        "severity": 0.0,
        "event": None,
        "timeline": {"enabled": False},
        "scenario_label": "Baseline",
        "top_growers": [],
    }
    payload.update(overrides)
    return payload


def _extract_data_json(html: str) -> dict:
    """Pull the `const DATA = {...};` payload back out of the generated
    script and parse it — the strongest possible check that Python's
    json.dumps + string concatenation didn't produce something the
    browser's JS parser would choke on."""
    match = re.search(r"const DATA = (\{.*?\});\n", html, re.DOTALL)
    assert match, "could not find `const DATA = ...;` in generated HTML"
    return json.loads(match.group(1))


def test_build_map_html_returns_a_string():
    html = build_map_html(_minimal_payload())
    assert isinstance(html, str)
    assert len(html) > 0


def test_build_map_html_includes_deckgl_and_topojson_script_tags():
    """Independent-review finding: the old maplibre-gl + CARTO tile-style
    basemap silently failed to render inside Streamlit's sandboxed
    components.html iframe ("the countries does not show"). Replaced with
    a single static TopoJSON land layer (topojson-client + deck.gl's own
    GeoJsonLayer) with no live tile-server dependency at all."""
    html = build_map_html(_minimal_payload())
    assert "deck.gl" in html
    assert "topojson" in html
    assert "maplibre" not in html.lower()


def test_build_map_html_fetches_land_topology_with_no_tile_server():
    html = build_map_html(_minimal_payload())
    assert "world-atlas" in html
    assert "cartocdn" not in html.lower()


def test_build_map_html_data_payload_round_trips_exactly():
    payload = _minimal_payload()
    html = build_map_html(payload)
    round_tripped = _extract_data_json(html)
    assert round_tripped == payload


def test_build_map_html_handles_none_corridor_and_event():
    html = build_map_html(_minimal_payload(corridor=None, event=None))
    data = _extract_data_json(html)
    assert data["corridor"] is None
    assert data["event"] is None


def test_build_map_html_handles_active_corridor_and_event():
    payload = _minimal_payload(
        corridor={"lon": 56.5, "lat": 26.5, "name": "Strait of Hormuz"},
        severity=0.9,
        event={"lon": 59.5, "lat": 29.5, "name": "event_h5_full_closure"},
    )
    html = build_map_html(payload)
    data = _extract_data_json(html)
    assert data["corridor"]["name"] == "Strait of Hormuz"
    assert data["event"]["name"] == "event_h5_full_closure"


def test_build_map_html_handles_timeline_disabled():
    html = build_map_html(_minimal_payload(timeline={"enabled": False}))
    data = _extract_data_json(html)
    assert data["timeline"]["enabled"] is False


def test_build_map_html_handles_timeline_enabled_with_full_shape():
    payload = _minimal_payload(timeline={
        "enabled": True, "n_days": 7,
        "spr": {"day0": 0.0, "shock": 300.0, "adapted": 250.0},
        "shortfall": {"day0": 50.0, "shock": 400.0, "adapted": 100.0},
    })
    html = build_map_html(payload)
    data = _extract_data_json(html)
    assert data["timeline"]["n_days"] == 7
    assert data["timeline"]["spr"]["shock"] == 300.0


def test_build_map_html_handles_empty_nodes_and_edges():
    """No solve yet / all node-and-edge-type filters cleared in the
    sidebar — must not crash even with nothing to draw."""
    html = build_map_html(_minimal_payload(nodes=[], edges=[]))
    data = _extract_data_json(html)
    assert data["nodes"] == []
    assert data["edges"] == []


def test_build_map_html_includes_top_growers_when_present():
    """The 'better alternatives' panel — new payload field. Must appear
    verbatim in the embedded data so the JS can render it, and the HUD
    markup that reads it must be present in the template."""
    payload = _minimal_payload(top_growers=[
        {"name": "USA → Mumbai", "day0": 150.0, "adapted": 310.0},
        {"name": "UAE → Sikka", "day0": 200.0, "adapted": 280.0},
    ])
    html = build_map_html(payload)
    data = _extract_data_json(html)
    assert data["top_growers"][0]["name"] == "USA → Mumbai"
    assert data["top_growers"][0]["adapted"] == 310.0
    assert "hud-alts" in html
    assert "top_growers" in html


def test_build_map_html_empty_top_growers_still_valid():
    html = build_map_html(_minimal_payload(top_growers=[]))
    data = _extract_data_json(html)
    assert data["top_growers"] == []


def test_build_map_html_legend_mentions_domestic_and_port_to_refinery():
    """Independent-review finding: the legend used to list only
    normal/disrupted/reroute/SPR even though domestic_pipeline (orange)
    and port_to_refinery (slate) edges are drawn with their own colors."""
    html = build_map_html(_minimal_payload())
    assert "domestic" in html.lower()
    assert "refinery" in html.lower()


def test_build_map_html_respects_height_argument():
    short_html = build_map_html(_minimal_payload(), height=400)
    tall_html = build_map_html(_minimal_payload(), height=800)
    assert "390px" in short_html  # height - 10, per the wrap div
    assert "790px" in tall_html


def test_build_map_html_scenario_label_appears_in_payload():
    html = build_map_html(_minimal_payload(scenario_label="Hormuz full closure"))
    data = _extract_data_json(html)
    assert data["scenario_label"] == "Hormuz full closure"


def test_build_map_html_persists_camera_via_sessionstorage():
    """Independent-review finding: every Streamlit rerun fully remounts
    this component, snapping the camera back to the default view. Camera
    state should be saved/restored via sessionStorage, wrapped in
    try/catch so it degrades gracefully if storage is blocked."""
    html = build_map_html(_minimal_payload())
    assert "sessionStorage" in html
    assert "petrotwin_viewstate" in html
    # must be defensive — storage access can throw in sandboxed contexts
    assert "catch" in html


def test_build_map_html_land_fetch_failure_is_caught_not_fatal():
    """The land layer is a nice-to-have, not a requirement — if the
    TopoJSON fetch fails (offline, blocked), dots/lines must still render
    rather than the whole component erroring out."""
    html = build_map_html(_minimal_payload())
    assert ".catch(" in html


def test_build_map_html_edge_with_null_flow_fields_does_not_crash():
    """Non-shipping edges (spr_link, domestic_pipeline before a solve has
    run) carry day0=shock=adapted=None in the real payload — must survive
    JSON serialization and still produce valid output."""
    payload = _minimal_payload(edges=[
        {"id": "e_spr_vizag_link", "name": "SPR Vizag → Ref", "path": [[83.2, 17.7], [83.3, 17.8]],
         "type": "spr_link", "color": [131, 56, 236], "cap": 0.0,
         "day0": None, "shock": None, "adapted": None, "disrupted": False},
    ])
    html = build_map_html(payload)
    data = _extract_data_json(html)
    assert data["edges"][0]["day0"] is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
