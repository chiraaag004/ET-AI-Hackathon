# Independent Audit — Findings

Every finding below was **verified by actually running the code** (full test suite + targeted
adversarial probes against the solved LP), not by reading it. Environment: Python 3, Pyomo +
HiGHS, Streamlit 1.59.2 (newer than yours — noted where that matters). All 95 tests pass as
claimed (82 core in 1.2 s + 13 AppTest). The toy-case hand-check reproduces. The CVaR
mechanism genuinely works: λ=0→3 shifts Iraq −264 kbpd, Russia −68, into USA +68 / UAE +23,
expected cost +0.42%, worst-case cost −3.2%. The two documented bug fixes (take-or-pay,
empty-scenario-list) hold. What follows is what the test suite does **not** catch.

---

## HIGH — these change the numbers your demo shows

### H1. India's biggest domestic supply source is stranded: Mumbai offshore + Rajasthan crude never reaches any refinery
`e_domestic_offshore_mumbai_port` (cap 672.8, actual production 309.3 kbpd) and
`e_domestic_rajasthan_vadinar` (cap 174.9, production 140.6 kbpd) terminate at **ports**.
But both consumers of the graph count only `shipping_route` inflows at ports:

- `optimizer.py` `port_in_edges` (port_balance) — shipping edges only
- `scenario_engine.py` `refinery_supply_gap` `port_inbound` — shipping edges only

So domestic barrels arriving at a port can never leave it. **Verified on the solved model:
flow = 0.0 on both edges in every scenario.** ~450 kbpd of real, cheap (−$5/bbl) indigenous
supply — 80% of India's domestic production — is invisible to the whole system.

Knock-on effects, all verified:
- Mumbai BPCL shows a 160.9 kbpd shortfall **at baseline** (Mumbai port's only counted
  inflow is the 150 kbpd USA route, against 431.7 kbpd of Mumbai refinery demand).
- The model buys **257 kbpd of spot crude on a normal day** to paper over it.
- Of the "~297 kbpd baseline topology gap," **132 kbpd (44%) is this code bug, not a data
  gap**: scenario-engine decomposition = Panipat 132.5 + Mumbai BPCL 91.0 + Mumbai HPCL 40.8
  + Kochi 31.3 + Bathinda 1.0. KNOWN_LIMITATIONS attributes the whole gap to
  "Panipat/Bathinda under-connection" — the Mumbai half of that attribution is wrong.

**Fix (~4 lines each):** include `domestic_pipeline` edges in `port_in_edges` (optimizer)
and `port_inbound` (scenario engine). Then re-derive the residual gap number everywhere it's
quoted (docs, captions, KNOWN_LIMITATIONS).

### H2. The optimizer drains the Strategic Petroleum Reserve on a normal day
Baseline (no disruption) SPR draw, verified: **Vizag 140.0 kbpd (maxed) + Padur 164.5 =
304.5 kbpd of strategic reserves used as routine supply.** Cause: SPR cost is basket + $3 =
$73.99/bbl, which undercuts USA ($77.49), Angola ($76.99), Nigeria ($76.49) and spot
($76.99), and the single-period model has **no inventory accounting** — SPR is effectively a
free 475 kbpd supplier with no depletion cost. A judge who asks "what does the baseline plan
look like?" sees India funding daily operations out of its emergency reserve, which also
flatters every disruption scenario (the SPR is 'already flowing').

**Fix (pick one):** (a) constrain `spr_draw[e, "baseline"] == 0` — reserves are for
disruptions; (b) raise `SPR_DRAWDOWN_PREMIUM_USD_BBL` above the most expensive routine
barrel (≥ $10–15/bbl, defensible as inventory/opportunity cost); (c) both. Note this changes
every cost figure in the demo — re-record numbers afterwards.

### H3. Domestic production caps don't exist in the optimizer
`supplier_cap` sums only `shipping_route` contracts, so domestic suppliers (whose edges are
`domestic_pipeline` in OTHER_EDGES) are capped only by pipeline capacity, not by what the
region actually produces. Verified at baseline: **Assam used 108.5 kbpd vs 67.5 produced
(1.6×); Gujarat used 153.9 vs 45.0 (3.4×).** Cheap domestic crude gets overdrawn, further
distorting baseline economics. (Combined with H1's fix this matters more: once Mumbai
offshore is un-stranded, its 672.8 kbpd pipeline would let the solver draw 2× the field's
real output.)

**Fix:** add a constraint per domestic supplier: sum of its outgoing `flow` ≤ node
`flow_kbpd`, per scenario. Fix H1 and H3 **together** — H1 alone makes H3 worse.

---

## MEDIUM — visible in the demo or latent correctness debt

### M1. The Brent-price headline maps to "Baseline — no disruption"
Verified: `h4_brent_100` → corridor None, severity 0.20 → **scenario=baseline**. It's the
only headline in your curated 7 with no corridor keyword ("Brent", "$126", "oil price" match
nothing). Clicking it in the demo announces a $126-Brent crisis and then auto-selects "no
disruption" with a zero-gap briefing. Either add price-shock keywords to the Hormuz list
(defensible for this curated set), or remove h4, or keep it deliberately as your "honest
limitation" talking point — but decide, don't discover it live.

### M2. port_haldia is a dead end — a route on your map can never deliver
`e_other_haldia` ships 160 kbpd into port_haldia, which has **zero outgoing edges** (Haldia
refinery is fed from Paradip via PHBPL). Verified: contract = 0, flow = 0 in every scenario.
The map draws a supply route that the optimizer provably never uses. Add a
`port_haldia → ref_haldia` edge or delete the route.

### M3. PHBPL shared capacity is double-counted (latent)
`e_paradip_haldia_ref` and `e_paradip_barauni_ref` each carry the full 409.7 kbpd; the JSON
note says "not additive" but **no code enforces it** — the LP would happily push 819 kbpd
through a 409 kbpd pipeline. Not binding today (max observed combined flow: 126 kbpd), so
results are unaffected, but it's one demand bump away from being silently wrong. One joint
constraint fixes it.

### M4. Port capacities are dead data — and internally inconsistent
No code reads port `capacity_kbpd`. Meanwhile 6 of 11 ports have total inbound shipping
capacity exceeding their stated capacity (Sikka: 2310 in vs 1950 cap; also Vadinar, Kandla,
New Mangalore, Chennai, Visakhapatnam). Either add a port throughput constraint or remove
the field; as-is it's a contradiction sitting in `network.json` for any judge who opens it.

### M5. KPI "Hormuz-routed capacity" overstates exposure by ignoring your own exposure field
The app sums full `capacity_kbpd` of Hormuz-tagged edges: **2,800 kbpd (57% of imports)**.
Exposure-weighted (`capacity × chokepoint_exposure`): **2,380 kbpd (48%)** — which also
sits right next to the problem statement's own "40–45%" figure, so the corrected number is
*better* for your pitch. One-line fix in the KPI.

---

## LOW — polish, consistency, forward-compat

- **L1. Stale sidebar:** "Coming Day 3+: headline → event-node signal extraction…" — Day 3
  shipped. Ten seconds to delete; looks unfinished in a demo otherwise.
- **L2. Mixed shortfall conventions in one briefing:** the executive note quotes the raw
  worst-case shortfall (733.7 kbpd, includes the baseline artifact) alongside
  baseline-netted gap metrics. After fixing H1–H3 re-derive both; until then label raw as raw.
- **L3. Timeline "Day 0: unmet demand" shows ~209 kbpd on a normal day** (raw baseline
  shortfall) — the artifact leaking into a demo-visible metric. Fixing H1 mostly cures it.
- **L4. days_of_cover semantics:** for hormuz_100 the gap (838 kbpd) exceeds max SPR draw
  (475), so SPR covers only ~57% of the gap, yet the metric reads "82.3 days of cover."
  Also SPR is physically linked to only 2 refineries while the arithmetic assumes it can
  serve the national gap. Reword the label ("SPR endurance at max drawdown") or cap it.
- **L5. Streamlit deprecation:** on 1.59 every `use_container_width=True` logs a removal
  warning (removal announced post-2025-12-31). Your local version is older, so fine for the
  hackathon; expect breakage on future upgrades.
- **L6. Cache staleness:** `_run_comparison`/`_run_sensitivity` are `st.cache_data`-keyed on
  parameters only — if you regenerate `network.json` mid-session, cached optimizer results
  are stale. Restart Streamlit (or add a data-file mtime to the cache key) after rebuilds.
- **L7. Stale briefing on scenario switch:** after a run, changing the Scenario picker leaves
  the previous briefing (describing the old trigger) rendered below new snapshot numbers.
  Cosmetic; a caption ("briefing reflects the last run") would cover it.
- **L8. Slider-clamp crash: NOT reproduced.** Sequence (ndays=30 → day=25 → shrink ndays=5)
  clamps safely on Streamlit 1.59 with zero exceptions. Verify once on your local version;
  low risk.

---

## Order of operations

1. Fix H1 + H3 together (port inflows + domestic caps), then H2 (SPR), then M2 (Haldia).
2. **Re-run the full test suite** — any test that snapshots current numeric outputs encodes
   today's buggy numbers and should fail/be updated. If none fail, that's a coverage gap.
3. Re-derive every number quoted in docs/captions/KNOWN_LIMITATIONS: the ~297 baseline gap,
   the 209/733.7 shortfalls, expected costs, and the money-slide percentages all change.
4. M1, M5, L1 are minutes each; do them the same session.
5. M3, M4 are one constraint each — cheap insurance for Q&A.

## What this audit did NOT cover
Visual rendering (no pixels checked — same limitation as your own testing), real LLM-path
execution (no API key here either), load/concurrency, and correctness of the PPAC/DGCI&S
source figures themselves (your provenance documentation was spot-checked for internal
consistency only).
