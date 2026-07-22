"""
Layer 2 (part 1) — Scenario Engine.

Pure-Python disruption simulation over data/network.json. No solver here —
this answers "what does the raw network look like under a disruption"
(degraded edge capacities, per-refinery supply gap, days-of-cover) fast
enough for an interactive slider. The optimizer (optimizer.py) then asks
"given this degraded network, what's the best procurement response" —
that needs a solver because it's a reallocation problem, not just arithmetic.

Run standalone: python3 scenario_engine.py
"""
import json
from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "network.json"

# Named scenarios: (corridor_id, severity 0-1, human label, probability)
# Probabilities are illustrative planning assumptions (documented as such
# in the optimizer's meta output), not a geopolitical risk forecast.
SCENARIOS = {
    "baseline": {"corridor": None, "severity": 0.0, "label": "Baseline — no disruption", "probability": 0.55},
    "hormuz_50": {"corridor": "corridor_hormuz", "severity": 0.5, "label": "Strait of Hormuz — 50% capacity loss", "probability": 0.25},
    "hormuz_100": {"corridor": "corridor_hormuz", "severity": 1.0, "label": "Strait of Hormuz — full closure", "probability": 0.05},
    "redsea_suspend": {"corridor": "corridor_redsea_suez", "severity": 0.8, "label": "Red Sea / Suez — 80% suspension", "probability": 0.15},
}


def load_network(path: Path = DATA_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def degraded_capacity(edge: dict, corridor: str | None, severity: float) -> float:
    """
    Capacity of a shipping_route edge under a disruption. Non-shipping
    edges (pipelines, port-to-refinery, SPR links) are never chokepoint
    -exposed and pass through unchanged.

    Simplification (documented in SPEC.md / DATA_SOURCES.md): even if the
    edge has an alt_corridor on file, we degrade the SAME edge's capacity
    by severity * chokepoint_exposure rather than silently restoring it via
    the alternate route. The optimizer recovers volume by shifting flow to
    OTHER edges/suppliers with spare capacity — that reallocation, not a
    free reroute on the same edge, is the point of the exercise.
    """
    base = edge.get("capacity_kbpd", 0.0)
    if corridor is None or edge.get("type") != "shipping_route":
        return base
    if edge.get("via_corridor") != corridor:
        return base
    exposure = edge.get("chokepoint_exposure", 0.0)
    return base * max(0.0, 1.0 - severity * exposure)


def apply_scenario(network: dict, scenario_key: str) -> dict:
    """Returns a deep-ish copy of network['edges'] with capacities degraded,
    plus a summary of what was hit."""
    sc = SCENARIOS[scenario_key]
    corridor, severity = sc["corridor"], sc["severity"]

    degraded_edges = []
    lost_kbpd = 0.0
    for e in network["edges"]:
        new_cap = degraded_capacity(e, corridor, severity)
        e2 = dict(e)
        e2["capacity_kbpd_scenario"] = new_cap
        degraded_edges.append(e2)
        lost_kbpd += e.get("capacity_kbpd", 0.0) - new_cap

    return {
        "scenario": scenario_key,
        "label": sc["label"],
        "corridor": corridor,
        "severity": severity,
        "edges": degraded_edges,
        "total_capacity_lost_kbpd": round(lost_kbpd, 1),
    }


def refinery_supply_gap(network: dict, scenario_result: dict) -> list[dict]:
    """
    Rough (non-optimized) per-refinery supply picture: how much crude can
    physically still reach each refinery via port_to_refinery +
    domestic_pipeline edges, capped by the upstream port's still-available
    inbound capacity from suppliers. This is a capacity ceiling, not an
    optimized allocation — the optimizer decides the actual routing.
    """
    edges = scenario_result["edges"]
    nodes_by_id = {n["id"]: n for n in network["nodes"]}

    # Independent audit finding H1 (mirrored here from optimizer.py): a
    # port's inbound capacity isn't only shipping_route arrivals — two
    # domestic_pipeline edges (Mumbai offshore, Rajasthan) also terminate
    # at a port before continuing on to a refinery. Counting only
    # shipping_route inflow made this non-optimized snapshot understate
    # what a port can pass through, inflating refinery gaps (Mumbai in
    # particular) with an artifact rather than a real topology gap.
    port_inbound = {}
    for e in edges:
        if e["type"] in ("shipping_route", "domestic_pipeline") and nodes_by_id.get(e["target"], {}).get("type") == "port":
            port_inbound[e["target"]] = port_inbound.get(e["target"], 0.0) + e["capacity_kbpd_scenario"]

    results = []
    for n in network["nodes"]:
        if n["type"] != "refinery":
            continue
        reachable = 0.0
        for e in edges:
            if e["target"] != n["id"]:
                continue
            if e["type"] == "port_to_refinery":
                port_cap = port_inbound.get(e["source"], 0.0)
                reachable += min(e["capacity_kbpd_scenario"], port_cap)
            elif e["type"] == "domestic_pipeline":
                reachable += e["capacity_kbpd_scenario"]
        demand = n["capacity_kbpd"]
        gap = max(0.0, demand - reachable)
        results.append({
            "refinery": n["name"], "id": n["id"], "demand_kbpd": demand,
            "reachable_kbpd": round(reachable, 1), "gap_kbpd": round(gap, 1),
            "utilization_pct": round(100 * min(reachable, demand) / demand, 1) if demand else 0.0,
        })
    return sorted(results, key=lambda r: -r["gap_kbpd"])


def days_of_cover(network: dict, gap_kbpd_total: float) -> float | None:
    """SPR days of cover if drawing down at max combined rate against the
    aggregate national supply gap. Returns None if there's no gap.

    Independent audit finding L4: when gap_kbpd_total exceeds max_draw_kbpd
    (e.g. hormuz_100: 838 kbpd gap vs. 475 kbpd max SPR draw), this silently
    clamps effective_draw to max_draw_kbpd and reports "82.3 days of cover"
    with no indication that the SPR is only covering ~57% of the gap, not
    all of it. See coverage_fraction() below for the missing half of that
    picture — callers should report both together."""
    if gap_kbpd_total <= 0:
        return None
    spr_nodes = [n for n in network["nodes"] if n["type"] == "spr"]
    total_inventory_kbpd_equiv = sum(n["inventory_mmt"] * 1e6 * 7.33 / 1000 for n in spr_nodes)  # kb total
    max_draw_kbpd = sum(n["max_draw_rate_kbpd"] for n in spr_nodes)
    effective_draw = min(max_draw_kbpd, gap_kbpd_total)
    if effective_draw <= 0:
        return None
    return round(total_inventory_kbpd_equiv / effective_draw, 1)


def coverage_fraction(network: dict, gap_kbpd_total: float) -> float | None:
    """What fraction of the gap the SPR's max combined drawdown rate can
    actually serve (independent audit finding L4). 1.0 means the SPR can
    fully cover the gap at max draw; 0.57 means it can only physically
    supply 57% of what's missing, with the remainder unaddressed by SPR
    alone (needs spot purchases, demand curtailment, etc). Returns None
    if there's no gap to cover."""
    if gap_kbpd_total <= 0:
        return None
    spr_nodes = [n for n in network["nodes"] if n["type"] == "spr"]
    max_draw_kbpd = sum(n["max_draw_rate_kbpd"] for n in spr_nodes)
    if max_draw_kbpd <= 0:
        return 0.0
    return round(min(1.0, max_draw_kbpd / gap_kbpd_total), 3)


def summarize(scenario_key: str) -> dict:
    """
    Reports both the raw (unoptimized) refinery supply gap AND the gap
    net of whatever already exists in the baseline/no-disruption case.

    The raw gap includes a ~300 kbpd topology-completeness artifact present
    even at baseline (some real pipeline/rail connectivity into Panipat/
    Bathinda isn't modeled as a named edge — see KNOWN_LIMITATIONS.md). If
    we reported the raw number for every scenario, that artifact would ride
    along in every disruption result, making even a mild disruption look
    worse than it actually is. Reporting the INCREMENTAL gap (this
    scenario's raw gap minus baseline's raw gap, floored at 0) nets that
    artifact out and isolates what the disruption itself actually caused —
    which is the number that should drive days-of-cover and the headline
    metric. The raw gap is still returned for transparency, not hidden.
    """
    network = load_network()
    result = apply_scenario(network, scenario_key)
    gaps = refinery_supply_gap(network, result)
    total_gap = sum(g["gap_kbpd"] for g in gaps)

    if scenario_key == "baseline":
        baseline_total_gap = total_gap
    else:
        baseline_result = apply_scenario(network, "baseline")
        baseline_gaps = refinery_supply_gap(network, baseline_result)
        baseline_total_gap = sum(g["gap_kbpd"] for g in baseline_gaps)

    incremental_gap = max(0.0, total_gap - baseline_total_gap)
    cover = days_of_cover(network, incremental_gap)
    coverage = coverage_fraction(network, incremental_gap)
    return {
        "scenario": scenario_key,
        "label": result["label"],
        "total_capacity_lost_kbpd": result["total_capacity_lost_kbpd"],
        "total_refinery_gap_kbpd": round(total_gap, 1),
        "baseline_gap_kbpd": round(baseline_total_gap, 1),
        "incremental_gap_kbpd": round(incremental_gap, 1),
        "days_of_cover_if_unmitigated": cover,
        "spr_coverage_fraction": coverage,
        "worst_hit_refineries": gaps[:5],
    }


if __name__ == "__main__":
    for key in SCENARIOS:
        s = summarize(key)
        print(f"\n=== {s['label']} ===")
        print(f"  Corridor capacity lost: {s['total_capacity_lost_kbpd']:,.0f} kbpd")
        print(f"  Total refinery supply gap (unmitigated): {s['total_refinery_gap_kbpd']:,.0f} kbpd")
        print(f"  Days of cover if drawing max SPR against this gap: {s['days_of_cover_if_unmitigated']}")
        for r in s["worst_hit_refineries"]:
            if r["gap_kbpd"] > 0:
                print(f"    - {r['refinery']}: gap {r['gap_kbpd']:.0f} kbpd ({r['utilization_pct']:.0f}% served)")
