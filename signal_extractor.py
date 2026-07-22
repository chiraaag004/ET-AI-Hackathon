"""
Layer 1 — Risk Signal Agent.

Headline -> structured disruption signal (corridor, severity, probability)
-> nearest matching scenario in scenario_engine.SCENARIOS -> event node for
the Supply Chain Knowledge Graph. Per the plan's solo scope cut, this reads
from a small pre-cached, dated, sourced set of REAL headlines rather than a
live news feed (GDELT/RSS) — the demo looks identical and can't break on
conference Wi-Fi.

The headline set below is centered on the actual, ongoing 2026 Strait of
Hormuz crisis (US/Israel strikes on Iran since 28 Feb 2026; Iran mining and
closing the strait; Brent crude peaking near $126/bbl; Indian seafarers
among the casualties) rather than a hypothetical — this is real, dated,
and independently checkable (Wikipedia: "2026 Strait of Hormuz crisis"),
which is a stronger evidentiary basis than an invented scenario. One Red
Sea headline (a real 2024 Houthi-crisis event, already used for this
model's validation in KNOWN_LIMITATIONS.md) is included so the extractor
demonstrably handles more than one corridor.

Run standalone: python3 signal_extractor.py

---------------------------------------------------------------------------
THE SIGNAL SCHEMA — the actual contract, not an implementation detail
---------------------------------------------------------------------------
Every signal source in this file (real LLM, rule-based fallback, or a
human setting sliders in the app's "Manual Signal Override" panel) must
produce EXACTLY this shape. This is deliberately small: it's every field
the rest of the pipeline (nearest_scenario, the optimizer, the Disruption
Timeline, the briefing generator) actually reads — nothing is included
"because an LLM could plausibly say it."

    corridor:  str | None
        One of "corridor_hormuz", "corridor_redsea_suez", "corridor_malacca",
        "corridor_cape", or None (no chokepoint implicated). Must be a real
        corridor node id in data/network.json — nearest_scenario() treats
        anything else as None.
    severity:  float, 0.0-1.0
        0 = no disruption, 1 = full capacity loss at the corridor. Feeds
        directly into scenario_engine.degraded_capacity() via whichever
        scenario nearest_scenario() maps this signal onto.
    probability: float, 0.0-1.0
        Confidence this is REAL and CURRENT (already happening / credibly
        reported), not a forecast of a hypothetical future event. This is
        about the signal's reliability, not the scenario's baked-in
        planning probability in scenario_engine.SCENARIOS (a separate,
        deliberately-static number — see KNOWN_LIMITATIONS.md).
    estimated_duration_days: int, >= 1
        Rough expected days until a re-contracted procurement plan is
        fully in place. Added specifically to drive the Disruption
        Timeline's "days to fully re-contract" slider (app.py) with a
        signal-informed default instead of a fixed guess — a full
        closure headline should suggest a longer adaptation window than a
        warning-level headline. Still user-adjustable in the app either way.
    rationale: str
        One sentence, human-readable, shown directly in the UI. Not used
        by any downstream logic — it exists so a person can sanity-check
        *why* the signal looks the way it does.
    method: str
        One of "llm" (real API call succeeded), "rule_based_fallback"
        (deterministic keyword match, no API key configured), or
        "manual_mock" (a human set the sliders directly in the app,
        bypassing text extraction entirely). Purely a provenance label for
        the UI badge — never affects behavior.

Deliberately NOT in this schema (considered and cut, not overlooked):
`affected_suppliers` — a specific-supplier disruption (e.g. sanctions on
one country, which the original plan's headline categories mention) has no
representation in scenario_engine.SCENARIOS at all right now; every
scenario here is corridor-based. Adding supplier-level signals would need a
new scenario type first — flagged as a real gap, not silently patched over
by stuffing it into this schema without anywhere for it to go.
"""
from llm import call_llm_json, llm_configured

HEADLINES = [
    {
        "id": "h1_strikes",
        "date": "2026-02-28",
        "headline": "US and Israel launch coordinated airstrikes on Iran; Supreme Leader Khamenei killed",
        "source": "Wikipedia — \"2026 Strait of Hormuz crisis\" / \"2026 Iran war\"",
        "body": "Operation Epic Fury: US and Israeli strikes hit Iranian military, nuclear, and "
                "leadership targets. Iran retaliates with missile and drone strikes on Israel and "
                "US bases in the Gulf, including the UAE, Qatar, and Bahrain.",
    },
    {
        "id": "h2_tanker_attacks",
        "date": "2026-03-01",
        "headline": "Oil tanker Skylight struck near Khasab, Oman — two Indian crew killed; tanker "
                    "MKD VYOM hit by drone boat, one more Indian sailor killed",
        "source": "Wikipedia — \"2026 Strait of Hormuz crisis\"",
        "body": "IRGC transmits warnings via VHF radio that no ships will be permitted to pass the "
                "strait. Ship-tracking data shows a 70% reduction in strait traffic within days.",
    },
    {
        "id": "h3_closure_confirmed",
        "date": "2026-03-02",
        "headline": "IRGC officially confirms the Strait of Hormuz is closed, threatens any ship that passes",
        "source": "Wikipedia — \"2026 Strait of Hormuz crisis\"",
        "body": "Shipping traffic through the strait falls toward zero; over 150 ships anchor "
                "outside the strait to avoid the risk.",
    },
    {
        "id": "h4_brent_100",
        "date": "2026-03-08",
        "headline": "Brent crude surpasses $100/barrel for the first time in four years",
        "source": "CNBC / Reuters / The Guardian (via Wikipedia)",
        "body": "Oil prices are rising faster than during any other conflict in recent history; "
                "Brent goes on to peak near $126/barrel — the largest monthly oil price increase "
                "on record.",
        # Independent audit finding M1: this is the ONE curated headline with
        # no corridor keyword ("Brent", "$100", "$126", "oil price" all miss
        # the keyword list below) — it deliberately extracts to
        # corridor=None, severity=0.20, which maps to scenario="baseline".
        # That's a feature, not a bug: it's evidence the extractor reacts to
        # physical chokepoint threats, not price consequences of them, and
        # is kept in the curated set on purpose as an "honest limitation"
        # talking point. Flagged in the UI via `note` so it's never a
        # surprise mid-demo.
        "note": "Deliberately maps to baseline: this headline describes a PRICE "
                "consequence, not a physical chokepoint threat, so it has no corridor "
                "keyword match. Kept in the set on purpose to show the extractor doesn't "
                "overreact to price headlines alone.",
    },
    {
        "id": "h5_full_closure",
        "date": "2026-03-27",
        "headline": "Iran declares the Strait of Hormuz closed to any vessel going \"to and from\" "
                    "US, Israeli, and allied ports",
        "source": "AFP (via Wikipedia)",
        "body": "An estimated 20,000 mariners and 2,000 ships are reported stranded in the Persian Gulf.",
    },
    {
        "id": "h6_us_blockade",
        "date": "2026-04-13",
        "headline": "US Navy begins blockading Iranian ports, creating a \"dual blockade\" of the strait",
        "source": "Wikipedia — \"2026 United States naval blockade of Iran\"",
        "body": "Follows the collapse of the Islamabad Talks. Iran had briefly agreed to reopen the "
                "strait after an 8 April ceasefire, then began charging tolls of over $1 million "
                "per ship instead of a genuine reopening.",
    },
    {
        "id": "h7_redsea_precedent",
        "date": "2024-01-16",
        "headline": "Shell, Reliance and Torm divert tankers from the Red Sea as Houthi attacks continue",
        "source": "S&P Global Commodity Insights (via EIA, \"Red Sea attacks increase shipping "
                   "times and freight rates\", Feb 2024)",
        "body": "Vessels reroute via the Cape of Good Hope. Crude flow through Bab-el-Mandeb falls "
                "~18% in December 2023 versus the Jan-Nov average; tanker rates on affected "
                "routes rise ~20% in a month.",
    },
]

CORRIDOR_KEYWORDS = {
    # "iran"/"irgc"/"persian gulf" are included alongside "hormuz" itself
    # because this demo's curated headline set treats Iran-shipping
    # headlines as de facto Hormuz signals — a narrow heuristic tuned for
    # THIS headline set, not a general-purpose classifier. It's also a
    # deliberately honest illustration of where the rule-based fallback is
    # weaker than the real LLM: a headline about US/Israel striking Iran
    # doesn't say "Hormuz," but a real LLM call correctly infers the
    # causal link (Iran retaliates by threatening the strait it borders)
    # where a keyword match only gets there via this hardcoded list.
    "corridor_hormuz": ["hormuz", "iran", "irgc", "persian gulf", "khasab"],
    "corridor_redsea_suez": ["red sea", "houthi", "bab-el-mandeb", "bab el-mandeb", "suez"],
    "corridor_malacca": ["malacca"],
    "corridor_cape": ["cape of good hope"],
}

# Ordered weakest -> strongest; a later match overrides an earlier one when
# multiple keyword groups appear in the same headline.
SEVERITY_KEYWORDS = [
    (["warns", "warning", "threat", "tension", "divert", "reroute"], 0.35),
    (["struck", "attack", "attacked", "drone", "missile", "killed"], 0.6),
    (["closed", "closure", "blockade", "mines", "mined", "stranded"], 0.9),
]


def _duration_from_severity(severity: float) -> int:
    """Coarse severity -> expected re-contracting window, used by the rule
    -based fallback and as a starting point manual mode's slider can
    override. Not a real forecasting model — a documented, simple bucket."""
    if severity >= 0.9:
        return 14
    if severity >= 0.5:
        return 7
    if severity >= 0.3:
        return 4
    return 3


def _rule_based_extract(text: str) -> dict:
    """Deterministic fallback used whenever no LLM key is configured (see
    llm.py). Not a simulation of the LLM — labeled as what it is."""
    text_l = text.lower()
    corridor = None
    for c, kws in CORRIDOR_KEYWORDS.items():
        if any(kw in text_l for kw in kws):
            corridor = c
            break
    severity = 0.2
    for kws, sev in SEVERITY_KEYWORDS:
        if any(kw in text_l for kw in kws):
            severity = max(severity, sev)
    probability = 0.9 if severity >= 0.9 else (0.6 if severity >= 0.5 else 0.3)
    return {
        "corridor": corridor,
        "severity": round(severity, 2),
        "probability": probability,
        "estimated_duration_days": _duration_from_severity(severity),
        "rationale": "Rule-based keyword match (no ANTHROPIC_API_KEY configured — see llm.py).",
        "method": "rule_based_fallback",
    }


_EXTRACTION_SYSTEM = (
    "You extract structured supply-chain disruption signals from crude-oil shipping headlines. "
    "Respond with ONLY a JSON object, no other text: "
    '{"corridor": one of "corridor_hormuz"/"corridor_redsea_suez"/"corridor_malacca"/'
    '"corridor_cape"/null, "severity": float 0.0-1.0 (0=no disruption, 1=full closure), '
    '"probability": float 0.0-1.0 (confidence this is materializing/materialized, not a '
    'forecast of a future event), "estimated_duration_days": integer >= 1 (rough days until a '
    "re-contracted procurement plan would be fully in place), "
    '"rationale": one sentence}.'
)


def extract_signal(headline: dict) -> dict:
    """headline -> the signal schema documented in this module's docstring.
    Tries the real LLM first (if configured); falls back to the
    deterministic keyword extractor otherwise or on any failure."""
    full_text = f"{headline['headline']}. {headline['body']}"
    if llm_configured():
        prompt = f"Headline: {headline['headline']}\nDetails: {headline['body']}"
        result = call_llm_json(prompt, system=_EXTRACTION_SYSTEM)
        if result and "severity" in result:
            result.setdefault("rationale", "")
            result.setdefault("estimated_duration_days", _duration_from_severity(result.get("severity", 0.0)))
            result["method"] = "llm"
            return result
    return _rule_based_extract(full_text)


def build_manual_signal(corridor: str | None, severity: float, probability: float,
                         duration_days: int, rationale: str = "") -> dict:
    """The third signal source: a human sets these values directly via
    sliders in the app's Manual Signal Override panel, standing in for
    whatever an LLM (or the rule-based fallback) would have produced.
    Returns the exact same schema as extract_signal() so every downstream
    consumer (nearest_scenario, the optimizer, the briefing generator, the
    map's event node) needs zero special-casing for where the signal came
    from."""
    return {
        "corridor": corridor,
        "severity": round(float(severity), 2),
        "probability": round(float(probability), 2),
        "estimated_duration_days": int(duration_days),
        "rationale": rationale or "Manually set — standing in for an LLM/rule-based extraction.",
        "method": "manual_mock",
    }


def nearest_scenario(signal: dict) -> str:
    """Maps an extracted signal onto the closest scenario already defined
    in scenario_engine.SCENARIOS, so the rest of the app (map, optimizer)
    doesn't need a separate code path for LLM-driven vs. manually-picked
    scenarios."""
    corridor = signal.get("corridor")
    severity = signal.get("severity", 0.0) or 0.0
    if corridor == "corridor_hormuz":
        if severity >= 0.75:
            return "hormuz_100"
        if severity >= 0.3:
            return "hormuz_50"
        return "baseline"
    if corridor == "corridor_redsea_suez":
        if severity >= 0.3:
            return "redsea_suspend"
        return "baseline"
    return "baseline"


def make_event_node(headline: dict | None, signal: dict) -> dict:
    """A type="event" node for the Supply Chain Knowledge Graph — this is
    what makes the LLM extraction step genuine KG behavior (per the plan's
    Section 2 note) rather than just a UI filter: the headline literally
    becomes a node linked to the corridor it affects. headline=None
    covers the Manual Signal Override path, which has no source text."""
    if headline is None:
        return {
            "id": "event_manual_mock",
            "type": "event",
            "name": f"Manually-set signal ({signal.get('rationale', '')})",
            "date": None,
            "source": "manual override — no headline",
            "affects_corridor": signal.get("corridor"),
            "severity": signal.get("severity"),
            "extraction_method": signal.get("method"),
        }
    return {
        "id": f"event_{headline['id']}",
        "type": "event",
        "name": headline["headline"],
        "date": headline["date"],
        "source": headline["source"],
        "affects_corridor": signal.get("corridor"),
        "severity": signal.get("severity"),
        "extraction_method": signal.get("method"),
    }


if __name__ == "__main__":
    print(f"LLM configured: {llm_configured()}\n")
    for h in HEADLINES:
        sig = extract_signal(h)
        scen = nearest_scenario(sig)
        print(f"[{h['date']}] {h['headline'][:70]}...")
        print(f"  -> corridor={sig.get('corridor')} severity={sig.get('severity')} "
              f"probability={sig.get('probability')} duration={sig.get('estimated_duration_days')}d "
              f"method={sig.get('method')}")
        print(f"  -> nearest scenario: {scen}\n")
