"""
ET AI Hackathon 2026 — PS2: AI-Driven Energy Supply Chain Resilience

Fourth independent review — direct feedback on the three-tab redesign:
"the scenario tab looks shit and the other tabs does not look professional
at all.. make them look professional and also add some more important
tabs which you removed.. instead of making information clustered.. use
clickable cards and hover text". Two decisions were confirmed with the
user before rebuilding: (1) keep Current system / Scenarios / News as the
three main tabs, but add back a "Details & charts" tab (the old
Prescription/Timeline/Assumptions content, redesigned, not deleted) and a
standalone "Data & methods" tab; (2) go dark, data-dashboard styling.

  Current system   — plain-English explanation + baseline stat cards + map.
  Scenarios        — pick a disruption via clickable pill-cards, get the
                      plain-language story + map. No jargon, no charts.
  News             — same story, triggered by a real dated headline.
  Details & charts — NEW top-level home for everything technical: KPIs,
                      the full technical briefing, cost/shift/refinery
                      charts, and the assumption-robustness stress test.
                      Has its own scenario picker — deliberately NOT wired
                      to "whichever tab you used last", since Streamlit
                      reruns every tab's body on every interaction and
                      there's no reliable way to know which tab a given
                      rerun was "really" triggered from; a tab that's
                      self-contained is more predictable than one that
                      quietly depends on invisible cross-tab state.
  Data & methods   — sources, assumptions, node/edge tables, PPAC-verified
                      figures, and the real-world validation comparison —
                      moved out of a Current-system expander into its own
                      tab so it has a proper home instead of being buried.

Visual design: dark theme set globally via .streamlit/config.toml (so
every native widget — buttons, sliders, dataframes, the pills below —
themes consistently, rather than fighting Streamlit's internal,
non-deterministic CSS class names one widget at a time). The narrative
cards use a small hand-written CSS block for the parts Streamlit doesn't
theme by default (custom HTML cards, hero banner). "Clickable cards" for
the scenario picker are `st.pills` — a real native Streamlit widget
(fully testable via AppTest, unlike a hand-rolled HTML/JS card grid) that
already renders as a horizontal row of clickable, hover-highlighted
pill-buttons. Hover text is native `title="..."` attributes on the custom
HTML cards (real browser tooltips) plus `help=` on native widgets.

Bug fix carried over from the last round: plain_language_story() used to
wrap emphasized words in Markdown "**word**" syntax, but those strings
are always embedded inside raw HTML <div> cards — and Streamlit's
markdown renderer does not re-process Markdown found inside a raw HTML
block, so the asterisks rendered literally instead of bold. Fixed in
briefing_generator.py to emit real <strong> tags instead.

Run: streamlit run app.py
"""
import json
import time
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import pydeck as pdk
import searoute as sr
import streamlit as st
import streamlit.components.v1 as components

import briefing_generator as briefing_gen
import optimizer as opt
import scenario_engine as sceng
import signal_extractor as sig_ext
from animated_map import build_map_html
from llm import llm_configured

DATA_PATH = Path(__file__).parent / "data" / "network.json"
DEFAULT_LAM = 3.0

st.set_page_config(
    page_title="India Crude Supply Chain Digital Twin",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Card CSS — dark data-dashboard palette, matching the .streamlit/config.toml
# theme (base="dark") so custom cards sit naturally next to native widgets
# instead of clashing with them. [title] gets a help cursor so the hover
# tooltips are discoverable, not just present.
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    [title] {cursor: help;}
    .pt-card {background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;
              padding:16px 20px;margin-bottom:12px;box-shadow:0 2px 8px rgba(15,23,42,0.06);}
    .pt-card h4 {margin:0 0 8px 0;font-size:15px;color:#0f172a;}
    .pt-card p {margin:0 0 6px 0;font-size:14.5px;line-height:1.55;color:#334155;}
    .pt-card p:last-child {margin-bottom:0;}
    .pt-card strong {color:#0369a1;}
    .pt-situation {background:#f1f5f9;border:1px dashed #0f766e55;border-radius:10px;
                   padding:12px 18px;margin-bottom:14px;font-size:14.5px;color:#475569;}
    .pt-situation strong {color:#0f766e;}
    .pt-accent-impact {border-left:4px solid #dc2626;}
    .pt-accent-effect {border-left:4px solid #d97706;}
    .pt-accent-actions {border-left:4px solid #0f766e;}
    .pt-accent-plan {border-left:4px solid #2563eb;}
    .pt-hero {background:linear-gradient(135deg,#f0fdfa 0%,#eff6ff 60%,#f8fafc 100%);
              color:#0f172a;border:1px solid #cbd5e1;border-radius:14px;padding:22px 26px;
              margin-bottom:18px;}
    .pt-hero h3 {margin:0 0 8px 0;color:#0f172a;font-size:19px;}
    .pt-hero p {margin:0;font-size:14.5px;line-height:1.65;color:#334155;}
    .pt-hero b {color:#0f766e;}
    .pt-stat-grid {display:flex;flex-wrap:wrap;gap:12px;margin-bottom:16px;}
    .pt-stat {background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;
              padding:14px 16px;flex:1;min-width:170px;transition:border-color .15s;}
    .pt-stat:hover {border-color:#0f766e88;}
    .pt-stat .lbl {font-size:11.5px;color:#64748b;text-transform:uppercase;
                   letter-spacing:.04em;margin-bottom:5px;}
    .pt-stat .num {font-size:22px;font-weight:700;color:#0f172a;line-height:1.2;}
    .pt-stat .sub {font-size:12.5px;color:#64748b;margin-top:5px;}
    .pt-section-title {font-size:16px;font-weight:600;color:#0f172a;margin:6px 0 12px 0;
                       padding-bottom:8px;border-bottom:2px solid #0f766e55;}
    .pt-pointer {background:#f1f5f9;border:1px solid #e2e8f0;border-radius:8px;
                 padding:8px 14px;font-size:13px;color:#475569;margin-top:10px;}
    .pt-pointer b {color:#0f766e;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Data loading (unchanged from before — same engines, same numbers)
# ---------------------------------------------------------------------------


@st.cache_data
def load_network(path: Path, _mtime_key: float) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


network = load_network(DATA_PATH, DATA_PATH.stat().st_mtime)
nodes = pd.DataFrame(network["nodes"])
edges = pd.DataFrame(network["edges"])

NODE_COLORS = {
    "supplier": [230, 57, 70],
    "corridor": [255, 183, 3],
    "port": [42, 157, 143],
    "refinery": [38, 70, 83],
    "spr": [131, 56, 236],
}
NODE_RADIUS = {
    "supplier": 60000,
    "corridor": 45000,
    "port": 30000,
    "refinery": 35000,
    "spr": 25000,
}

nodes["color"] = nodes["type"].map(NODE_COLORS)
nodes["radius"] = nodes["type"].map(NODE_RADIUS)
is_domestic = nodes.get("subtype") == "domestic"
nodes.loc[is_domestic, "color"] = nodes.loc[is_domestic, "color"].apply(lambda _: [251, 133, 0])
nodes.loc[is_domestic, "radius"] = 45000

node_lookup = nodes.set_index("id")[["lat", "lon"]]
edges = edges.join(node_lookup.rename(columns={"lat": "src_lat", "lon": "src_lon"}), on="source")
edges = edges.join(node_lookup.rename(columns={"lat": "tgt_lat", "lon": "tgt_lon"}), on="target")

EDGE_COLORS = {
    "shipping_route": [42, 157, 143],
    "port_to_refinery": [38, 70, 83],
    "domestic_pipeline": [251, 133, 0],
    "spr_link": [131, 56, 236],
}
edges["color"] = edges["type"].map(EDGE_COLORS)

scenario_options = {k: v["label"] for k, v in sceng.SCENARIOS.items()}
corridor_options = {n["id"]: n["name"] for n in network["nodes"] if n["type"] == "corridor"}
node_names = {n["id"]: n["name"] for n in network["nodes"]}

# Icon-prefixed short labels for the pill-card scenario picker. Kept
# separate from scenario_options (the full technical label, still used in
# captions/briefings/tables) because a clickable card needs a label short
# enough to fit on a pill, not a full sentence.
SCENARIO_PILL_LABELS = {
    "baseline": "🟢 Normal day",
    "hormuz_50": "🟡 Hormuz — half blocked",
    "hormuz_100": "🔴 Hormuz — fully closed",
    "redsea_suspend": "🟠 Red Sea — mostly suspended",
}

# ---------------------------------------------------------------------------
# Sidebar — map display options + honesty text, kept out of the main flow
# ---------------------------------------------------------------------------

st.sidebar.title("Digital twin")

with st.sidebar.form("filters_form"):
    visible_node_types = st.multiselect(
        "Node types", options=sorted(nodes["type"].unique()), default=sorted(nodes["type"].unique()),
    )
    visible_edge_types = st.multiselect(
        "Edge types", options=sorted(edges["type"].unique()), default=sorted(edges["type"].unique()),
    )
    st.form_submit_button("Apply filters", use_container_width=True)

use_animated_map = st.sidebar.checkbox(
    "Animated map (client-side)", value=True,
    help="60 fps animation rendered in the browser. Needs internet for a couple of CDN scripts; "
         "switch off for a static map that works offline.",
)

with st.sidebar.expander("About this twin"):
    st.markdown(
        "A live model of how crude oil gets from other countries into India's fuel tanks — and what "
        "happens if a shipping route gets disrupted. Built on public government data (PPAC / "
        "DGCI&S / refinery / SPR filings); ship positions are illustrative, not live tracking. "
        "Under the hood it's a two-stage optimizer: it commits to supplier contracts before a "
        "disruption happens, then works out the cheapest safe response once it does. Full technical "
        "disclosures: KNOWN_LIMITATIONS.md, DATA_SOURCES.md."
    )

nodes_f = nodes[nodes["type"].isin(visible_node_types)].copy()
edges_f = edges[edges["type"].isin(visible_edge_types)].copy()

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

hcol1, hcol2 = st.columns([3, 1])
with hcol1:
    st.title("India Crude Import Digital Twin")
with hcol2:
    st.markdown(
        ("<div style='text-align:right;padding-top:18px;'>"
         + ("<span style='background:#ccfbf1;color:#0f766e;border-radius:999px;"
            "padding:3px 12px;font-size:12px;border:1px solid #99f6e4;'>live LLM</span>" if llm_configured() else
            "<span style='background:#fef3c7;color:#b45309;border-radius:999px;"
            "padding:3px 12px;font-size:12px;border:1px solid #fde68a;'>rule-based signal</span>")
         + " <span style='background:#ccfbf1;color:#0f766e;border-radius:999px;"
           "padding:3px 12px;font-size:12px;border:1px solid #99f6e4;'>solver ready</span></div>"),
        unsafe_allow_html=True,
    )

tab_system, tab_scenarios, tab_news, tab_details, tab_data = st.tabs(
    ["Current system", "Scenarios", "News", "Details & charts", "Data & methods"]
)

# ---------------------------------------------------------------------------
# Shared map-rendering helpers — used by every tab, so they live outside
# every `with tab_x:` block.
# ---------------------------------------------------------------------------

corridor_lookup = {row["id"]: (row["lon"], row["lat"]) for _, row in nodes[nodes["type"] == "corridor"].iterrows()}

# Fallback-only render-only bends, used ONLY if a real searoute lookup
# fails for a given pair (e.g. an unusual coordinate the maritime graph
# can't snap to a sea node). Kept as a safety net, not the primary path
# source anymore — see _real_sea_path() below.
CORRIDOR_PATH_WAYPOINTS = {
    "corridor_redsea_suez": [(36.1, -5.4), (31.3, 32.3)],  # Gibraltar, Port Said
}
EDGE_RENDER_WAYPOINTS = {
    "e_usa_mumbai": [(-34.3, 18.5)],
    "e_usa_sikka": [(-34.3, 18.5)],
}


@st.cache_data(show_spinner=False)
def _real_sea_path(src_lon: float, src_lat: float, tgt_lon: float, tgt_lat: float):
    """Independent-review request: shipping routes used to be a straight
    line from source to destination (or, for the chokepoint corridors, a
    single manually-picked bend point) — geometrically fine for a
    single-server render, but visibly wrong wherever that straight line
    cuts across a continent instead of following the ocean (e.g. USA to
    Mumbai as a straight line crosses the Atlantic AND North Africa/the
    Middle East). `searoute` computes the real shortest sea route between
    two points over a bundled maritime traffic-lane graph — it already
    knows to route through the Suez Canal, around the Cape of Good Hope,
    or through the Strait of Malacca/Hormuz as appropriate, so it also
    makes CORRIDOR_PATH_WAYPOINTS/EDGE_RENDER_WAYPOINTS above obsolete for
    any pair it can solve (kept only as a fallback). Runs fully offline
    (no network call — the maritime graph ships with the package) and is
    fast enough (~0.01-0.1s per pair, cached here so it only runs once per
    edge per process) to compute for every shipping route at startup.
    Returns None on any failure so the caller can fall back safely."""
    try:
        route = sr.searoute((src_lon, src_lat), (tgt_lon, tgt_lat), units="km")
        coords = route["geometry"]["coordinates"]
        if len(coords) < 2:
            return None
        return [[float(lon), float(lat)] for lon, lat in coords]
    except Exception:
        return None


def build_path(row):
    if row["type"] == "shipping_route":
        real = _real_sea_path(row["src_lon"], row["src_lat"], row["tgt_lon"], row["tgt_lat"])
        if real:
            return real
        # Fallback: the old manual-bend approach, only reached if searoute
        # couldn't resolve this specific pair.
        path = [[row["src_lon"], row["src_lat"]]]
        via = row.get("via_corridor")
        if isinstance(via, str) and via in corridor_lookup:
            for wlat, wlon in CORRIDOR_PATH_WAYPOINTS.get(via, []):
                path.append([wlon, wlat])
            path.append(list(corridor_lookup[via]))
        for wlat, wlon in EDGE_RENDER_WAYPOINTS.get(row["id"], []):
            path.append([wlon, wlat])
        path.append([row["tgt_lon"], row["tgt_lat"]])
        return path
    return [[row["src_lon"], row["src_lat"]], [row["tgt_lon"], row["tgt_lat"]]]


def prepare_edges_for_scenario(active_corridor):
    """A fresh per-scenario copy of the filtered edge table: path geometry
    plus which edges are flagged as disrupted for this specific corridor."""
    ef = edges_f.copy()
    ef["path"] = ef.apply(build_path, axis=1)
    ef["is_disrupted"] = (ef["type"] == "shipping_route") & (ef["via_corridor"] == active_corridor)
    max_cap = max(ef.loc[ef["type"] == "shipping_route", "capacity_kbpd"].max(), 1.0)
    ef["render_width"] = ef["capacity_kbpd"].apply(lambda cap: 1.5 + 6.5 * min(1.0, (cap or 0.0) / max_cap))
    return ef


def animated_payload(scenario_key, ef, r1, n_days, signal=None, headline_id=None):
    """Everything the client-side animation needs, computed in Python so JS
    never re-derives a number the model already produced. r1 is the full
    risk-averse optimizer result dict (not just its flows sub-dict) so the
    timeline can read scenario_shortfall_kbpd alongside edge/SPR flows."""
    active_scenario = sceng.SCENARIOS[scenario_key]
    active_corridor = active_scenario["corridor"] if active_scenario["severity"] > 0 else None
    snapshot = sceng.summarize(scenario_key)
    r1_flows = r1.get("flows") if r1 else None
    flows = r1_flows["edge_flow_kbpd"] if r1_flows else None

    payload_edges = []
    for _, row in ef.iterrows():
        eid = row["id"]
        day0 = shock = adapted = None
        if flows and eid in flows:
            day0 = flows[eid].get("baseline", 0.0)
            adapted = flows[eid].get(scenario_key, 0.0)
            if row["type"] == "shipping_route":
                edge_dict = row.to_dict()
                shock = min(day0, sceng.degraded_capacity(edge_dict, active_corridor, active_scenario["severity"]))
            else:
                shock = day0
        payload_edges.append({
            "id": eid, "name": node_names.get(row["source"], row["source"]) + " → " +
                               node_names.get(row["target"], row["target"]),
            "path": row["path"], "type": row["type"],
            "color": list(row["color"]), "cap": float(row["capacity_kbpd"] or 0.0)
                     if row["type"] != "spr_link" else 0.0,
            "day0": day0, "shock": shock, "adapted": adapted,
            "disrupted": bool(row["is_disrupted"]),
        })

    payload_nodes = [{
        "id": r["id"], "name": r["name"], "type": r["type"],
        "lon": r["lon"], "lat": r["lat"], "color": list(r["color"]), "radius": int(r["radius"]),
    } for _, r in nodes_f.iterrows()]

    corridor = None
    if active_corridor is not None and active_corridor in corridor_lookup:
        clon, clat = corridor_lookup[active_corridor]
        corridor = {"lon": clon, "lat": clat, "name": node_names.get(active_corridor, active_corridor)}

    event = None
    if signal and signal.get("corridor") in corridor_lookup:
        ev_lon, ev_lat = corridor_lookup[signal["corridor"]]
        event_headline = next((h for h in sig_ext.HEADLINES if h["id"] == headline_id), None)
        event_node = sig_ext.make_event_node(event_headline, signal)
        event = {"lon": ev_lon + 3.0, "lat": ev_lat + 3.0, "name": event_node["name"]}

    timeline = {"enabled": False}
    if flows and active_corridor is not None:
        spr_flows = r1_flows["spr_draw_kbpd"]
        spr_day0 = sum(v.get("baseline", 0.0) for v in spr_flows.values())
        spr_adapted = sum(v.get(scenario_key, 0.0) for v in spr_flows.values())
        max_draw = sum(n["max_draw_rate_kbpd"] for n in network["nodes"] if n["type"] == "spr")
        raw_gap_shock = snapshot["incremental_gap_kbpd"]
        shortfall_day0 = r1["scenario_shortfall_kbpd"].get("baseline", 0.0)
        shortfall_adapted = r1["scenario_shortfall_kbpd"].get(scenario_key, 0.0)
        timeline = {
            "enabled": True, "n_days": max(1, n_days),
            "spr": {"day0": spr_day0, "shock": min(max_draw, spr_day0 + raw_gap_shock), "adapted": spr_adapted},
            "shortfall": {"day0": shortfall_day0, "shock": max(shortfall_day0, raw_gap_shock), "adapted": shortfall_adapted},
        }

    top_growers = []
    if flows and active_corridor is not None:
        grown = sorted(
            (pe for pe in payload_edges if pe["type"] == "shipping_route"
             and pe["day0"] is not None and pe["adapted"] is not None
             and (pe["adapted"] - pe["day0"]) > 5.0),
            key=lambda pe: -(pe["adapted"] - pe["day0"]),
        )
        top_growers = [{"name": pe["name"], "day0": round(pe["day0"], 0), "adapted": round(pe["adapted"], 0)}
                       for pe in grown[:3]]

    return {
        "nodes": payload_nodes, "edges": payload_edges, "corridor": corridor,
        "severity": float(active_scenario["severity"]), "event": event,
        "timeline": timeline, "scenario_label": scenario_options[scenario_key],
        "top_growers": top_growers,
    }


def render_map(scenario_key, ef, r1=None, n_days=7, signal=None, headline_id=None, height=560):
    """Animated deck.gl map if enabled, else a static pydeck fallback."""
    r1_flows = r1.get("flows") if r1 else None
    active_scenario = sceng.SCENARIOS[scenario_key]
    active_corridor = active_scenario["corridor"] if active_scenario["severity"] > 0 else None

    if use_animated_map:
        payload = animated_payload(scenario_key, ef, r1, n_days, signal=signal, headline_id=headline_id)
        components.html(build_map_html(payload, height=height), height=height)
        cap = "Flow dots show real optimizer output. Red pulse marks the disrupted route."
        if r1_flows and active_corridor is not None:
            cap += " Press Play to watch the shock happen and the plan adapt."
        st.caption(cap)
    else:
        HIGHLIGHT_COLOR = [239, 35, 60]
        normal_edges = ef[~ef["is_disrupted"]]
        disrupted_edges = ef[ef["is_disrupted"]]
        map_layers = [
            pdk.Layer("PathLayer", data=normal_edges, get_path="path", get_color="color",
                      get_width="render_width", width_min_pixels=1.5, pickable=True),
            pdk.Layer("PathLayer", data=disrupted_edges, get_path="path", get_color=HIGHLIGHT_COLOR,
                      get_width="render_width", width_min_pixels=3, pickable=True),
        ]
        nodes_render = nodes_f.copy()
        if active_corridor is not None:
            is_active = nodes_render["id"] == active_corridor
            nodes_render.loc[is_active, "color"] = nodes_render.loc[is_active, "color"].apply(lambda _: HIGHLIGHT_COLOR)
            nodes_render.loc[is_active, "radius"] = 90000
        map_layers.append(pdk.Layer(
            "ScatterplotLayer", data=nodes_render, get_position=["lon", "lat"], get_fill_color="color",
            get_radius="radius", pickable=True, opacity=0.85, stroked=True,
            get_line_color=[15, 23, 42], line_width_min_pixels=1,
        ))
        if signal and signal.get("corridor") in corridor_lookup:
            ev_lon, ev_lat = corridor_lookup[signal["corridor"]]
            event_headline = next((h for h in sig_ext.HEADLINES if h["id"] == headline_id), None)
            event_node = sig_ext.make_event_node(event_headline, signal)
            event_df = pd.DataFrame([{"lon": ev_lon + 3.0, "lat": ev_lat + 3.0, "name": event_node["name"],
                                       "type": f"event ({event_node['extraction_method']})"}])
            map_layers.append(pdk.Layer(
                "ScatterplotLayer", data=event_df, get_position=["lon", "lat"], get_fill_color=[15, 23, 42],
                get_radius=70000, pickable=True, opacity=0.95, stroked=True,
                get_line_color=HIGHLIGHT_COLOR, line_width_min_pixels=3,
            ))
        deck = pdk.Deck(
            layers=map_layers, initial_view_state=pdk.ViewState(latitude=15, longitude=55, zoom=2.3, pitch=25),
            map_style="light",
            tooltip={"html": "<b>{name}</b><br/>type: {type}", "style": {"backgroundColor": "#ffffff", "color": "#0f172a", "border": "1px solid #cbd5e1"}},
        )
        st.pydeck_chart(deck, use_container_width=True)
        cap = "Width scales with capacity."
        if active_corridor is not None:
            cap += f" Red = affected by {scenario_options[scenario_key]}."
        st.caption(cap)


@st.cache_data(show_spinner=False)
def _solve_pair(lam_value: float, _network_mtime_key: float):
    r0 = opt.run_full_network(lam=0.0, include_flows=True)
    r1 = opt.run_full_network(lam=lam_value, include_flows=True)
    return r0, r1


def get_solved(lam_value: float):
    return _solve_pair(lam_value, DATA_PATH.stat().st_mtime)


def stat_card(label, value, sub, tooltip=None):
    title_attr = f' title="{tooltip}"' if tooltip else ""
    return (f"<div class='pt-stat'{title_attr}><div class='lbl'>{label}</div>"
            f"<div class='num'>{value}</div><div class='sub'>{sub}</div></div>")


def render_scenario_experience(scenario_key, signal=None, headline=None, source="manual"):
    """The shared body for the Scenarios and News tabs: plain-language
    story first, map second — nothing technical here anymore (that all
    lives in the Details & charts tab now). Uses a fixed risk-aversion
    level (DEFAULT_LAM) since that's an advanced knob that belongs in the
    technical tab, not a concept a first-time reader needs to see."""
    active_scenario = sceng.SCENARIOS[scenario_key]
    active_corridor = active_scenario["corridor"] if active_scenario["severity"] > 0 else None
    snapshot = sceng.summarize(scenario_key)

    if active_corridor == "corridor_hormuz":
        st.info(
            "**This isn't hypothetical.** The Strait of Hormuz has been effectively closed to shipping "
            "since 28 Feb 2026 and still is today — this mirrors the real, ongoing crisis. Real-world "
            "comparison numbers are in the Data & methods tab."
        )

    r0, r1 = get_solved(DEFAULT_LAM)
    facts = briefing_gen._build_facts(
        headline, signal, scenario_key, scenario_options[scenario_key], snapshot, r0, r1, network, node_names,
    )
    story = briefing_gen.plain_language_story(facts, network)

    st.markdown(f"<div class='pt-situation'>{story['situation']}</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            f"<div class='pt-card pt-accent-impact' title='The size of the disruption and the supply "
            f"gap it creates, in plain numbers.'><h4>📉 Impact</h4><p>{story['impact']}</p></div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='pt-card pt-accent-effect' title='Which refineries feel it first, and how badly.'>"
            f"<h4>🏭 Effect on India</h4><p>{story['effect']}</p></div>",
            unsafe_allow_html=True,
        )
    with c2:
        actions_html = "".join(f"<p>• {a}</p>" for a in story["actions"])
        st.markdown(
            f"<div class='pt-card pt-accent-actions' title='The concrete response: reserves, spot "
            f"purchases, supplier shifts.'><h4>✅ What to do</h4>{actions_html}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='pt-card pt-accent-plan' title='How the response unfolds over time, and roughly "
            f"what it costs.'><h4>📅 The plan</h4><p>{story['plan']}</p>"
            f"<p style='opacity:.75;font-size:13px;'>{story['cost']}</p></div>",
            unsafe_allow_html=True,
        )

    ef = prepare_edges_for_scenario(active_corridor)
    n_days = int((signal or {}).get("estimated_duration_days") or 7)
    render_map(scenario_key, ef, r1=r1, n_days=n_days, signal=signal,
               headline_id=(headline or {}).get("id"), height=560)

    st.markdown(
        "<div class='pt-pointer'>Want the underlying numbers, cost charts, and a stress-test of the "
        "assumptions? Open <b>Details &amp; charts</b>. Full sources and real-world validation are in "
        "<b>Data &amp; methods</b>.</div>",
        unsafe_allow_html=True,
    )


def render_technical_breakdown(default_scenario_key, pill_key):
    """Self-contained technical view: its own scenario picker, its own
    risk-aversion slider, its own solve — everything from the old
    Prescription/Timeline/Assumptions tabs, kept in full, just given a
    proper tab of its own instead of a single collapsed expander."""
    scenario_key = st.pills(
        "Situation", options=list(scenario_options.keys()),
        format_func=lambda k: SCENARIO_PILL_LABELS[k], default=default_scenario_key, key=pill_key,
    )
    if scenario_key is None:
        scenario_key = default_scenario_key
    snapshot = sceng.summarize(scenario_key)

    lam = st.slider(
        "How cautious should the plan be? 0 = cheapest on average, higher = safer against the worst case.",
        min_value=0.0, max_value=6.0, value=st.session_state.get("lam_value", DEFAULT_LAM), step=0.5,
        key="det_lam",
    )
    st.session_state["lam_value"] = lam
    r0, r1 = get_solved(lam)

    is_domestic_supplier = nodes.get("subtype") == "domestic"
    _hormuz_edges = edges.loc[edges["via_corridor"] == "corridor_hormuz"]
    hormuz_exposure = (_hormuz_edges["capacity_kbpd"] * _hormuz_edges["chokepoint_exposure"]).sum()

    st.markdown("<div class='pt-section-title'>Key numbers</div>", unsafe_allow_html=True)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("At-risk capacity", f"{snapshot['total_capacity_lost_kbpd']:,.0f} kbpd")
    k2.metric("Supply gap (vs. baseline)", f"{snapshot['incremental_gap_kbpd']:,.0f} kbpd")
    k3.metric("Emergency-reserve endurance", f"{snapshot['days_of_cover_if_unmitigated'] or '—'} days")
    k4.metric("Hormuz exposure (weighted)", f"{hormuz_exposure:,.0f} kbpd")
    coverage = snapshot.get("spr_coverage_fraction")
    if coverage is not None and coverage < 1.0:
        st.warning(
            f"The emergency reserve alone can cover about {coverage * 100:.0f}% of this gap at max "
            f"drawdown — the rest needs rerouting, spot purchases, or curtailment."
        )

    briefing_text, briefing_method = briefing_gen.generate_briefing(
        headline=None, signal=None, scenario_key=scenario_key,
        scenario_label=scenario_options[scenario_key], snapshot=snapshot, r0=r0, r1=r1, network=network,
    )
    method_label = "🟢 LLM-drafted" if briefing_method == "llm" else "🟡 template-drafted"
    st.markdown(f"<div class='pt-section-title'>Full technical briefing ({method_label})</div>", unsafe_allow_html=True)
    st.markdown(briefing_text)

    st.markdown("<div class='pt-section-title'>Cost and supplier-shift charts</div>", unsafe_allow_html=True)
    worst = r0["worst_scenario"]
    money_fig, (money_ax1, money_ax2) = plt.subplots(1, 2, figsize=(9, 3.2))
    money_fig.patch.set_facecolor("#ffffff")
    for ax, title, vals in (
        (money_ax1, "Expected cost ($/day)", [r0["expected_cost_usd_per_day"], r1["expected_cost_usd_per_day"]]),
        (money_ax2, f"Worst-case ({worst}) cost ($/day)",
         [r0["scenario_costs_usd_per_day"][worst], r1["scenario_costs_usd_per_day"][worst]]),
    ):
        ax.set_facecolor("#ffffff")
        ax.bar(["Cheapest on average", "Risk-averse"], vals, color=["#0f766e", "#dc2626"])
        ax.set_title(title, fontsize=10, color="#0f172a")
        ax.ticklabel_format(axis="y", style="plain")
        ax.tick_params(colors="#475569")
        for spine in ax.spines.values():
            spine.set_color("#cbd5e1")
    money_fig.tight_layout()
    st.pyplot(money_fig, use_container_width=True)

    all_suppliers = sorted(set(r0["contract_by_supplier_kbpd"]) | set(r1["contract_by_supplier_kbpd"]),
                            key=lambda s: -r0["contract_by_supplier_kbpd"].get(s, 0))
    shift_rows = []
    for sp in all_suppliers:
        c0 = r0["contract_by_supplier_kbpd"].get(sp, 0.0)
        c1 = r1["contract_by_supplier_kbpd"].get(sp, 0.0)
        if abs(c1 - c0) > 1.0:
            shift_rows.append({"supplier": node_names.get(sp, sp), "cheapest-on-average (kbpd)": c0,
                                "risk-averse (kbpd)": c1, "shift (kbpd)": round(c1 - c0, 1)})
    if shift_rows:
        shift_df = pd.DataFrame(shift_rows).sort_values("shift (kbpd)")
        shift_fig, shift_ax = plt.subplots(figsize=(8, 0.45 * len(shift_df) + 0.5))
        shift_fig.patch.set_facecolor("#ffffff")
        shift_ax.set_facecolor("#ffffff")
        bar_colors = ["#dc2626" if s < 0 else "#0f766e" for s in shift_df["shift (kbpd)"]]
        shift_ax.barh(shift_df["supplier"], shift_df["shift (kbpd)"], color=bar_colors)
        shift_ax.axvline(0, color="#94a3b8", linewidth=0.8)
        shift_ax.set_xlabel("Contract change (kbpd)", color="#0f172a")
        shift_ax.tick_params(colors="#475569")
        for spine in shift_ax.spines.values():
            spine.set_color("#cbd5e1")
        shift_fig.tight_layout()
        st.pyplot(shift_fig, use_container_width=True)

    if snapshot["worst_hit_refineries"]:
        st.markdown("<div class='pt-section-title'>Refinery impact detail</div>", unsafe_allow_html=True)
        ref_df = pd.DataFrame(snapshot["worst_hit_refineries"])
        ref_df = ref_df[ref_df["gap_kbpd"] > 0].sort_values("utilization_pct")
        if not ref_df.empty:
            util_fig, util_ax = plt.subplots(figsize=(8, 0.45 * len(ref_df) + 0.5))
            util_fig.patch.set_facecolor("#ffffff")
            util_ax.set_facecolor("#ffffff")
            bar_colors = ["#dc2626" if u < 60 else "#d97706" if u < 90 else "#0f766e" for u in ref_df["utilization_pct"]]
            util_ax.barh(ref_df["refinery"], ref_df["utilization_pct"], color=bar_colors)
            util_ax.set_xlim(0, 100)
            util_ax.set_xlabel("% of demand still served", color="#0f172a")
            util_ax.tick_params(colors="#475569")
            for spine in util_ax.spines.values():
                spine.set_color("#cbd5e1")
            util_fig.tight_layout()
            st.pyplot(util_fig, use_container_width=True)
        st.dataframe(pd.DataFrame(snapshot["worst_hit_refineries"]), use_container_width=True, hide_index=True)

    st.markdown("<div class='pt-section-title'>Stress-test the assumptions behind these dollar figures</div>",
                unsafe_allow_html=True)
    col_a1, col_a2 = st.columns(2)
    with col_a1:
        shortfall_penalty = st.slider("Shortfall penalty ($/bbl)", 75, 225, 150, 5, key="det_penalty")
        spot_premium = st.slider("Spot-market premium ($/bbl)", 3.0, 9.0, 6.0, 0.5, key="det_premium")
    with col_a2:
        take_or_pay = st.slider("Take-or-pay minimum offtake (fraction)", 0.35, 1.0, 0.70, 0.05, key="det_top")
        hormuz_100_prob = st.slider("P(Hormuz full closure) planning assumption", 0.025, 0.075, 0.05, 0.005, key="det_hprob")
    if st.button("Run robustness check", key="det_robustness_btn"):
        with st.spinner("Solving base-assumption and slider-stressed models..."):
            base_run = opt.run_full_network(lam=lam)
            stressed_run = opt.run_full_network(
                lam=lam, shortfall_penalty_usd_bbl=shortfall_penalty, spot_premium_usd_bbl=spot_premium,
                take_or_pay_fraction=take_or_pay, probability_overrides={"hormuz_100": hormuz_100_prob},
            )

        def _top_suppliers(res, n=2):
            ranked = sorted(res["contract_by_supplier_kbpd"], key=lambda s: -res["contract_by_supplier_kbpd"][s])
            return ranked[:n]

        base_top, stressed_top = _top_suppliers(base_run), _top_suppliers(stressed_run)
        if set(base_top) == set(stressed_top):
            st.success(f"Top-2 contracted suppliers unchanged: {', '.join(node_names.get(s, s) for s in base_top)}. "
                       f"The recommendation is stable across this range of assumptions.")
        else:
            st.warning(f"Top-2 suppliers shifted from {', '.join(node_names.get(s, s) for s in base_top)} to "
                       f"{', '.join(node_names.get(s, s) for s in stressed_top)} at these slider values.")


# ---------------------------------------------------------------------------
# Tab 1 — Current system: plain-English explanation + today's baseline
# ---------------------------------------------------------------------------

with tab_system:
    st.markdown(
        "<div class='pt-hero'><h3>What this is</h3>"
        "<p>This is a live model of how crude oil travels from other countries into India's fuel "
        "tanks — from oil fields and ports abroad, through ships and pipelines, to refineries. "
        "It watches for real-world disruptions (like a blocked shipping route), works out exactly "
        "how much oil supply that would remove and from where, and recommends the cheapest safe way "
        "to make up the difference. Three steps: <b>Sense</b> (read a disruption signal), "
        "<b>Simulate</b> (work out the damage), <b>Prescribe</b> (recommend the response).</p></div>",
        unsafe_allow_html=True,
    )

    is_domestic_supplier = nodes.get("subtype") == "domestic"
    total_import_kbpd = nodes.loc[(nodes["type"] == "supplier") & ~is_domestic_supplier, "flow_kbpd"].sum()
    total_domestic_kbpd = nodes.loc[(nodes["type"] == "supplier") & is_domestic_supplier, "flow_kbpd"].sum()
    total_refinery_cap = nodes.loc[nodes["type"] == "refinery", "capacity_kbpd"].sum()
    total_spr_mmt = nodes.loc[nodes["type"] == "spr", "inventory_mmt"].sum()
    _hormuz_edges = edges.loc[edges["via_corridor"] == "corridor_hormuz"]
    hormuz_exposure = (_hormuz_edges["capacity_kbpd"] * _hormuz_edges["chokepoint_exposure"]).sum()
    hormuz_pct = (hormuz_exposure / total_import_kbpd * 100) if total_import_kbpd else 0.0

    st.markdown(
        "<div class='pt-stat-grid'>"
        + stat_card("Oil imported daily", f"{total_import_kbpd:,.0f} kbpd",
                    "thousand barrels a day, from other countries",
                    "kbpd = thousand barrels per day, the standard unit for national oil flows.")
        + stat_card("India's own oil", f"{total_domestic_kbpd:,.0f} kbpd", "produced domestically")
        + stat_card("Refining capacity", f"{total_refinery_cap:,.0f} kbpd",
                    "how much crude India's refineries can turn into fuel")
        + stat_card("Emergency reserve", f"{total_spr_mmt:.2f} MMT",
                    "~9-10 days of national consumption, stockpiled for a crisis",
                    "MMT = million metric tonnes. This is India's Strategic Petroleum Reserve (SPR).")
        + stat_card("Strait of Hormuz dependence", f"{hormuz_pct:.0f}%",
                    "of imports pass through this one chokepoint",
                    "Weighted by how exposed each shipping route actually is, not just whether it touches the strait.")
        + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div class='pt-section-title'>What a normal day looks like</div>", unsafe_allow_html=True)
    ef0 = prepare_edges_for_scenario(None)
    render_map("baseline", ef0, r1=None, n_days=7, height=560)
    st.caption(
        "No disruption applied — this is the normal flow of oil into India. Open the 'Scenarios' or "
        "'News' tab to see what changes when something goes wrong."
    )

    with st.expander("❓ How this system works, in a bit more detail"):
        st.markdown(
            "- **Sense** — a disruption is described either by picking a real dated headline (News "
            "tab) or a scenario directly (Scenarios tab). Either way it becomes the same small set of "
            "facts: which chokepoint, how severe, how long it's expected to last.\n"
            "- **Simulate** — the model already knows every supplier, ship route, port, pipeline, "
            "refinery, and emergency reserve in India's crude supply chain (47 nodes, 45 routes, from "
            "public PPAC/DGCI&S/refinery/SPR data). Removing capacity at the affected chokepoint shows "
            "exactly which refineries would run short, and by how much.\n"
            "- **Prescribe** — an optimizer (a solver that tries millions of combinations in a fraction "
            "of a second) decides the cheapest safe way to close that gap: drawing the emergency "
            "reserve, buying extra oil on the spot market, or shifting future contracts toward "
            "suppliers that aren't affected. It's deliberately a bit cautious (it plans for the worst "
            "case a little, not just the average case) so a plan doesn't quietly rely on a chokepoint "
            "staying open.\n"
            "- Nothing here is a live news feed or live ship-tracking — headlines are a small, dated, "
            "sourced set (documented scope cut for a solo build), and ship positions are illustrative. "
            "Every number the model produces, though, is real optimizer output, not a canned answer."
        )

    st.markdown(
        "<div class='pt-pointer'>Full data sources, node/edge tables, and the real-world validation "
        "comparison live in <b>Data &amp; methods</b>.</div>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Tab 2 — Scenarios: pick a disruption via clickable pill-cards
# ---------------------------------------------------------------------------

with tab_scenarios:
    st.markdown(
        "Pick a situation below to see, in plain terms, what would happen and what India would do "
        "about it."
    )
    scenario_key = st.pills(
        "Situation", options=list(scenario_options.keys()), format_func=lambda k: SCENARIO_PILL_LABELS[k],
        default="hormuz_100", key="scn_pill",
    )
    if scenario_key is None:
        scenario_key = "baseline"
    st.caption(scenario_options[scenario_key])
    render_scenario_experience(scenario_key, source="manual")

# ---------------------------------------------------------------------------
# Tab 3 — News: same story, triggered by a real dated headline
# ---------------------------------------------------------------------------

with tab_news:
    st.markdown(
        "Pick a real headline about a crude-oil disruption and see, end to end, what it would mean "
        "for India — no jargon, no separate tabs to piece together."
    )
    headline_id = st.radio(
        "Headlines", options=[h["id"] for h in sig_ext.HEADLINES],
        format_func=lambda k: next(f"[{h['date']}] {h['headline']}" for h in sig_ext.HEADLINES if h["id"] == k),
        key="news_headline_pick", label_visibility="collapsed",
    )
    selected_headline = next(h for h in sig_ext.HEADLINES if h["id"] == headline_id)
    st.caption(f"{selected_headline['body']} — {selected_headline['source']}")
    if selected_headline.get("note"):
        st.info(selected_headline["note"])

    go_clicked = st.button("See what this means for India →", type="primary", key="news_go")
    if go_clicked:
        with st.spinner("Reading the headline and working out the impact..."):
            t0 = time.perf_counter()
            signal = sig_ext.extract_signal(selected_headline)
            new_scenario_key = sig_ext.nearest_scenario(signal)
            elapsed = time.perf_counter() - t0
        st.session_state["news_signal"] = signal
        st.session_state["news_headline_id"] = headline_id
        st.session_state["news_scenario_key"] = new_scenario_key
        st.session_state["news_elapsed"] = elapsed

    result_visible = (
        st.session_state.get("news_headline_id") == headline_id and "news_signal" in st.session_state
    )
    if result_visible:
        method_badges = {"llm": "🟢 read by the live LLM", "rule_based_fallback": "🟡 read by rule-based keyword match",
                          "manual_mock": "🔵 manually set"}
        signal = st.session_state["news_signal"]
        st.caption(
            f"{method_badges.get(signal.get('method'), signal.get('method', '—'))} in "
            f"{st.session_state['news_elapsed']:.2f} seconds."
        )
        render_scenario_experience(
            st.session_state["news_scenario_key"], signal=signal, headline=selected_headline, source="headline",
        )
    else:
        st.caption("Click the button above to see the full breakdown for this headline.")

# ---------------------------------------------------------------------------
# Tab 4 — Details & charts: everything technical, in one proper home
# ---------------------------------------------------------------------------

with tab_details:
    st.markdown(
        "The numbers, charts, and stress-tests behind the plain-language stories in Scenarios and "
        "News. Pick a situation here independently of the other tabs."
    )
    render_technical_breakdown(default_scenario_key="hormuz_100", pill_key="det_pill")

# ---------------------------------------------------------------------------
# Tab 5 — Data & methods: sources, tables, real-world validation
# ---------------------------------------------------------------------------

with tab_data:
    st.markdown(
        f"PPAC-verified context: imports {total_import_kbpd:,.0f} kbpd · indigenous "
        f"{total_domestic_kbpd:,.0f} kbpd · modeled refinery capacity {total_refinery_cap:,.0f} kbpd · "
        f"emergency reserve {total_spr_mmt:.2f} MMT."
    )
    st.markdown("<div class='pt-section-title'>Data assumptions</div>", unsafe_allow_html=True)
    for a in network["meta"]["assumptions"]:
        st.markdown(f"- {a}")
    st.markdown("<div class='pt-section-title'>Sources</div>", unsafe_allow_html=True)
    for s in network["meta"]["sources"]:
        st.markdown(f"- {s}")
    st.markdown("<div class='pt-section-title'>Node table</div>", unsafe_allow_html=True)
    st.dataframe(nodes_f.drop(columns=["color", "radius"]), use_container_width=True)
    st.markdown("<div class='pt-section-title'>Edge table</div>", unsafe_allow_html=True)
    st.dataframe(
        edges_f.drop(columns=["color", "src_lat", "src_lon", "tgt_lat", "tgt_lon"], errors="ignore"),
        use_container_width=True,
    )
    st.markdown("<div class='pt-section-title'>PPAC-verified figures (from user-provided source documents)</div>",
                unsafe_allow_html=True)
    st.json(network["meta"].get("verified_from_provided_documents", {}))
    st.markdown("<div class='pt-section-title'>Does this match what's actually happening in the real world?</div>",
                unsafe_allow_html=True)
    st.markdown(
        "Checked via live web search on 2026-07-21 (this event postdates any static training "
        "cutoff, so it was verified directly rather than recalled) — full citations in "
        "KNOWN_LIMITATIONS.md §8a.\n\n"
        "**The Strait of Hormuz has been effectively closed since 28 Feb 2026 and still is "
        "today.** The full-closure scenario in the Scenarios tab is not a stress-test invented "
        "for a demo — it is the actual, ongoing situation.\n\n"
        "| Metric | This model | Real-world reported |\n"
        "|---|---|---|\n"
        "| Hormuz-routed import share | 48.2% (exposure-weighted) | 40-52% (multiple sources) |\n"
        "| Capacity/flow lost under full closure | 48.2% (2,380 of 4,936.2 kbpd) | \"over 40%\" of "
        "crude flows lost (OilPrice.com) |\n"
        "| Emergency reserve | 5.33 MMT, ~9.5 days at full fill | 5.33 MMT, \"9-10 days of cover\" "
        "(same PIB-sourced figure, independently reported) |\n"
        "| Diversification direction | Risk-averse plan shifts contracts away from Hormuz-exposed "
        "suppliers | India secured ~70% of imports from outside Hormuz by 11 Mar 2026 (Petroleum "
        "Ministry) |\n\n"
        "**What this model does NOT capture:** the IEA's coordinated 400M-barrel strategic "
        "release, GDP/rupee/capital-flow effects, price-controlled retail fuel losses to OMCs, "
        "and the human cost of the conflict."
    )
