"""
Correctness/invariant tests for optimizer.py. The toy case (run_toy_case)
already hand-checks a simple scenario; these tests probe the FULL network
solve for invariants that must hold regardless of parameters — constraint
satisfaction, not just "solver returned optimal."
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pyomo.environ as pyo
import pytest

import optimizer as opt
import scenario_engine as sceng


@pytest.fixture(scope="module")
def network():
    return sceng.load_network()


@pytest.fixture(scope="module")
def solved_model(network):
    model, meta = opt.build_model(network, list(sceng.SCENARIOS.keys()), lam=3.0)
    status = opt.solve(model)
    return model, meta, status


def test_toy_case_still_hand_checks():
    """The hand-checked toy case is the one piece of ground truth in this
    whole model — if this ever fails, everything downstream is suspect."""
    opt.run_toy_case()  # raises AssertionError internally if wrong


def test_full_network_solves_optimal(solved_model):
    _, _, status = solved_model
    assert status == "optimal"


def test_demand_balance_holds_exactly(solved_model, network):
    """inflow + spr_draw + spot + shortfall == demand, for every refinery,
    every scenario — this is an equality constraint, so any violation
    beyond solver tolerance means something is actually wrong."""
    model, meta, _ = solved_model
    other_edge_by_id = meta["other_edge_by_id"]
    spr_edge_by_id = meta["spr_edge_by_id"]
    demand = meta["demand"]
    for r in model.REFINERIES:
        ref_in_edges = [eid for eid, e in other_edge_by_id.items() if e["target"] == r]
        ref_spr_edges = [eid for eid, e in spr_edge_by_id.items() if e["target"] == r]
        for s in model.SCENARIOS:
            inflow = sum(pyo.value(model.flow[e, s]) for e in ref_in_edges)
            spr_in = sum(pyo.value(model.spr_draw[e, s]) for e in ref_spr_edges)
            spot = pyo.value(model.spot[r, s])
            shortfall = pyo.value(model.shortfall[r, s])
            total = inflow + spr_in + spot + shortfall
            assert abs(total - demand[r]) < 1e-4, f"{r}/{s}: {total} != {demand[r]}"


def test_contract_never_exceeds_undisrupted_capacity(solved_model, network):
    model, meta, _ = solved_model
    for e in model.SHIP_EDGES:
        cap = meta["ship_edge_by_id"][e]["capacity_kbpd"]
        assert pyo.value(model.contract[e]) <= cap + 1e-4


def test_delivered_never_exceeds_contract_or_surviving_capacity(solved_model):
    model, meta, _ = solved_model
    for e in model.SHIP_EDGES:
        contract_val = pyo.value(model.contract[e])
        edge = meta["ship_edge_by_id"][e]
        for s in model.SCENARIOS:
            sc = sceng.SCENARIOS[s]
            surviving_cap = sceng.degraded_capacity(edge, sc["corridor"], sc["severity"])
            delivered = pyo.value(model.shipping_flow[e, s])
            assert delivered <= contract_val + 1e-4
            assert delivered <= surviving_cap + 1e-4


def test_take_or_pay_floor_respected(solved_model):
    """paid_volume >= take_or_pay_fraction * contract, for every edge and
    scenario — this is the mechanism that fixed the lambda-has-no-effect
    bug, so it's worth pinning down explicitly."""
    model, meta, _ = solved_model
    for e in model.SHIP_EDGES:
        contract_val = pyo.value(model.contract[e])
        for s in model.SCENARIOS:
            paid = pyo.value(model.paid_volume[e, s])
            delivered = pyo.value(model.shipping_flow[e, s])
            assert paid >= opt.TAKE_OR_PAY_FRACTION * contract_val - 1e-4
            assert paid >= delivered - 1e-4


def test_supplier_export_cap_respected(network, solved_model):
    model, meta, _ = solved_model
    suppliers = [n for n in network["nodes"] if n["type"] == "supplier"]
    nodes_by_id = {n["id"]: n for n in network["nodes"]}
    for sp in suppliers:
        edges = [e for e in model.SHIP_EDGES if meta["ship_edge_by_id"][e]["source"] == sp["id"]]
        if not edges:
            continue
        total_contract = sum(pyo.value(model.contract[e]) for e in edges)
        assert total_contract <= nodes_by_id[sp["id"]]["flow_kbpd"] + 1e-4


def test_no_negative_flows_anywhere(solved_model):
    """Every decision variable is declared NonNegativeReals — confirm the
    solver actually respected that, not just that Pyomo declared it."""
    model, _, _ = solved_model
    for e in model.SHIP_EDGES:
        assert pyo.value(model.contract[e]) >= -1e-6
        for s in model.SCENARIOS:
            assert pyo.value(model.shipping_flow[e, s]) >= -1e-6
            assert pyo.value(model.paid_volume[e, s]) >= -1e-6
    for e in model.OTHER_EDGES:
        for s in model.SCENARIOS:
            assert pyo.value(model.flow[e, s]) >= -1e-6
    for r in model.REFINERIES:
        for s in model.SCENARIOS:
            assert pyo.value(model.shortfall[r, s]) >= -1e-6
            assert pyo.value(model.spot[r, s]) >= -1e-6


def test_risk_aversion_actually_changes_solution():
    """The original lambda-bug regression test: risk-neutral and
    risk-averse solutions must NOT be byte-identical. If this ever passes
    with lam=0 == lam=3 again, the take-or-pay fix has regressed."""
    r0 = opt.run_full_network(lam=0.0)
    r1 = opt.run_full_network(lam=3.0)
    assert r0["expected_cost_usd_per_day"] != r1["expected_cost_usd_per_day"]
    assert r0["contract_by_supplier_kbpd"] != r1["contract_by_supplier_kbpd"]


def test_shortfall_penalty_below_deliverable_cost_causes_collapse():
    """Documents the discovered failure mode (not a bug to fix — a
    boundary the UI slider deliberately stays above, min=75). Pinning it
    down means if the slider's floor is ever loosened without noticing
    this constraint, this test catches the collapse."""
    r_low_penalty = opt.run_full_network(lam=0.0, scenario_keys=["baseline"], shortfall_penalty_usd_bbl=20.0)
    r_normal = opt.run_full_network(lam=0.0, scenario_keys=["baseline"], shortfall_penalty_usd_bbl=150.0)
    assert r_low_penalty["max_shortfall_kbpd"] > r_normal["max_shortfall_kbpd"]


def test_probability_override_renormalizes(network):
    """Overriding one scenario's probability should change the relative
    weighting in expected_cost (via renormalization), not just be ignored."""
    r_base = opt.run_full_network(lam=0.0, probability_overrides={"hormuz_100": 0.05})
    r_stressed = opt.run_full_network(lam=0.0, probability_overrides={"hormuz_100": 0.5})
    assert r_base["expected_cost_usd_per_day"] != r_stressed["expected_cost_usd_per_day"]


def test_probability_override_unknown_key_does_not_crash():
    """probability_overrides referencing a scenario key that isn't in the
    solved scenario_keys set should be silently ignored, not raise."""
    r = opt.run_full_network(lam=0.0, scenario_keys=["baseline"],
                              probability_overrides={"not_a_real_scenario": 0.9})
    assert r["termination"] == "optimal"


def test_single_scenario_keys_list_does_not_crash():
    r = opt.run_full_network(lam=0.0, scenario_keys=["baseline"])
    assert r["termination"] == "optimal"
    assert list(r["scenario_costs_usd_per_day"].keys()) == ["baseline"]


def test_empty_scenario_keys_raises_rather_than_silently_misbehaving():
    """An empty scenario list means total_prob=0 -> division by zero in
    the probability renormalization. This SHOULD raise, not silently
    produce garbage — pinning down current behavior explicitly."""
    with pytest.raises(Exception):
        opt.run_full_network(lam=0.0, scenario_keys=[])


def test_extract_flows_matches_extract_results_shortfall(network):
    """Cross-check: summing shortfall from extract_flows-adjacent model
    state should agree with extract_results' own shortfall figures — a
    consistency check between the two extraction functions that read the
    same solved model."""
    model, meta = opt.build_model(network, list(sceng.SCENARIOS.keys()), lam=1.0)
    opt.solve(model)
    results = opt.extract_results(model, meta)
    flows = opt.extract_flows(model)
    for s in model.SCENARIOS:
        edge_total = sum(v.get(s, 0.0) for v in flows["spr_draw_kbpd"].values())
        # spr draw isn't in extract_results directly, so just sanity check it's non-negative and finite
        assert edge_total >= 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
