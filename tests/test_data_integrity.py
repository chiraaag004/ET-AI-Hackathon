"""
Sanity checks on data/network.json itself — every other test assumes this
graph is well-formed (every edge references real nodes, no orphaned
capacity, shares roughly sum to 100%). Nothing upstream actually verifies
that assumption; this does.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import scenario_engine as sceng


@pytest.fixture(scope="module")
def network():
    return sceng.load_network()


def test_every_edge_endpoint_references_a_real_node(network):
    node_ids = {n["id"] for n in network["nodes"]}
    for e in network["edges"]:
        assert e["source"] in node_ids, f"edge {e['id']} has unknown source {e['source']}"
        assert e["target"] in node_ids, f"edge {e['id']} has unknown target {e['target']}"


def test_every_via_corridor_references_a_real_corridor_node(network):
    corridor_ids = {n["id"] for n in network["nodes"] if n["type"] == "corridor"}
    for e in network["edges"]:
        via = e.get("via_corridor")
        if via is not None:
            assert via in corridor_ids, f"edge {e['id']} references unknown corridor {via}"


def test_every_alt_corridor_references_a_real_corridor_node(network):
    corridor_ids = {n["id"] for n in network["nodes"] if n["type"] == "corridor"}
    for e in network["edges"]:
        alt = e.get("alt_corridor")
        if alt is not None:
            assert alt in corridor_ids, f"edge {e['id']} references unknown alt_corridor {alt}"


def test_no_duplicate_node_ids(network):
    ids = [n["id"] for n in network["nodes"]]
    assert len(ids) == len(set(ids))


def test_no_duplicate_edge_ids(network):
    ids = [e["id"] for e in network["edges"]]
    assert len(ids) == len(set(ids))


def test_supplier_shares_sum_near_100_pct(network):
    """Import + domestic supplier flow_kbpd should sum close to the total
    import figure documented in DATA_SOURCES.md (~4936 kbpd) + domestic
    (~562 kbpd) — a gross sanity check that nobody fat-fingered a share."""
    suppliers = [n for n in network["nodes"] if n["type"] == "supplier"]
    total_flow = sum(n.get("flow_kbpd", 0.0) for n in suppliers)
    assert 5000 <= total_flow <= 6000, f"total supplier flow {total_flow} kbpd is out of expected range"


def test_all_capacities_and_flows_non_negative(network):
    for n in network["nodes"]:
        for field in ("flow_kbpd", "capacity_kbpd", "inventory_mmt", "max_draw_rate_kbpd"):
            if field in n:
                assert n[field] >= 0, f"node {n['id']} has negative {field}"
    for e in network["edges"]:
        if "capacity_kbpd" in e:
            assert e["capacity_kbpd"] >= 0, f"edge {e['id']} has negative capacity"


def test_chokepoint_exposure_in_valid_range(network):
    for e in network["edges"]:
        exposure = e.get("chokepoint_exposure")
        if exposure is not None:
            assert 0.0 <= exposure <= 1.0, f"edge {e['id']} has out-of-range exposure {exposure}"


def test_scenario_probabilities_sum_to_one():
    total = sum(sc["probability"] for sc in sceng.SCENARIOS.values())
    assert abs(total - 1.0) < 1e-6, f"scenario probabilities sum to {total}, not 1.0"


def test_scenario_severities_in_valid_range():
    for key, sc in sceng.SCENARIOS.items():
        assert 0.0 <= sc["severity"] <= 1.0, f"{key} has out-of-range severity {sc['severity']}"


def test_every_refinery_has_positive_capacity(network):
    refineries = [n for n in network["nodes"] if n["type"] == "refinery"]
    assert len(refineries) > 0
    for r in refineries:
        assert r["capacity_kbpd"] > 0, f"refinery {r['id']} has non-positive capacity"


def test_every_supplier_has_at_least_one_outbound_edge_or_is_flagged(network):
    """A supplier with flow_kbpd > 0 but zero outbound edges would be
    silently unreachable — the optimizer's supplier_cap constraint would
    just skip it (pyo.Constraint.Skip), hiding real capacity from every
    result without any error. Would have caught this class of bug earlier
    if it had existed."""
    suppliers = [n for n in network["nodes"] if n["type"] == "supplier" and n.get("flow_kbpd", 0) > 0]
    edge_sources = {e["source"] for e in network["edges"]}
    for sp in suppliers:
        assert sp["id"] in edge_sources, f"supplier {sp['id']} has flow_kbpd>0 but no outbound edges"


def test_every_port_has_at_least_one_shipping_route_inflow(network):
    """Regression test for a real bug hit while expanding the pooled
    'Other' supplier into 25 individual countries: port_haldia's only
    shipping_route inflow was e_other_haldia, and deleting the pooled
    node without replacing that specific inflow left the optimizer's
    port_throughput constraint for Haldia summing over zero edges —
    which Pyomo doesn't reject as infeasible, it crashes outright
    (InvalidConstraintError: trivial Boolean). A port with demand routed
    through it (via port_to_refinery) but no supply route feeding it is a
    silent way to break the solver, not just an ugly aggregate node."""
    ports = {n["id"] for n in network["nodes"] if n["type"] == "port"}
    fed_ports = {e["target"] for e in network["edges"] if e["type"] == "shipping_route"}
    unfed = ports - fed_ports
    assert not unfed, f"ports with zero shipping_route inflow: {unfed}"


def test_other_aggregate_supplier_is_gone_and_replaced_by_named_countries(network):
    """Independent-review request: 'can we separate each country in the
    nodes that combine 26 countries together so the network looks full?'
    — sup_other should no longer exist, and the 25 countries that used to
    be pooled into it (all but Hungary, which reported exactly 0 tonnes
    in the source data) should each be present as their own supplier node."""
    node_ids = {n["id"] for n in network["nodes"]}
    assert "sup_other" not in node_ids

    expected_countries = {
        "sup_egypt", "sup_colombia", "sup_brazil", "sup_qatar", "sup_oman", "sup_libya",
        "sup_mexico", "sup_malaysia", "sup_venezuela", "sup_congo_p", "sup_turkey", "sup_gabon",
        "sup_korea", "sup_ghana", "sup_brunei", "sup_uruguay", "sup_algeria", "sup_singapore",
        "sup_congo_d", "sup_argentina", "sup_panama", "sup_togo", "sup_canada", "sup_south_sudan",
        "sup_cameroon",
    }
    assert expected_countries <= node_ids, f"missing: {expected_countries - node_ids}"

    country_suppliers = [n for n in network["nodes"] if n["id"] in expected_countries]
    total_flow = sum(n["flow_kbpd"] for n in country_suppliers)
    total_import = sum(n.get("flow_kbpd", 0.0) for n in network["nodes"]
                        if n["type"] == "supplier" and n.get("subtype") != "domestic")
    # These 25 countries collectively carried sup_other's old 9.08% share —
    # confirm the total flow moved over intact, not silently dropped or
    # double-counted while splitting it up.
    share = total_flow / total_import
    assert 0.085 <= share <= 0.095, f"25-country share is {share:.4f}, expected ~0.0908 (sup_other's old share)"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
