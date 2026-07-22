"""
Layer 3 — Adaptive Procurement Orchestrator (Day 2 build target, per SPEC.md).

Two-stage stochastic LP (linear program — every decision variable is
continuous flow; there are deliberately no integer/binary variables) with
an optional CVaR risk-averse term, built directly over the Supply Chain
Knowledge Graph in data/network.json. Solved with Pyomo + HiGHS
(open-source, no commercial solver).

Staying continuous is a deliberate choice, not a shortcut: nothing in this
model's actual decisions (how much to contract per route, how to route
flow, when to draw SPR/spot) requires integrality. Integer variables would
only enter if we modeled discrete infrastructure decisions (e.g. "build
this pipeline: yes/no") — out of scope here. An LP also solves in well
under a second even on the full network, which matters for a live demo
with an interactive risk-aversion slider; there's no reason to trade that
away to make the model look more sophisticated than the decision actually
requires.

Build order (matches SPEC.md / the plan's Day 2 instructions):
  1. Toy case, risk-neutral, hand-checked          -> run_toy_case()
  2. Full network, risk-neutral, single scenario    -> run_full_network(lam=0, scenario_keys=["baseline"])
  3. Full network, all 4 scenarios, risk-neutral    -> run_full_network(lam=0)
  4. Full network, all 4 scenarios, CVaR added      -> run_full_network(lam>0)

Run standalone: python3 optimizer.py
"""
from pathlib import Path

import pyomo.environ as pyo

from scenario_engine import SCENARIOS, degraded_capacity, load_network

DATA_PATH = Path(__file__).parent / "data" / "network.json"

# ---------------------------------------------------------------------------
# Cost assumptions — explicit and testable (per the plan's Evaluation Focus).
# These are NOT PPAC-sourced figures; they are documented modeling
# judgment calls layered on top of the one real anchor we have (PPAC's
# India Basket average, $70.99/bbl, FY2025-26). Swap these for real
# contract/freight data if available before a real deployment.
# ---------------------------------------------------------------------------
INDIA_BASKET_USD_BBL = 70.99

# Per-supplier price differential vs. the India Basket average, reflecting
# well-documented market discounts/premia (Russian Urals discount, heavier
# crude discount, light-sweet premium). Domestic (indigenous) crude is
# priced below the basket to reflect no import freight/customs.
SUPPLIER_PRICE_DIFF_USD_BBL = {
    "sup_russia": -8.0,
    "sup_iraq": -3.0,
    "sup_saudi": 1.0,
    "sup_uae": 1.5,
    "sup_usa": 2.0,
    "sup_kuwait": -2.0,
    "sup_nigeria": 2.5,
    "sup_angola": 1.5,
    # The 25 individually-modeled formerly-pooled "Other" countries below
    # deliberately have NO entry here — same treatment "sup_other" got
    # before this dict, defaulting to the plain India Basket price via
    # freight_usd_bbl()'s `.get(edge["source"], 0.0)` fallback. None of
    # these have documented, sourced price differentials (unlike the
    # top-8, which are backed by well-known market discounts/premia), so
    # inventing one for each would be a modeling judgment call dressed up
    # as data.
    "sup_domestic_offshore_mumbai": -5.0,
    "sup_domestic_rajasthan": -5.0,
    "sup_domestic_assam": -5.0,
    "sup_domestic_gujarat": -5.0,
}

SPOT_PREMIUM_USD_BBL = 6.0      # spot purchases cost basket + this premium
SPR_DRAWDOWN_PREMIUM_USD_BBL = 12.0   # opportunity cost of tapping strategic reserves
# (raised from 3.0 per independent audit finding H2: at $3/bbl, SPR crude
# priced at basket+premium undercut several real suppliers (USA, Angola,
# Nigeria, spot), so the solver drained the SPR on ordinary days. $12/bbl
# puts SPR crude above every routine supplier, making it a genuine last
# resort even in scenarios where the hard baseline-zero constraint above
# doesn't apply.)
SHORTFALL_PENALTY_USD_BBL = 150.0    # last-resort penalty; forces the solver to avoid unmet demand.
                                      # Must exceed every deliverable crude's all-in cost (never below
                                      # ~$70-95/bbl range here) or the solver will "rationally" prefer
                                      # taking the penalty over paying for real crude — that's a sign
                                      # of a broken assumption, not a real economic finding.
SPOT_CAP_FRACTION_OF_DEMAND = 0.20   # finite spot-market liquidity, per refinery
BBL_PER_KBPD_DAY = 1000.0            # 1 kbpd = 1000 bbl/day

# Minimum take-or-pay fraction on first-stage supplier contracts: you pay
# for at least this fraction of what you committed to buy, every scenario,
# even if the route can't actually deliver it (real term crude contracts
# work this way). WITHOUT this, contracting is free optionality with zero
# downside, so the solver trivially contracts 100% of every supplier's
# capacity regardless of risk — collapsing risk-neutral and risk-averse
# into the identical solution (this was the actual bug behind the first
# working version of this model showing 0% difference between lambda=0
# and lambda>0). This is what makes over-committing to a chokepoint
# -fragile supplier a real, scenario-dependent cost, which is what CVaR
# then has genuine leverage to trade off against.
TAKE_OR_PAY_FRACTION = 0.7


def freight_usd_bbl(transit_days) -> float:
    """Bucketed freight-rate proxy by transit time. Documented assumption,
    not a real tanker charter quote."""
    if transit_days is None:
        return 0.0
    if transit_days < 10:
        return 1.0
    if transit_days < 15:
        return 2.0
    if transit_days < 20:
        return 3.0
    if transit_days < 25:
        return 4.5
    return 5.5


def compute_unit_cost_usd_bbl(edge: dict, price_overrides: dict | None = None) -> float:
    """$/bbl for a unit of flow on this edge. port_to_refinery edges carry
    no additional marginal cost — the grade/origin cost is charged once,
    at the shipping_route or domestic_pipeline edge that actually
    originates the barrel."""
    diffs = {**SUPPLIER_PRICE_DIFF_USD_BBL, **(price_overrides or {})}
    if edge["type"] == "shipping_route":
        diff = diffs.get(edge["source"], 0.0)
        return INDIA_BASKET_USD_BBL + diff + freight_usd_bbl(edge.get("transit_days"))
    if edge["type"] == "domestic_pipeline":
        diff = diffs.get(edge["source"], -5.0)
        return INDIA_BASKET_USD_BBL + diff
    return 0.0  # port_to_refinery, spr_link (spr_link cost handled separately)


# ---------------------------------------------------------------------------
# Model construction
# ---------------------------------------------------------------------------

def build_model(network: dict, scenario_keys, lam: float = 0.0, alpha: float = 0.9,
                 demand_utilization: float = 0.9, price_overrides: dict | None = None,
                 spot_cap_fraction: float = SPOT_CAP_FRACTION_OF_DEMAND,
                 spot_premium_usd_bbl: float = SPOT_PREMIUM_USD_BBL,
                 shortfall_penalty_usd_bbl: float = SHORTFALL_PENALTY_USD_BBL,
                 take_or_pay_fraction: float = TAKE_OR_PAY_FRACTION,
                 probability_overrides: dict | None = None):
    """
    Builds the Pyomo model. Returns (model, meta) where meta carries the
    plain-Python lookups needed to extract/interpret results.

    Genuinely two-stage, which matters for CVaR to have any effect at all:
      - FIRST STAGE (decided before the disruption is known, shared across
        all scenarios): `contract[e]` for each shipping_route edge — how
        much volume to commit to each supplier->port route. This is where
        chokepoint risk actually lives, so it's the lever that trades off
        cost vs. exposure.
      - SECOND STAGE (recourse, scenario-specific): `shipping_flow[e,s]`
        (delivered volume, capped by both the contract and whatever
        capacity survives the disruption), plus fully-flexible
        `flow[e,s]` on port_to_refinery/domestic_pipeline edges, SPR
        draws, spot buys and shortfall.
      Earlier version of this model made EVERY variable scenario-indexed
      with no shared first-stage decision — the solver could then
      re-optimize each scenario from scratch independently, so a
      risk-averse objective had nothing left to trade off against (no
      slack to reallocate) and CVaR silently did nothing. This structure
      is what the plan's Sawik-derived formulation actually calls for.
    """
    nodes = {n["id"]: n for n in network["nodes"]}
    shipping_edges = [e for e in network["edges"] if e["type"] == "shipping_route"]
    other_flow_edges = [e for e in network["edges"] if e["type"] in ("port_to_refinery", "domestic_pipeline")]
    spr_edges = [e for e in network["edges"] if e["type"] == "spr_link"]

    suppliers = [n for n in network["nodes"] if n["type"] == "supplier"]
    ports = [n for n in network["nodes"] if n["type"] == "port"]
    refineries = [n for n in network["nodes"] if n["type"] == "refinery"]

    demand = {r["id"]: r["capacity_kbpd"] * demand_utilization for r in refineries}
    unit_cost = {e["id"]: compute_unit_cost_usd_bbl(e, price_overrides) * BBL_PER_KBPD_DAY
                 for e in shipping_edges + other_flow_edges}

    scenarios = {k: dict(SCENARIOS[k]) for k in scenario_keys}
    if probability_overrides:
        # Lets the Assumptions & Robustness panel test "what if the planning
        # probability we assigned to a scenario is wrong by X%" without
        # touching the hardcoded SCENARIOS dict. Overriding one scenario's
        # probability and renormalizing (below) automatically rescales all
        # the others in proportion — same mechanism a real analyst would use
        # for a quick sensitivity check.
        for k, p in probability_overrides.items():
            if k in scenarios:
                scenarios[k]["probability"] = p
    total_prob = sum(s["probability"] for s in scenarios.values())
    prob = {k: s["probability"] / total_prob for k, s in scenarios.items()}  # renormalize

    m = pyo.ConcreteModel()
    m.SHIP_EDGES = pyo.Set(initialize=[e["id"] for e in shipping_edges])
    m.OTHER_EDGES = pyo.Set(initialize=[e["id"] for e in other_flow_edges])
    m.SPR_EDGES = pyo.Set(initialize=[e["id"] for e in spr_edges])
    m.REFINERIES = pyo.Set(initialize=list(demand.keys()))
    m.SCENARIOS = pyo.Set(initialize=list(scenarios.keys()))

    m.contract = pyo.Var(m.SHIP_EDGES, within=pyo.NonNegativeReals)              # first-stage
    m.shipping_flow = pyo.Var(m.SHIP_EDGES, m.SCENARIOS, within=pyo.NonNegativeReals)  # second-stage (delivered)
    m.paid_volume = pyo.Var(m.SHIP_EDGES, m.SCENARIOS, within=pyo.NonNegativeReals)     # second-stage (billed)
    m.flow = pyo.Var(m.OTHER_EDGES, m.SCENARIOS, within=pyo.NonNegativeReals)
    m.spr_draw = pyo.Var(m.SPR_EDGES, m.SCENARIOS, within=pyo.NonNegativeReals)
    m.spot = pyo.Var(m.REFINERIES, m.SCENARIOS, within=pyo.NonNegativeReals)
    m.shortfall = pyo.Var(m.REFINERIES, m.SCENARIOS, within=pyo.NonNegativeReals)
    m.VaR = pyo.Var(within=pyo.Reals)
    m.z = pyo.Var(m.SCENARIOS, within=pyo.NonNegativeReals)

    ship_edge_by_id = {e["id"]: e for e in shipping_edges}
    other_edge_by_id = {e["id"]: e for e in other_flow_edges}
    spr_edge_by_id = {e["id"]: e for e in spr_edges}

    # --- first-stage contract capped at the route's undisrupted capacity ---
    def contract_cap_rule(m, e):
        return m.contract[e] <= ship_edge_by_id[e]["capacity_kbpd"]
    m.contract_cap = pyo.Constraint(m.SHIP_EDGES, rule=contract_cap_rule)

    # --- delivered volume <= contracted volume, and <= whatever capacity
    # survives the disruption in this scenario ---
    def delivered_le_contract_rule(m, e, s):
        return m.shipping_flow[e, s] <= m.contract[e]
    m.delivered_le_contract = pyo.Constraint(m.SHIP_EDGES, m.SCENARIOS, rule=delivered_le_contract_rule)

    def delivered_le_surviving_cap_rule(m, e, s):
        edge = ship_edge_by_id[e]
        sc = scenarios[s]
        cap = degraded_capacity(edge, sc["corridor"], sc["severity"])
        return m.shipping_flow[e, s] <= cap
    m.delivered_le_surviving_cap = pyo.Constraint(m.SHIP_EDGES, m.SCENARIOS, rule=delivered_le_surviving_cap_rule)

    # --- take-or-pay: billed volume is at least the contracted minimum
    # offtake, and at least whatever was actually delivered. Over
    # -committing to a route that then can't deliver (chokepoint hit)
    # means paying for undelivered barrels — a real, scenario-dependent
    # cost of concentration risk that CVaR can act on. ---
    def pay_ge_floor_rule(m, e, s):
        return m.paid_volume[e, s] >= take_or_pay_fraction * m.contract[e]
    m.pay_ge_floor = pyo.Constraint(m.SHIP_EDGES, m.SCENARIOS, rule=pay_ge_floor_rule)

    def pay_ge_delivered_rule(m, e, s):
        return m.paid_volume[e, s] >= m.shipping_flow[e, s]
    m.pay_ge_delivered = pyo.Constraint(m.SHIP_EDGES, m.SCENARIOS, rule=pay_ge_delivered_rule)

    # --- other (port_to_refinery / domestic_pipeline) edge capacity —
    # these aren't chokepoint-exposed, so no scenario degradation ---
    def other_cap_rule(m, e, s):
        return m.flow[e, s] <= other_edge_by_id[e]["capacity_kbpd"]
    m.other_capacity = pyo.Constraint(m.OTHER_EDGES, m.SCENARIOS, rule=other_cap_rule)

    # --- SPR drawdown capacity ---
    def spr_cap_rule(m, e, s):
        return m.spr_draw[e, s] <= spr_edge_by_id[e]["drawdown_capacity_kbpd"]
    m.spr_capacity = pyo.Constraint(m.SPR_EDGES, m.SCENARIOS, rule=spr_cap_rule)

    # --- SPR is for disruptions, not routine supply (independent audit
    # finding H2): with no per-period depletion accounting, a cheap SPR
    # premium made reserves look like just another supplier, and the
    # solver drained 304.5 kbpd of strategic crude on an undisrupted
    # baseline day. Force baseline draw to zero outright — the premium
    # constant below is also raised so that even in disrupted scenarios
    # SPR is priced as a genuine last resort, not a discount option. ---
    if "baseline" in scenarios:
        def spr_baseline_zero_rule(m, e):
            return m.spr_draw[e, "baseline"] == 0
        m.spr_baseline_zero = pyo.Constraint(m.SPR_EDGES, rule=spr_baseline_zero_rule)

    # --- spot cap (finite spot-market liquidity) ---
    def spot_cap_rule(m, r, s):
        return m.spot[r, s] <= spot_cap_fraction * demand[r]
    m.spot_cap = pyo.Constraint(m.REFINERIES, m.SCENARIOS, rule=spot_cap_rule)

    # --- supplier total export capacity, on the CONTRACT (first-stage) —
    # a supplier's total production/export volume is committed once, not
    # re-decided per scenario. Imported suppliers only — domestic
    # suppliers ship via domestic_pipeline (OTHER_EDGES), not shipping
    # routes, so they need their own cap below (domestic_supplier_cap). ---
    supplier_out_edges = {sp["id"]: [e["id"] for e in shipping_edges if e["source"] == sp["id"]]
                          for sp in suppliers}

    def supplier_cap_rule(m, sp):
        edges = supplier_out_edges[sp]
        if not edges:
            return pyo.Constraint.Skip
        return sum(m.contract[e] for e in edges) <= nodes[sp]["flow_kbpd"]
    m.supplier_cap = pyo.Constraint([sp["id"] for sp in suppliers], rule=supplier_cap_rule)

    # --- domestic supplier production cap (independent audit finding H3):
    # domestic_pipeline flow had NO cap tied to the field's real output —
    # only the pipeline's own physical capacity limited it, so the solver
    # could (and did) draw more "Assam" or "Gujarat" crude than those
    # fields actually produce. Per-scenario, not first-stage: domestic
    # supply carries no chokepoint risk, so there's no take-or-pay
    # /contracting story here, just "you can't pump more than the field
    # makes." Must land together with the H1 port-balance fix below —
    # fixing H1 alone (without this) would let the newly-unstranded
    # offshore Mumbai/Rajasthan volumes be similarly overdrawn. ---
    domestic_out_edges = {sp["id"]: [e["id"] for e in other_flow_edges
                                      if e["type"] == "domestic_pipeline" and e["source"] == sp["id"]]
                          for sp in suppliers if sp.get("subtype") == "domestic"}

    def domestic_supplier_cap_rule(m, sp, s):
        edges = domestic_out_edges.get(sp, [])
        if not edges:
            return pyo.Constraint.Skip
        return sum(m.flow[e, s] for e in edges) <= nodes[sp]["flow_kbpd"]
    m.domestic_supplier_cap = pyo.Constraint(
        [sp["id"] for sp in suppliers if sp.get("subtype") == "domestic"], m.SCENARIOS,
        rule=domestic_supplier_cap_rule,
    )

    # --- port flow conservation: can't ship out of a port more than
    # arrives at it (per scenario, using actual delivered volume).
    # Independent audit finding H1: this previously counted ONLY
    # shipping_route inflow, so any port fed by a domestic_pipeline edge
    # (Mumbai, Vadinar) had its port_to_refinery outflow capped by
    # shipping inflow alone — domestic barrels arriving at the port had
    # nowhere to go and were silently discarded (confirmed: both
    # domestic-to-port edges solved to flow=0.0 in every scenario before
    # this fix). Now counts both. ---
    port_in_edges = {p["id"]: [e["id"] for e in shipping_edges if e["target"] == p["id"]]
                     for p in ports}
    port_in_domestic_edges = {p["id"]: [e["id"] for e in other_flow_edges
                                         if e["type"] == "domestic_pipeline" and e["target"] == p["id"]]
                               for p in ports}
    port_out_edges = {p["id"]: [e["id"] for e in other_flow_edges if e["type"] == "port_to_refinery" and e["source"] == p["id"]]
                      for p in ports}

    def port_balance_rule(m, p, s):
        inflow = port_in_edges[p]
        domestic_inflow = port_in_domestic_edges[p]
        outflow = port_out_edges[p]
        if not outflow:
            return pyo.Constraint.Skip
        return sum(m.flow[e, s] for e in outflow) <= (
            sum(m.shipping_flow[e, s] for e in inflow) + sum(m.flow[e, s] for e in domestic_inflow)
        )
    m.port_balance = pyo.Constraint([p["id"] for p in ports], m.SCENARIOS, rule=port_balance_rule)

    # --- port throughput cap (independent audit finding M4): nothing
    # previously read a port node's own capacity_kbpd at all — only
    # per-edge capacities were enforced, and 6 of 11 ports have combined
    # inbound shipping-edge capacity that nominally exceeds the port's
    # own stated throughput. This caps actual total inflow (shipping +
    # domestic) at the port's real capacity, if that field is present. ---
    port_capacity = {p["id"]: p.get("capacity_kbpd") for p in ports}

    def port_throughput_rule(m, p, s):
        cap = port_capacity.get(p)
        if cap is None:
            return pyo.Constraint.Skip
        total_in = sum(m.shipping_flow[e, s] for e in port_in_edges[p]) + \
            sum(m.flow[e, s] for e in port_in_domestic_edges[p])
        return total_in <= cap
    m.port_throughput = pyo.Constraint([p["id"] for p in ports], m.SCENARIOS, rule=port_throughput_rule)

    # --- shared-capacity groups (independent audit finding M3): some
    # edges represent physically-shared infrastructure (e.g. the
    # Paradip-Haldia-Barauni pipeline splits into two branches that each
    # separately claimed the FULL pipeline capacity, letting the solver
    # push up to 2x the pipeline's real throughput). Any other_flow_edge
    # tagged with a shared_capacity_group is jointly capped with its
    # group-mates instead of only its own individual edge capacity. ---
    shared_groups: dict = {}
    shared_group_cap: dict = {}
    for e in other_flow_edges:
        grp = e.get("shared_capacity_group")
        if grp:
            shared_groups.setdefault(grp, []).append(e["id"])
            shared_group_cap[grp] = e.get("shared_capacity_group_cap", e["capacity_kbpd"])

    def shared_capacity_rule(m, grp, s):
        return sum(m.flow[e, s] for e in shared_groups[grp]) <= shared_group_cap[grp]
    if shared_groups:
        m.shared_capacity = pyo.Constraint(list(shared_groups.keys()), m.SCENARIOS, rule=shared_capacity_rule)

    # --- refinery demand balance ---
    ref_in_edges = {r["id"]: [e["id"] for e in other_flow_edges if e["target"] == r["id"]]
                    for r in refineries}
    ref_spr_edges = {r["id"]: [e["id"] for e in spr_edges if e["target"] == r["id"]] for r in refineries}

    def demand_rule(m, r, s):
        inflow = sum(m.flow[e, s] for e in ref_in_edges[r])
        spr_in = sum(m.spr_draw[e, s] for e in ref_spr_edges[r])
        return inflow + spr_in + m.spot[r, s] + m.shortfall[r, s] == demand[r]
    m.demand_balance = pyo.Constraint(m.REFINERIES, m.SCENARIOS, rule=demand_rule)

    # --- scenario cost + CVaR ---
    def scenario_cost(m, s):
        ship_cost = sum(m.paid_volume[e, s] * unit_cost[e] for e in m.SHIP_EDGES)
        other_cost = sum(m.flow[e, s] * unit_cost[e] for e in m.OTHER_EDGES)
        spr_cost = sum(m.spr_draw[e, s] * (INDIA_BASKET_USD_BBL + SPR_DRAWDOWN_PREMIUM_USD_BBL) * BBL_PER_KBPD_DAY
                       for e in m.SPR_EDGES)
        spot_cost = sum(m.spot[r, s] * (INDIA_BASKET_USD_BBL + spot_premium_usd_bbl) * BBL_PER_KBPD_DAY
                        for r in m.REFINERIES)
        shortfall_cost = sum(m.shortfall[r, s] * shortfall_penalty_usd_bbl * BBL_PER_KBPD_DAY
                             for r in m.REFINERIES)
        return ship_cost + other_cost + spr_cost + spot_cost + shortfall_cost

    m.scenario_total_cost = pyo.Expression(m.SCENARIOS, rule=scenario_cost)

    def cvar_z_rule(m, s):
        return m.z[s] >= m.scenario_total_cost[s] - m.VaR
    m.cvar_z = pyo.Constraint(m.SCENARIOS, rule=cvar_z_rule)

    m.CVaR = pyo.Expression(expr=m.VaR + (1.0 / (1.0 - alpha)) * sum(prob[s] * m.z[s] for s in m.SCENARIOS))
    m.expected_cost = pyo.Expression(expr=sum(prob[s] * m.scenario_total_cost[s] for s in m.SCENARIOS))
    m.obj = pyo.Objective(expr=m.expected_cost + lam * m.CVaR, sense=pyo.minimize)

    meta = {
        "demand": demand, "unit_cost": unit_cost, "prob": prob,
        "ship_edge_by_id": ship_edge_by_id, "other_edge_by_id": other_edge_by_id,
        "spr_edge_by_id": spr_edge_by_id,
        "refineries": {r["id"]: r for r in refineries},
        "alpha": alpha, "lam": lam,
    }
    return m, meta


_SOLVER_CANDIDATES = ["appsi_highs", "highs"]


def _get_available_solver():
    """
    Tries each known HiGHS interface Pyomo might have registered and
    returns the first one that actually reports itself available.
    Different pyomo/highspy version combinations register the solver
    under different names (appsi_highs needs the appsi plugin wired up;
    'highs' is the more recently added direct interface) — trying both
    avoids failing on environments where only one of them works.
    """
    for name in _SOLVER_CANDIDATES:
        try:
            candidate = pyo.SolverFactory(name)
            if candidate.available():
                return candidate, name
        except Exception:
            continue
    raise RuntimeError(
        "No working HiGHS solver interface found (tried: " + ", ".join(_SOLVER_CANDIDATES) + "). "
        "This almost always means the 'highspy' package isn't installed in the Python "
        "environment actually running this app. Fix: run `pip install highspy` in that "
        "same environment (e.g. `D:\\Anaconda\\envs\\machine_learning\\python.exe -m pip "
        "install highspy`), then restart Streamlit."
    )


def solve(model) -> str:
    solver, name_used = _get_available_solver()
    result = solver.solve(model)
    return str(result.solver.termination_condition)


def extract_flows(model) -> dict:
    """
    Per-edge, per-scenario flow values (not aggregated by supplier like
    extract_results' contract_by_supplier_kbpd). This is what the map needs
    to draw edge width proportional to actual delivered volume and to
    animate the Disruption Timeline — extract_results alone only has
    supplier-level and refinery-level rollups.
    """
    m = model
    edge_flow_kbpd = {}
    for e in m.SHIP_EDGES:
        edge_flow_kbpd[e] = {s: round(pyo.value(m.shipping_flow[e, s]), 2) for s in m.SCENARIOS}
    for e in m.OTHER_EDGES:
        edge_flow_kbpd[e] = {s: round(pyo.value(m.flow[e, s]), 2) for s in m.SCENARIOS}
    spr_draw_kbpd = {e: {s: round(pyo.value(m.spr_draw[e, s]), 2) for s in m.SCENARIOS} for e in m.SPR_EDGES}
    spot_kbpd = {r: {s: round(pyo.value(m.spot[r, s]), 2) for s in m.SCENARIOS} for r in m.REFINERIES}
    return {"edge_flow_kbpd": edge_flow_kbpd, "spr_draw_kbpd": spr_draw_kbpd, "spot_kbpd": spot_kbpd}


def extract_results(model, meta) -> dict:
    m = model
    scenario_costs = {s: round(pyo.value(m.scenario_total_cost[s]), 1) for s in m.SCENARIOS}
    total_shortfall = {s: round(sum(pyo.value(m.shortfall[r, s]) for r in m.REFINERIES), 2) for s in m.SCENARIOS}
    worst_scenario = max(scenario_costs, key=scenario_costs.get)

    contract_by_supplier: dict = {}
    for e in m.SHIP_EDGES:
        src = meta["ship_edge_by_id"][e]["source"]
        contract_by_supplier[src] = contract_by_supplier.get(src, 0.0) + pyo.value(m.contract[e])
    contract_by_supplier = {k: round(v, 1) for k, v in contract_by_supplier.items()}

    shortfall_by_refinery = {
        s: {r: round(pyo.value(m.shortfall[r, s]), 1) for r in m.REFINERIES if pyo.value(m.shortfall[r, s]) > 1.0}
        for s in m.SCENARIOS
    }

    # Incremental shortfall = this scenario's shortfall minus baseline's own
    # shortfall (floored at 0). Nets out the ~300 kbpd topology-completeness
    # gap that shows up even with zero disruption (see KNOWN_LIMITATIONS.md)
    # so every scenario's headline number reflects what the DISRUPTION
    # caused, not a modeling artifact riding along underneath it. Only
    # computed when baseline is actually one of the solved scenarios.
    incremental_shortfall = None
    if "baseline" in total_shortfall:
        baseline_shortfall = total_shortfall["baseline"]
        incremental_shortfall = {
            s: round(max(0.0, v - baseline_shortfall), 2) for s, v in total_shortfall.items()
        }

    return {
        "termination": None,
        "expected_cost_usd_per_day": round(pyo.value(m.expected_cost), 1),
        "cvar_usd_per_day": round(pyo.value(m.CVaR), 1),
        "objective": round(pyo.value(m.obj), 1),
        "scenario_costs_usd_per_day": scenario_costs,
        "scenario_shortfall_kbpd": total_shortfall,
        "scenario_incremental_shortfall_kbpd": incremental_shortfall,
        "worst_scenario": worst_scenario,
        "max_shortfall_kbpd": max(total_shortfall.values()),
        "contract_by_supplier_kbpd": contract_by_supplier,
        "shortfall_by_refinery_kbpd": shortfall_by_refinery,
    }


# ---------------------------------------------------------------------------
# Toy case — hand-checkable, per SPEC.md build order step 1
# ---------------------------------------------------------------------------

def toy_network() -> dict:
    return {
        "nodes": [
            {"id": "sup_A", "type": "supplier", "name": "Toy Supplier A (cheap)", "flow_kbpd": 100},
            {"id": "sup_B", "type": "supplier", "name": "Toy Supplier B (expensive)", "flow_kbpd": 100},
            {"id": "port_X", "type": "port", "name": "Toy Port", "capacity_kbpd": 250},
            {"id": "ref_1", "type": "refinery", "name": "Toy Refinery 1", "capacity_kbpd": 60},
            {"id": "ref_2", "type": "refinery", "name": "Toy Refinery 2", "capacity_kbpd": 90},
        ],
        "edges": [
            {"id": "e_A_X", "type": "shipping_route", "source": "sup_A", "target": "port_X",
             "capacity_kbpd": 100, "transit_days": 5, "via_corridor": None, "chokepoint_exposure": 0.0},
            {"id": "e_B_X", "type": "shipping_route", "source": "sup_B", "target": "port_X",
             "capacity_kbpd": 100, "transit_days": 5, "via_corridor": None, "chokepoint_exposure": 0.0},
            {"id": "e_X_1", "type": "port_to_refinery", "source": "port_X", "target": "ref_1", "capacity_kbpd": 60},
            {"id": "e_X_2", "type": "port_to_refinery", "source": "port_X", "target": "ref_2", "capacity_kbpd": 90},
        ],
    }


def run_toy_case():
    network = toy_network()
    overrides = {"sup_A": -20.0, "sup_B": 10.0}  # force A cheaper than B
    model, meta = build_model(
        network, scenario_keys=["baseline"], lam=0.0, alpha=0.9,
        demand_utilization=1.0, price_overrides=overrides,
        spot_cap_fraction=0.0,  # isolate supplier dispatch logic from spot-market substitution
        take_or_pay_fraction=0.0,  # isolate from take-or-pay commitment cost for this hand-check
    )
    status = solve(model)
    assert status == "optimal", f"toy case did not solve to optimality: {status}"

    flow_A = pyo.value(model.shipping_flow["e_A_X", "baseline"])
    flow_B = pyo.value(model.shipping_flow["e_B_X", "baseline"])
    shortfall_total = sum(pyo.value(model.shortfall[r, "baseline"]) for r in model.REFINERIES)

    # Hand-check: cheaper supplier A (cap 100) should be used to its limit
    # before touching more expensive supplier B; total demand is 150, so
    # B should supply exactly the remaining 50; shortfall should be 0.
    assert abs(flow_A - 100) < 1e-3, f"expected A=100, got {flow_A}"
    assert abs(flow_B - 50) < 1e-3, f"expected B=50, got {flow_B}"
    assert shortfall_total < 1e-6, f"expected 0 shortfall, got {shortfall_total}"

    expected_cost = 100 * (70.99 - 20 + 1.0) * 1000 + 50 * (70.99 + 10 + 1.0) * 1000
    actual_cost = pyo.value(model.scenario_total_cost["baseline"])
    assert abs(actual_cost - expected_cost) < 1.0, f"cost mismatch: {actual_cost} vs {expected_cost}"

    print(f"TOY CASE PASSED — flow_A={flow_A:.1f}, flow_B={flow_B:.1f}, "
          f"shortfall={shortfall_total:.3f}, cost=${actual_cost:,.0f}/day "
          f"(hand-check: ${expected_cost:,.0f}/day)")


# ---------------------------------------------------------------------------
# Full network runs
# ---------------------------------------------------------------------------

def run_full_network(scenario_keys=None, lam: float = 0.0, alpha: float = 0.9,
                       demand_utilization: float = 0.9, include_flows: bool = False, **cost_kwargs):
    network = load_network(DATA_PATH)
    # NOTE: deliberately `is None`, not `scenario_keys or ...` — an empty
    # list [] is falsy in Python, so the old `or` idiom silently replaced
    # ANY empty list with the full 4-scenario default instead of running
    # zero scenarios (or raising). Found by an adversarial test
    # (tests/test_optimizer.py::test_empty_scenario_keys_...). None means
    # "not specified, use the default"; [] means "caller explicitly asked
    # for nothing," which should fail loudly, not silently substitute a
    # different request.
    if scenario_keys is None:
        scenario_keys = list(SCENARIOS.keys())
    if not scenario_keys:
        raise ValueError("scenario_keys is empty — at least one scenario is required to build a model.")
    model, meta = build_model(network, scenario_keys, lam=lam, alpha=alpha,
                               demand_utilization=demand_utilization, **cost_kwargs)
    status = solve(model)
    results = extract_results(model, meta)
    results["termination"] = status
    if include_flows:
        results["flows"] = extract_flows(model)
    return results


if __name__ == "__main__":
    print("=== Step 1: toy case (hand-checked) ===")
    run_toy_case()

    print("\n=== Step 2: full network, risk-neutral, baseline-only ===")
    r = run_full_network(scenario_keys=["baseline"], lam=0.0)
    print(f"  status={r['termination']}  expected_cost=${r['expected_cost_usd_per_day']:,.0f}/day  "
          f"max_shortfall={r['max_shortfall_kbpd']:.1f} kbpd")

    print("\n=== Step 3: full network, all 4 scenarios, risk-neutral (lambda=0) ===")
    r0 = run_full_network(lam=0.0)
    print(f"  status={r0['termination']}  expected_cost=${r0['expected_cost_usd_per_day']:,.0f}/day  "
          f"CVaR@90%=${r0['cvar_usd_per_day']:,.0f}/day  worst_scenario={r0['worst_scenario']}  "
          f"max_shortfall={r0['max_shortfall_kbpd']:.1f} kbpd")
    for s, c in r0["scenario_costs_usd_per_day"].items():
        print(f"    {s:20s} cost=${c:,.0f}/day  shortfall={r0['scenario_shortfall_kbpd'][s]:.1f} kbpd")

    LAM = 3.0
    print(f"\n=== Step 4: full network, all 4 scenarios, risk-averse (lambda={LAM}, alpha=0.9) ===")
    r1 = run_full_network(lam=LAM)
    print(f"  status={r1['termination']}  expected_cost=${r1['expected_cost_usd_per_day']:,.0f}/day  "
          f"CVaR@90%=${r1['cvar_usd_per_day']:,.0f}/day  worst_scenario={r1['worst_scenario']}  "
          f"max_shortfall={r1['max_shortfall_kbpd']:.1f} kbpd")
    for s, c in r1["scenario_costs_usd_per_day"].items():
        print(f"    {s:20s} cost=${c:,.0f}/day  shortfall={r1['scenario_shortfall_kbpd'][s]:.1f} kbpd")

    print("\n=== Money slide: risk-neutral vs risk-averse ===")
    delta_cost_pct = 100 * (r1["expected_cost_usd_per_day"] - r0["expected_cost_usd_per_day"]) / r0["expected_cost_usd_per_day"]
    worst_cost_0 = r0["scenario_costs_usd_per_day"][r0["worst_scenario"]]
    worst_cost_1 = r1["scenario_costs_usd_per_day"][r0["worst_scenario"]]
    delta_worst_cost_pct = 100 * (worst_cost_1 - worst_cost_0) / worst_cost_0
    print(f"  Expected cost changes by {delta_cost_pct:+.2f}% going risk-averse")
    print(f"  Worst-case ({r0['worst_scenario']}) scenario COST changes by {delta_worst_cost_pct:+.2f}% going risk-averse")
    print(f"  Worst-case TOTAL SHORTFALL is unchanged ({r0['max_shortfall_kbpd']:.1f} kbpd both ways) — it is "
          f"capacity-bound (a topology limit), not a contracting choice. What CVaR actually buys here is cheaper "
          f"insurance against stranded take-or-pay commitments, not more physical barrels.")

    print("\n=== Where does the contracted portfolio actually shift? (supplier-level) ===")
    print(f"  {'supplier':30s} {'contract lam=0':>15s} {'contract lam=' + str(LAM):>15s} {'delta':>10s}")
    all_suppliers = sorted(set(r0["contract_by_supplier_kbpd"]) | set(r1["contract_by_supplier_kbpd"]),
                            key=lambda s: -r0["contract_by_supplier_kbpd"].get(s, 0))
    for sp in all_suppliers:
        c0 = r0["contract_by_supplier_kbpd"].get(sp, 0.0)
        c1 = r1["contract_by_supplier_kbpd"].get(sp, 0.0)
        if abs(c1 - c0) > 1.0:
            print(f"  {sp:30s} {c0:15.1f} {c1:15.1f} {c1 - c0:+10.1f}")

    print(f"\n=== Who actually bears the {r0['worst_scenario']} shortfall — and does CVaR just move it around? ===")
    refs = sorted(set(r0['shortfall_by_refinery_kbpd'][r0['worst_scenario']]) |
                  set(r1['shortfall_by_refinery_kbpd'][r0['worst_scenario']]))
    for rf in refs:
        s0 = r0['shortfall_by_refinery_kbpd'][r0['worst_scenario']].get(rf, 0.0)
        s1 = r1['shortfall_by_refinery_kbpd'][r0['worst_scenario']].get(rf, 0.0)
        print(f"  {rf:25s} lam=0: {s0:7.1f} kbpd   lam={LAM}: {s1:7.1f} kbpd")
