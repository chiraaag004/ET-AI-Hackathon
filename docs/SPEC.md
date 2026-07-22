# Model Spec — Adaptive Procurement Orchestrator (Day 2 build target)

One-page formulation, translated from Sawik's AMPL stochastic-portfolio models (MultiPort §1.1–1.2, Resil §1, VIABIL) into a Pyomo-ready spec. This is the contract for Day 2 — build against this, don't improvise constraints mid-build.

## Sets
- `S` — suppliers (Russia, Iraq, Saudi Arabia, UAE, USA, Nigeria, Other)
- `C` — chokepoints/corridors (Hormuz, Red Sea/Suez, Cape of Good Hope, Malacca)
- `P` — Indian import ports (Sikka, Vadinar, Kandla, Mumbai, New Mangalore, Kochi, Paradip, Chennai, Visakhapatnam, Haldia)
- `R` — refineries (12 major, see network.json)
- `SP` — SPR sites (Vizag, Mangalore, Padur)
- `Ω` — disruption scenarios (baseline + one per chokepoint at 50%/100% severity), each with probability `π_ω`

## Decision variables
- `x[s,p,r,ω]` — barrels/day shipped supplier `s` → port `p` → refinery `r` under scenario `ω`
- `spr_draw[sp,ω,t]` — barrels/day drawn from SPR site `sp` on day `t` of the response window, scenario `ω`
- `spot[r,ω]` — barrels/day of spot-market purchases routed directly to refinery `r` (higher unit cost, no long-term contract, unconstrained by supplier capacity)
- `shortfall[r,ω]` — unmet demand at refinery `r` under scenario `ω` (should be driven to 0 where feasible; its cost is what CVaR penalizes)
- `z[ω]`, `VaR` — auxiliary CVaR variables (Rockafellar–Uryasev linearization)

## Constraints
1. **Refinery grade compatibility** — `x[s,p,r,ω] = 0` if refinery `r`'s Nelson complexity / grade preference can't process supplier `s`'s crude grade (encoded per-edge in `network.json` as `grade`, per-refinery as `grade_preference`).
2. **Port throughput capacity** — Σ over s,r of `x[s,p,r,ω] ≤ port_capacity[p]`.
3. **Supplier route capacity** — `x[s,p,r,ω] ≤ edge_capacity[s,p]`, degraded by the active scenario's chokepoint knockout (`edge_capacity × (1 − severity × chokepoint_exposure)`).
4. **Refinery demand balance** — Σ over s,p of `x[s,p,r,ω] + spr_draw_to[r,ω] + spot[r,ω] + shortfall[r,ω] = demand[r]`.
5. **SPR drawdown limits** — cumulative `spr_draw[sp,ω,t]` over the response window ≤ `spr_inventory[sp]`; daily draw ≤ `spr_max_draw_rate[sp]`.
6. **Transit-time lag** (stretch, skip if Day 2 runs long) — flows rerouted via an alternate chokepoint incur `alt_route_transit_days`; model as a fixed delay before `x` becomes available, or ignore for MVP and treat as same-day with a cost penalty instead.

## Objective
Two-stage stochastic, risk-averse:

```
min  Σ_ω π_ω · [ Σ x·unit_cost + Σ spot·spot_cost + Σ shortfall·shortfall_penalty ]
     + λ · CVaR_α( total_cost_by_scenario )
```

- Risk-neutral baseline: `λ = 0` (build and validate this first).
- Risk-averse: `λ > 0`, `α = 0.90` or `0.95` (worst 10%/5% of scenarios), via the standard CVaR linearization:
  `CVaR_α = VaR + (1/(1-α)) · Σ_ω π_ω · z[ω]`, `z[ω] ≥ total_cost[ω] − VaR`, `z[ω] ≥ 0`.
- Fairness variant (cited, not built): replace the shortfall penalty with a max-min or Gini term across refiners' service levels — see Fairness deck. One slide, no code.

## Build order (Day 2)
1. Risk-neutral, single scenario (baseline), 3-supplier/2-refinery toy case — hand-check the answer.
2. Scale to full network (all S/P/R), still risk-neutral, still single scenario.
3. Add scenario set Ω (baseline + Hormuz 50%, Hormuz 100%, Red Sea suspension) with fixed probabilities.
4. Add CVaR term. Compare risk-neutral vs risk-averse total cost and worst-case shortfall — this is the money slide (Section 7 of the plan).

## Solver
Pyomo + HiGHS (open-source, `pip install highspy`, or `pip install pulp` if switching to PuLP — HiGHS is fast enough for this problem size, no commercial solver needed).
