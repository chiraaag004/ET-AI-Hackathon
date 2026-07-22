"""
Layer 1/4 — Executive Briefing Generator.

Optimizer output (+ the triggering headline, if any) -> a one-page
executive note. Uses the real LLM for prose polish if configured (llm.py);
otherwise fills a deterministic Markdown template with the same numbers.
Both paths are given the SAME pre-computed figures — the LLM is
instructed not to invent numbers, only to write them up. This keeps the
briefing accurate regardless of which path produced it, which matters
more than which one sounds nicer.

Run standalone: python3 briefing_generator.py
"""
from datetime import datetime

from llm import call_llm, llm_configured

_BRIEFING_SYSTEM = (
    "You are drafting a one-page executive briefing note for a crude oil procurement officer. "
    "You will be given a bulleted list of pre-computed numbers. Write a short, direct briefing "
    "using ONLY the numbers given to you — do not invent, round differently, or estimate any "
    "additional figures. Structure it under exactly these four headers, in this order, because "
    "the reader needs a straight answer to each one, not prose they have to dig through: "
    "'### Impact' (what happened, in plain words — the size of the disruption and the supply gap "
    "it creates, without jargon), '### Effect on India' (what this actually means operationally — "
    "which refineries/regions are hit, what it costs, whether the SPR alone can cover it), "
    "'### Recommended actions' (a short numbered list of concrete, specific actions — which "
    "suppliers to lean on more, whether to draw the SPR and how much, whether spot purchases are "
    "needed and roughly how much), '### Response plan' (the day-by-day shape of the plan: what "
    "happens immediately vs. over the re-contracting window, referencing the specific supplier "
    "shifts). End with a one-line '### Caveats' note. Plain business prose, no markdown headers "
    "deeper than ###, no emoji."
)


def _build_facts(headline, signal, scenario_key, scenario_label, snapshot, r0, r1, network, node_names):
    """Everything the briefing (either path) is allowed to say — the LLM
    prompt and the template both draw from exactly this, so neither path
    can drift from the actual optimizer output.

    Independent-review request: the briefing needs to answer, in plain
    words, (1) what's the impact, (2) how does it affect India, (3) what
    to do, (4) what's the plan — not just cost deltas. The extra fields
    below (SPR draw, spot purchases, worst-hit refineries, days-to-recontract)
    are what make those four questions answerable with real numbers instead
    of hand-waving."""
    worst = r0["worst_scenario"]
    delta_cost_pct = 100 * (r1["expected_cost_usd_per_day"] - r0["expected_cost_usd_per_day"]) / r0["expected_cost_usd_per_day"]
    worst_cost_delta_pct = 100 * (r1["scenario_costs_usd_per_day"][worst] - r0["scenario_costs_usd_per_day"][worst]) \
        / r0["scenario_costs_usd_per_day"][worst]

    shifts = []
    for sp, c0 in r0["contract_by_supplier_kbpd"].items():
        c1 = r1["contract_by_supplier_kbpd"].get(sp, 0.0)
        if abs(c1 - c0) > 1.0:
            shifts.append((node_names.get(sp, sp), c0, c1))
    shifts.sort(key=lambda x: x[2] - x[1])
    gainers = [s for s in shifts if s[2] > s[1]]
    losers = [s for s in shifts if s[2] < s[1]]

    flows = r1.get("flows")
    spr_draw_kbpd = 0.0
    spot_total_kbpd = 0.0
    if flows:
        spr_draw_kbpd = sum(v.get(scenario_key, 0.0) for v in flows.get("spr_draw_kbpd", {}).values())
        spot_total_kbpd = sum(v.get(scenario_key, 0.0) for v in flows.get("spot_kbpd", {}).values())

    worst_hit = [
        {"name": r["refinery"], "gap_kbpd": r["gap_kbpd"], "utilization_pct": r["utilization_pct"]}
        for r in snapshot.get("worst_hit_refineries", []) if r["gap_kbpd"] > 0
    ][:3]

    facts = {
        "trigger": headline["headline"] if headline else f"Manually selected scenario: {scenario_label}",
        "trigger_date": headline["date"] if headline else datetime.now().strftime("%Y-%m-%d"),
        "scenario_label": scenario_label,
        "disruption_gap_kbpd": snapshot["incremental_gap_kbpd"],
        "days_of_cover": snapshot["days_of_cover_if_unmitigated"],
        "spr_coverage_fraction": snapshot.get("spr_coverage_fraction"),
        "expected_cost_risk_neutral": r0["expected_cost_usd_per_day"],
        "expected_cost_risk_averse": r1["expected_cost_usd_per_day"],
        "expected_cost_delta_pct": round(delta_cost_pct, 2),
        "worst_scenario": worst,
        "worst_case_cost_delta_pct": round(worst_cost_delta_pct, 2),
        "worst_case_shortfall_kbpd": r0["max_shortfall_kbpd"],
        "supplier_shifts": shifts[:5],
        "supplier_gainers": gainers[-3:][::-1],
        "supplier_losers": losers[:3],
        "spr_draw_kbpd": round(spr_draw_kbpd, 1),
        "spot_purchase_kbpd": round(spot_total_kbpd, 1),
        "worst_hit_refineries": worst_hit,
        "estimated_duration_days": signal.get("estimated_duration_days") if signal else None,
    }
    return facts


def _facts_to_bullets(facts: dict) -> str:
    coverage = facts["spr_coverage_fraction"]
    coverage_text = "not applicable" if coverage is None else f"{coverage * 100:.0f}% at max drawdown"
    lines = [
        f"- Trigger: {facts['trigger']} ({facts['trigger_date']})",
        f"- Scenario modeled: {facts['scenario_label']}",
        f"- Disruption-caused refinery supply gap (net of baseline): {facts['disruption_gap_kbpd']:,.0f} kbpd",
        f"- Days of cover if unmitigated: {facts['days_of_cover'] or 'not applicable — no incremental gap'}",
        f"- SPR coverage fraction of the gap: {coverage_text}",
        f"- SPR drawdown in the recommended (risk-averse) plan for this scenario: {facts['spr_draw_kbpd']:,.0f} kbpd",
        f"- Spot-market purchases in the recommended plan for this scenario: {facts['spot_purchase_kbpd']:,.0f} kbpd",
        f"- Expected procurement cost, risk-neutral plan: ${facts['expected_cost_risk_neutral']:,.0f}/day",
        f"- Expected procurement cost, risk-averse plan: ${facts['expected_cost_risk_averse']:,.0f}/day "
        f"({facts['expected_cost_delta_pct']:+.2f}% vs. risk-neutral)",
        f"- Worst-case scenario: {facts['worst_scenario']}; risk-averse plan changes its COST by "
        f"{facts['worst_case_cost_delta_pct']:+.2f}% vs. risk-neutral (physical worst-case shortfall is "
        f"unchanged at {facts['worst_case_shortfall_kbpd']:,.0f} kbpd — that's a topology limit, not a "
        f"contracting choice)",
    ]
    if facts["estimated_duration_days"]:
        lines.append(f"- Estimated days to fully re-contract: {facts['estimated_duration_days']}")
    if facts["worst_hit_refineries"]:
        lines.append("- Worst-hit refineries (unoptimized capacity ceiling, before routing/SPR/spot response):")
        for r in facts["worst_hit_refineries"]:
            lines.append(f"    - {r['name']}: {r['utilization_pct']:.0f}% of demand still served, "
                         f"gap {r['gap_kbpd']:.0f} kbpd")
    if facts["supplier_shifts"]:
        lines.append("- Supplier contract shifts (risk-neutral -> risk-averse, kbpd):")
        for name, c0, c1 in facts["supplier_shifts"]:
            lines.append(f"    - {name}: {c0:.1f} -> {c1:.1f} ({c1 - c0:+.1f})")
    return "\n".join(lines)


def _template_briefing(facts: dict) -> str:
    gainer_lines = "\n".join(
        f"- Increase contracted volume from **{name}**: {c0:.0f} -> {c1:.0f} kbpd ({c1 - c0:+.0f})"
        for name, c0, c1 in facts["supplier_gainers"]
    )
    loser_lines = "\n".join(
        f"- Reduce reliance on **{name}**: {c0:.0f} -> {c1:.0f} kbpd ({c1 - c0:+.0f})"
        for name, c0, c1 in facts["supplier_losers"]
    )
    shift_lines = "\n".join(
        f"- **{name}**: {c0:.0f} -> {c1:.0f} kbpd ({c1 - c0:+.0f})" for name, c0, c1 in facts["supplier_shifts"]
    ) or "- No supplier shifted contracted volume by more than 1 kbpd at this risk-aversion level."

    cover_line = (
        f"{facts['days_of_cover']:.1f} days of SPR cover remain if this gap is unmitigated"
        + (f", covering about {facts['spr_coverage_fraction']*100:.0f}% of it at max drawdown — the rest "
           f"needs spot purchases or rerouting" if facts["spr_coverage_fraction"] is not None
           and facts["spr_coverage_fraction"] < 1.0 else "") + "."
        if facts["days_of_cover"] else
        "No incremental SPR draw is required — the disruption-caused gap nets to zero or is already covered."
    )

    refinery_lines = "\n".join(
        f"- **{r['name']}**: {r['utilization_pct']:.0f}% of demand still served (gap {r['gap_kbpd']:.0f} kbpd) "
        f"before any optimizer response" for r in facts["worst_hit_refineries"]
    ) or "- No refinery shows a nonzero unoptimized gap in this scenario."

    duration_line = (
        f"Assumed re-contracting window: **{facts['estimated_duration_days']} days** — the Timeline tab "
        f"animates day-by-day interpolation between the immediate shock and this fully-adapted plan."
        if facts["estimated_duration_days"] else
        "No specific re-contracting duration was set for this run; the Timeline tab defaults to a 7-day window."
    )

    action_items = []
    if facts["disruption_gap_kbpd"] > 0:
        action_items.append(f"**Draw the SPR**: {facts['spr_draw_kbpd']:,.0f} kbpd in the recommended plan. {cover_line}")
        if facts["spot_purchase_kbpd"] > 0:
            action_items.append(
                f"**Buy spot cargo**: {facts['spot_purchase_kbpd']:,.0f} kbpd at the documented spot premium "
                f"over India Basket — a stopgap, not a long-term substitute for contracted volume."
            )
        if facts["supplier_gainers"]:
            action_items.append("**Re-contract toward diversified suppliers** — see the reallocation list below.")
    else:
        action_items.append("No incremental action required — this scenario nets to zero additional gap versus baseline.")
    actions_block = "\n".join(f"{i+1}. {item}" for i, item in enumerate(action_items))
    if facts["supplier_gainers"]:
        actions_block += "\n\n**Specific reallocation:**\n" + gainer_lines
        if facts["supplier_losers"]:
            actions_block += "\n" + loser_lines

    return f"""### Impact
The modeled disruption ({facts['scenario_label']}) creates a **{facts['disruption_gap_kbpd']:,.0f} kbpd** \
supply gap at Indian refineries, net of the baseline topology gap already present on a normal day. \
Trigger: {facts['trigger']} ({facts['trigger_date']}).

### Effect on India
{refinery_lines}

{cover_line} In the worst-case scenario across all four modeled disruptions ({facts['worst_scenario']}), the \
physical shortfall floor is {facts['worst_case_shortfall_kbpd']:,.0f} kbpd regardless of contracting strategy — \
that's a topology limit (route/port/pipeline capacity), not something better procurement can buy away.

### Recommended actions
{actions_block}

### Response plan
Adopt the risk-averse (CVaR-weighted) procurement plan. Expected cost rises {facts['expected_cost_delta_pct']:+.2f}% \
versus the pure cost-minimizing plan (${facts['expected_cost_risk_averse']:,.0f}/day vs \
${facts['expected_cost_risk_neutral']:,.0f}/day) — that premium buys cheaper insurance against stranded \
take-or-pay commitments on chokepoint-exposed routes, not additional physical barrels. {duration_line}

**Full contract shift, risk-neutral -> risk-averse:**
{shift_lines}

### Caveats
Cost assumptions (shortfall penalty, spot premium, take-or-pay fraction) are documented planning judgment \
calls, not contract data — see the Assumptions & Robustness panel. Model limitations (SPR sourcing, \
single-period modeling, fairness) are listed in KNOWN_LIMITATIONS.md.
"""


def plain_language_story(facts: dict, network: dict) -> dict:
    """Independent-review request: every tab must be understandable to
    someone with zero domain knowledge. _template_briefing() (above) is
    accurate but still uses terms like 'kbpd', 'CVaR', and 'take-or-pay' —
    fine for the technical breakdown, wrong for the primary view. This
    produces the SAME facts dict translated into plain English: no jargon,
    percentages instead of raw kbpd where that's more intuitive, 'emergency
    oil reserve' instead of 'SPR'. Returns a dict of short strings/lists
    that app.py renders as narrative cards."""
    # NOTE: these strings are always embedded inside raw HTML `<div>` cards
    # in app.py (via st.markdown(..., unsafe_allow_html=True)) — Streamlit's
    # markdown renderer does NOT re-process Markdown syntax found inside a
    # raw HTML block, so a literal "**word**" here would render as literal
    # asterisks around the word instead of bold. Use real `<strong>` tags,
    # not Markdown emphasis, so it actually renders bold wherever it's used.
    total_cap = sum(n.get("capacity_kbpd", 0) or 0 for n in network["nodes"] if n["type"] == "refinery")
    pct_impact = (facts["disruption_gap_kbpd"] / total_cap * 100) if total_cap else 0.0

    if facts["disruption_gap_kbpd"] <= 0:
        return {
            "situation": f"This is today's normal picture — <strong>{facts['scenario_label']}</strong>. Nothing is disrupted right now.",
            "impact": "No supply gap. Oil is flowing through every route as normal.",
            "effect": "Every refinery is getting all the crude oil it needs. No refinery is short.",
            "actions": ["Keep monitoring the news for early warning signs — nothing to act on right now."],
            "plan": "No changes to contracts or reserves are needed for this scenario.",
            "cost": "No extra cost versus the normal plan.",
        }

    situation = (
        f"This looks at what happens if <strong>{facts['scenario_label'].lower()}</strong>. "
        f"Trigger: {facts['trigger']} ({facts['trigger_date']})."
    )
    impact = (
        f"About <strong>{pct_impact:.0f}%</strong> of India's oil-refining capacity — roughly "
        f"<strong>{facts['disruption_gap_kbpd']:,.0f} thousand barrels a day</strong> — would lose its normal "
        f"supply route for a while."
    )
    if facts["worst_hit_refineries"]:
        names = ", ".join(r["name"] for r in facts["worst_hit_refineries"][:3])
        worst = facts["worst_hit_refineries"][0]
        effect = (
            f"The hardest-hit refineries are <strong>{names}</strong>. Without any response, <strong>{worst['name']}</strong> "
            f"would only get about <strong>{worst['utilization_pct']:.0f}%</strong> of the fuel it normally needs — "
            f"the rest simply wouldn't arrive."
        )
    else:
        effect = "No single refinery is hit hard enough to stand out — the shortfall is spread thinly across the network."

    actions = []
    if facts["days_of_cover"]:
        actions.append(
            f"Draw down India's emergency oil reserve — there's enough set aside to help cover this for "
            f"about <strong>{facts['days_of_cover']:.0f} days</strong>."
        )
    if facts["spot_purchase_kbpd"] > 0:
        actions.append(
            f"Buy extra oil on the open (spot) market — about <strong>{facts['spot_purchase_kbpd']:,.0f} thousand "
            f"barrels a day</strong> — at a higher price than usual, as a temporary stopgap."
        )
    if facts["supplier_gainers"]:
        gain_names = ", ".join(g[0] for g in facts["supplier_gainers"])
        actions.append(f"Shift future orders toward safer suppliers, mainly <strong>{gain_names}</strong>.")
    if not actions:
        actions.append("No special action needed — the gap is small enough to absorb without changes.")

    dur = facts["estimated_duration_days"] or 7
    if facts["supplier_losers"]:
        lose_names = ", ".join(l[0] for l in facts["supplier_losers"])
        plan = (
            f"Over the next <strong>{dur} days</strong>, orders gradually move away from <strong>{lose_names}</strong> and toward the "
            f"safer suppliers named above, while the emergency reserve and spot purchases cover the gap "
            f"in the meantime."
        )
    else:
        plan = (
            f"Over the next <strong>{dur} days</strong>, the emergency reserve and any spot purchases cover the gap "
            f"while contracts adjust."
        )
    cost = (
        f"This response costs about <strong>{facts['expected_cost_delta_pct']:+.1f}%</strong> more per day than doing "
        f"nothing special — think of it as an insurance premium against an even worse outcome."
    )
    return {"situation": situation, "impact": impact, "effect": effect, "actions": actions, "plan": plan, "cost": cost}


def generate_briefing(headline, signal, scenario_key: str, scenario_label: str, snapshot: dict,
                       r0: dict, r1: dict, network: dict) -> tuple[str, str]:
    """Returns (briefing_markdown, method) where method is "llm" or
    "template" so the caller can display which path produced it."""
    node_names = {n["id"]: n["name"] for n in network["nodes"]}
    facts = _build_facts(headline, signal, scenario_key, scenario_label, snapshot, r0, r1, network, node_names)

    if llm_configured():
        prompt = f"Numbers to use (do not add others):\n{_facts_to_bullets(facts)}"
        text = call_llm(prompt, system=_BRIEFING_SYSTEM, max_tokens=800)
        if text:
            return text, "llm"

    return _template_briefing(facts), "template"


if __name__ == "__main__":
    import optimizer as opt
    import scenario_engine as sceng

    scenario_key = "hormuz_100"
    r0 = opt.run_full_network(lam=0.0, include_flows=True)
    r1 = opt.run_full_network(lam=3.0, include_flows=True)
    snapshot = sceng.summarize(scenario_key)
    network = sceng.load_network()

    text, method = generate_briefing(
        headline={"headline": "IRGC officially confirms the Strait of Hormuz is closed", "date": "2026-03-02"},
        signal={"corridor": "corridor_hormuz", "severity": 0.9, "estimated_duration_days": 14},
        scenario_key=scenario_key,
        scenario_label=sceng.SCENARIOS[scenario_key]["label"],
        snapshot=snapshot, r0=r0, r1=r1, network=network,
    )
    print(f"[method={method}]\n")
    print(text)
