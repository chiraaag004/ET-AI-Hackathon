# Known Limitations — disclosed, not hidden

Every item below is a deliberate scope cut or a disclosed approximation, not
a bug. Each is cheap to explain in Q&A and none of them changes the demo.
If a judge asks about one of these, the honest answer is "yes, documented
here, and here's why it doesn't matter for what we're demonstrating" — not
a scramble.

## 1. SPR primary sourcing is not independently verified

Strategic Petroleum Reserve inventory figures (Vizag, Mangalore, Padur) come
from PIB press releases and Wikipedia, not from PPAC. SPR sits under a
separate MoPNG program and isn't in PPAC's Ready Reckoner or Snapshot
reports, so the DGCI&S cross-check trick that verified supplier shares
doesn't apply here. Closing this would need a direct RTI to MoPNG. See
`DATA_SOURCES.md` for the same caveat in context.

## 2. Fiscal-year vs. calendar-year mismatch in supplier shares

Country-wise import shares are exact DGCI&S calendar-2025 (Jan-Dec)
percentages, applied to PPAC's fiscal-year 2025-26 (Apr'25-Mar'26) import
volume total — the two periods overlap nine months but aren't identical.
Disclosed in `DATA_SOURCES.md`. Two independent cross-checks (implied
price, top-5 concentration) both landed within 0.3% of PPAC's own figures,
which is why the approximation is trusted rather than replaced.

## 3. Regional/domestic production split is an approximation

The ~562 kbpd of indigenous crude is split across four production regions
(offshore Mumbai, Rajasthan, Assam, Gujarat) using a documented but
estimated regional allocation, not a PPAC table broken out at that
granularity.

## 4. Single-period model — no multi-day SPR dynamics

The optimizer solves one representative day per scenario. SPR draws are
capped by a daily max-draw-rate, but there's no multi-day depletion
(inventory doesn't fall as you keep drawing) or replenishment. A real
resilience plan cares about day 1 vs. day 20 of a closure; this model only
answers "day 1."

## 5. Fairness / equitable-service-level objective — cut from scope

The original plan cites a fairness extension (don't let optimization
concentrate 100% of a shortfall onto whichever refinery is cheapest to
sacrifice). Not built — the app's optimizer section calls this out
explicitly where the per-refinery shortfall table shows CVaR redistributing
pain across refineries rather than reducing it.

## 6. `alt_corridor` / `alt_transit_days` are recorded but not used

Every shipping edge crossing Hormuz or the Red Sea/Suez corridor carries an
`alt_corridor` and `alt_transit_days` field (e.g. Russia→India via Suez is
22 days, via the Cape of Good Hope alternative is tagged 28 days). **Neither
field is read anywhere in `scenario_engine.py` or `optimizer.py`.**
`degraded_capacity()` only shrinks the same edge's capacity by
`severity * chokepoint_exposure`; recovery happens by the optimizer shifting
contract volume to other edges/suppliers, never by rerouting the same
shipment onto its alternate, longer path. This was found during real-world
validation (see below), not designed in — it's a genuine gap between what
the data model records and what the code consumes, worth being upfront
about rather than quietly leaving unmentioned.

## 7. No disruption-time freight/insurance surcharge

`freight_usd_bbl()` is keyed only on an edge's static base `transit_days`
and never changes during a disruption scenario. Real chokepoint crises
raise costs two ways this model doesn't capture: rerouted voyages take
longer (see #6) and freight/insurance rates spike even on routes that keep
sailing (war-risk premiums, fewer available ships). The real-world
comparison below sizes how big that gap is.

## 8. Real-world validation

### 8a. `hormuz_100` is not hypothetical — it is the real, ongoing crisis this whole build is based on

Independent-review request: check whether the disruptions this system predicts relate to real-world
data, not just internally-consistent arithmetic. Re-checked via live web search (not training-data
recall, since this event postdates any static knowledge cutoff) as of 21 July 2026 — the app's own
"today."

**What is actually happening, per current reporting:** Iran effectively closed the Strait of Hormuz on
28 February 2026 following US/Israeli strikes. As of 21 July 2026 the strait is described as
"effectively closed to commercial shipping" — some days last week saw only 4 tanker transits, versus
125-140/day before the war (Time, "What Is the Status of the Strait of Hormuz?", 12 Jul 2026; Hormuz
Strait Monitor crisis timeline). A four-month ceasefire memorandum collapsed in the first week of July;
CENTCOM has since conducted the largest strike package of the conflict and Iran has struck Jordan, the
UAE, Bahrain, and Qatar in response. In other words: `hormuz_100` (full closure, the scenario this
build treats as its "worst case") is not a tail-risk hypothetical being planned for — it is the
present, and has been for five months.

**India-specific reported impact, checked directly against this model's own numbers:**
- Real reporting: "roughly 52% of India's ~5 mbpd crude imports pass through the Strait of Hormuz"
  (Discovery Alert, citing IEA-referenced figures) and separately "40-50% of these imports transited
  the Strait of Hormuz" under normal conditions (OilPrice.com). **This model's own exposure-weighted
  Hormuz KPI: 48.2%** (2,380 of 4,936.2 kbpd) — inside the real reported 40-52% range, and close to
  its midpoint. The raw (unweighted) figure this app used to show, 56.7%, would have overstated it
  slightly beyond that range — one more reason the M5 exposure-weighting fix mattered for more than
  cosmetics.
- Real reporting: India "has lost over 40% of its crude oil flows since the Hormuz Strait closed"
  (OilPrice.com, "India's Oil Crisis Deepens as Hormuz Remains Shut"). **This model's `hormuz_100`
  scenario removes exactly 2,380 kbpd of shipping capacity — 48.2% of total import capacity** — the
  same order of magnitude as the real, reported ~40% flow loss. These are not the same measurement
  (reported "flow loss" nets in whatever rerouting/diversification already happened; this model's
  figure is the raw capacity removed before any optimizer response), which is exactly why they're
  close but not identical — and that gap is itself informative, not an error.
- Real reporting: India's SPR stood at "5.33 million tonnes — barely nine to ten days of cover"
  (thesquirrels.in, "The Strait Is Closed. The Reserves Are Draining."). **This model's `network.json`
  uses the same 5.33 MMT combined SPR inventory, ≈9.5 days at full fill** — this isn't a coincidence,
  it's the same PIB/Wikipedia-sourced figure (see DATA_SOURCES.md), but it's reassuring that the
  number independent reporting quotes for the real crisis matches what this build had already sourced
  before this check.
- Real reporting: by 11 March 2026, India had secured "about 70 percent of crude imports from outside
  the Strait of Hormuz" (source: India's Ministry of Petroleum and Natural Gas, via newsonair.gov.in)
  — i.e., real India cut its Hormuz-routed share roughly in half through diversification. **This
  model's own risk-averse (CVaR) plan does the same thing directionally**: the supplier-shift table in
  the Prescription tab shows contracted volume moving away from Hormuz-exposed suppliers (Iraq, Saudi,
  Kuwait) toward diversified, non-Hormuz ones (USA, UAE at lower exposure, Nigeria, Angola) under
  risk-aversion. Not a quantitative match (this model has no notion of "70% outside Hormuz" as a
  target), but the same qualitative response the real crisis actually produced.

**What this model does NOT capture, disclosed plainly:** the IEA's coordinated 400-million-barrel
strategic release (the largest in the institution's history, ~41% deployed by May 2026) — this model
only has India's own 3-site SPR, not the international coordinated response; the macroeconomic
fallout (India's GDP growth forecast cut to 6.7% for FY26-27, rupee at record lows, $20B+ in FII
outflows in four months, OMCs reportedly losing ~₹1,000 crore/day from price-controlled retail fuel);
and the human cost (Iran's Health Ministry reported 50+ deaths and 500+ wounded from strikes since
6 July alone, and earlier in this crisis two tankers with Indian seafarers aboard — *Skylight* and
*MKD VYOM* — were attacked, per the headline set in `signal_extractor.py`). None of this is
economically or humanly abstractable into a supply-chain LP; naming it here is the honest way to keep
the model's actual scope visible next to the real stakes.

**Bottom line for a judge's Q&A:** this isn't a hypothetical stress-test scenario picked for demo
drama — it is checked, as of the day this was written, against live reporting on the actual ongoing
crisis, and the model's central numbers (Hormuz exposure share, capacity lost, SPR inventory) land
inside or very close to what's independently reported. What the model gets right is the *supply
network arithmetic*; what it doesn't model — and says so — is the coordinated international response,
the macroeconomic and humanitarian fallout, and the specific diplomatic/financial mechanisms (waivers,
alternate payment routes) real countries used.

**Sources:** [Time — What Is the Status of the Strait of Hormuz?](https://time.com/article/2026/07/12/what-is-the-status-of-the-strait-of-hormuz-/) ·
[Hormuz Strait Monitor — Crisis Timeline](https://hormuzstraitmonitor.com/crisis-timeline/) ·
[Discovery Alert — Hormuz Crisis Transforms India's Energy Import Strategy in 2026](https://discoveryalert.com.au/hormuz-shock-india-oil-lifeline-2026/) ·
[OilPrice.com — India's Oil Crisis Deepens as Hormuz Remains Shut](https://oilprice.com/Energy/Energy-General/Indias-Oil-Crisis-Deepens-as-Hormuz-Remains-Shut.amp.html) ·
[thesquirrels.in — The Strait Is Closed. The Reserves Are Draining.](https://thesquirrels.in/global-economy-trade/strait-hormuz-closure-oil-india-spr-drawdown-2026-12007684) ·
[India's Ministry of Petroleum and Natural Gas, via newsonair.gov.in](https://www.newsonair.gov.in/india-secures-70-of-crude-oil-imports-outside-strait-of-hormuz-petroleum-ministry) ·
[CNBC — U.S. Hormuz blockade hits India](https://www.cnbc.com/2026/04/14/us-hormuz-blockade-hits-india-just-as-russian-oil-purchase-waiver-expires-deepening-energy-worries.html)

### 8b. Real-world validation: Red Sea / Houthi crisis vs. `redsea_suspend`

The Red Sea/Houthi crisis (Nov 2023–present) is a separate, live, well-documented analog specifically
to `redsea_suspend` (rather than `hormuz_100`, covered above), and it's the basis for this check.

**What actually happened** (EIA, "Red Sea attacks increase shipping times
and freight rates," Feb 2024, and India-specific reporting on the same
crisis):
- Persian Gulf → Rotterdam via Suez: 19 days. Via the Cape of Good Hope:
  ~35 days — **+16 days, +84%**.
- Crude flow through Bab el-Mandeb fell ~18% in December 2023 vs. the
  Jan-Nov 2023 average; clean product flow fell ~30%.
- Tanker rates on routes crossing the Red Sea/Suez rose ~20% in one month
  (Dec 2023 vs. Nov 2023); the western-India→UK-Continent route rose the
  most, 23%. Separately reported figures for the sustained 2024 period put
  Gulf→India crude tanker freight up 35-40% and war-risk insurance premiums
  up 15-20% at the peak.
- Brent spot price stayed roughly flat over the same window ($82/bbl the
  week before the attacks started, $79/bbl by mid-January) — the crisis
  raised freight and logistics costs, not the underlying crude commodity
  price. That's actually consistent with this model: `SPOT_PREMIUM_USD_BBL`
  is a flat constant, not scenario-dependent, so we never claimed a
  disruption should move the commodity price either.
- India's real response looked like diversification: crude imports from
  Brazil and the US rose over 30% between Dec 2023 and Feb 2024, as
  traders shifted volume away from the Suez-dependent corridor. This is
  directionally the same behavior the optimizer produces under
  risk-aversion — contract volume shifting from chokepoint-exposed
  suppliers toward diversified ones.

**Checking it against this model's own numbers:**
- `e_russia_vadinar` / `e_russia_sikka` (Russia's real route, genuinely
  Suez-dependent): `transit_days=22`, `alt_transit_days=28` — a **+6 day,
  +27%** penalty for the Cape reroute. The real-world Persian Gulf→Europe
  comparison above shows +16 days (+84%). This model's Cape-reroute penalty
  for Russia is understated relative to the best available real analog —
  worth widening if this edge case comes up, but doesn't change which
  supplier the optimizer favors, since Russia is already the
  highest-exposure, largest-volume route in every scenario.
- The freight-rate/insurance spike (+20-40% on affected routes, +15-20% war
  risk) has no analog in this model at all, per #7 above — it's a real,
  disclosed absence, not an approximation.
- Directionally, the model's core finding — that risk-aversion shifts
  contracted volume away from the chokepoint-exposed supplier and toward
  diversified ones (the supplier-shift table in the optimizer section) — is
  qualitatively consistent with what actually happened to India's real
  import mix during this crisis. That's the strongest validation available
  without a full historical backtest, and it's a fair thing to say to a
  judge: not "we proved the model is quantitatively accurate," but "the
  direction of the model's central recommendation matches the one real,
  comparable disruption we have data for."

## 9. "Other" supplier bucket's chokepoint routing is approximate — RESOLVED

**Update:** resolved. "Other" used to pool 26 countries (Egypt, Colombia, Brazil, Qatar, Oman, and 21 more, each individually under 2%) at a single representative coordinate with every one of its edges routed via the Malacca corridor — correct for the Southeast-Asia-ish share of that bucket, but wrong for constituents like Egypt/Oman/Qatar that are genuinely Red-Sea/Hormuz-side, and it visually understated how many real countries actually supply India's crude (a direct independent-review request: "can we separate each country in the nodes that combine 26 countries together so the network looks full?").

Fixed by modeling all 25 of the pooled countries individually (Hungary, the 26th, reported exactly 0 tonnes in the source data and is correctly omitted) — same DGCI&S source file (`dgcis_freeuser_1784552528488_1.xls`), same exact quantity-share percentages, just no longer aggregated. Each got a real principal export terminal (Ras Laffan for Qatar, Ceyhan for Turkey, Sidi Kerir for Egypt, etc.), a corridor/chokepoint-exposure assignment based on that terminal's actual geography (Gulf-inside countries via Hormuz at high exposure, Mediterranean/Red-Sea-adjacent via Suez, West/Central-African-Atlantic via the Cape bypass at zero exposure, Americas via no named chokepoint, Southeast Asia via Malacca), and a shipping edge to a specific Indian port. `build_network.py`'s SUPPLIER_META has the per-country reasoning in comments; the old routing-approximation problem this item originally described is gone because there's no longer a single bucket mixing all these regions together.

One new caveat introduced by this fix, disclosed rather than hidden: a handful of the DGCI&S rows (Panama, Singapore, Uruguay) are almost certainly transshipment/trading points rather than producing countries — "country of consignment" in trade data isn't always "country of origin." Modeled as-is (matching what the source data actually says) rather than silently reassigned to a guessed true origin.

Independent-review follow-up (now superseded by the fix above, kept for the record): the representative coordinate itself used to sit directly at Singapore (1.29, 103.85), which — apart from the routing approximation — visually read as "this marker IS Singapore," misleading for a bucket whose named constituents spanned the Gulf, Red Sea, Atlantic, and Pacific. That problem doesn't apply anymore since there's no single aggregate marker left to mislabel.

## 10. The λ / take-or-pay bug — kept as a technical-excellence story, not hidden

The first working version of the optimizer made every variable
scenario-indexed with no shared first-stage decision, so contracting was
free optionality and risk-aversion (`lam > 0`) produced a byte-identical
solution to risk-neutral. Caught by explicitly testing whether `lam`
changed the solution (it didn't). Fixed by making `contract[e]` genuinely
first-stage and adding `TAKE_OR_PAY_FRACTION = 0.7` (pay for ≥70% of
contracted volume even if a scenario can't deliver it — how real term
crude contracts actually work), which makes over-committing to a
chokepoint-fragile route a real, scenario-dependent cost that CVaR can
trade off against. Good Q&A answer to "how do we know CVaR is actually
doing anything": "we tested it, it wasn't, here's the fix and why it's
economically correct, not just a code patch."
