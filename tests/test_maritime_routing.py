"""
Independent-review request: "is there a way to make routes on the map as
actual routes instead of point A and point B being joined together with
straight line using actual route data over the ocean?" — yes, via the
`searoute` package (Apache-2.0, bundled offline maritime traffic-lane
graph, no network call needed). app.py's `_real_sea_path()` wraps it with
an st.cache_data cache and a fallback to the old manual-waypoint-bend
logic if a given pair can't be resolved.

These tests exercise `searoute` directly against every real shipping_route
edge in data/network.json (not by importing app.py, which runs
Streamlit-context calls like st.set_page_config() at import time — the
existing AppTest-based tests in test_app_integration.py already cover
that the map renders without exception end to end).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import searoute as sr

import scenario_engine as sceng


@pytest.fixture(scope="module")
def network():
    return sceng.load_network()


@pytest.fixture(scope="module")
def shipping_edges(network):
    node_lookup = {n["id"]: n for n in network["nodes"]}
    return [
        (e, node_lookup[e["source"]], node_lookup[e["target"]])
        for e in network["edges"] if e["type"] == "shipping_route"
    ]


def _route(src, tgt):
    return sr.searoute((src["lon"], src["lat"]), (tgt["lon"], tgt["lat"]), units="km")


def test_every_real_shipping_route_resolves_without_the_fallback(shipping_edges):
    """If searoute can't resolve a pair, app.py's build_path() silently
    falls back to the old straight/manually-bent line — which would be a
    silent regression to the exact bug being fixed. Assert every real
    edge in the network resolves cleanly, so a fallback is never
    triggered in practice today."""
    failures = []
    for e, src, tgt in shipping_edges:
        try:
            route = _route(src, tgt)
            coords = route["geometry"]["coordinates"]
            if len(coords) < 2:
                failures.append((e["id"], "fewer than 2 points"))
        except Exception as ex:
            failures.append((e["id"], str(ex)))
    assert not failures, f"these edges fell back to the straight-line renderer: {failures}"


def test_long_haul_routes_are_not_reduced_to_a_straight_line(shipping_edges):
    """The specific complaint: a route rendered as a straight point-A-to-
    point-B line cuts across landmass on long hauls. A real sea route
    between distant points should have multiple intermediate waypoints
    tracing the coastline/chokepoints, not just the two endpoints."""
    long_haul_ids = {"e_usa_mumbai", "e_usa_sikka", "e_russia_vadinar", "e_russia_sikka",
                      "e_nigeria_kochi", "e_angola_kochi"}
    checked = 0
    for e, src, tgt in shipping_edges:
        if e["id"] not in long_haul_ids:
            continue
        route = _route(src, tgt)
        coords = route["geometry"]["coordinates"]
        assert len(coords) > 5, f"{e['id']} resolved to a near-straight line ({len(coords)} points)"
        checked += 1
    assert checked == len(long_haul_ids), "not every expected long-haul edge was present in the network"


def test_route_endpoints_stay_close_to_the_real_node_coordinates(shipping_edges):
    """searoute snaps each endpoint to the nearest node on its maritime
    graph — this must stay a close approximation of the real supplier/port
    location, not snap somewhere wildly off (which would misrepresent
    where a route actually starts/ends on screen)."""
    def _dist_deg(a, b):
        # searoute can express a longitude past the antimeridian (e.g.
        # -279.6 instead of 80.4) for a long Pacific-crossing route —
        # mathematically the same point, so wrap the difference into
        # [-180, 180] before measuring distance rather than penalizing a
        # representation choice that isn't actually a routing error.
        dlon = (a[0] - b[0] + 180) % 360 - 180
        dlat = a[1] - b[1]
        return (dlon ** 2 + dlat ** 2) ** 0.5

    for e, src, tgt in shipping_edges:
        route = _route(src, tgt)
        coords = route["geometry"]["coordinates"]
        start, end = coords[0], coords[-1]
        assert _dist_deg(start, (src["lon"], src["lat"])) < 5.0, \
            f"{e['id']} start point snapped too far from source: {start} vs {(src['lon'], src['lat'])}"
        assert _dist_deg(end, (tgt["lon"], tgt["lat"])) < 5.0, \
            f"{e['id']} end point snapped too far from target: {end} vs {(tgt['lon'], tgt['lat'])}"


def test_route_distance_is_plausible_for_known_corridors(shipping_edges):
    """Spot-check: a Hormuz-routed Gulf-to-India edge should be a short
    regional hop (a few thousand km), not a global circumnavigation —
    catches the routing engine picking a nonsensical detour."""
    edge_by_id = {e["id"]: (e, src, tgt) for e, src, tgt in shipping_edges}
    e, src, tgt = edge_by_id["e_iraq_sikka"]
    route = _route(src, tgt)
    length_km = route["properties"]["length"]
    assert 500 < length_km < 5000, f"e_iraq_sikka route length implausible: {length_km} km"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
