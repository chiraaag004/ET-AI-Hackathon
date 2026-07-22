"""
Client-side animated map component (deck.gl, no Streamlit reruns).

Why a component instead of st.pydeck_chart: any animation driven from
Python requires a full Streamlit rerun per frame — it stutters and can
re-trigger solves. Here the browser runs a requestAnimationFrame loop at
60 fps over data Python serialized ONCE per rerun. Python stays the
source of truth for every number (flows, degraded capacities, SPR/
shortfall interpolation anchors are all computed in app.py and injected);
JS only interpolates and draws.

Visual language (same four meanings as the rest of the app):
  teal  = flowing normally      red  = disrupted / below normal
  gold  = reroute absorbing more purple = SPR    orange = domestic

Effects:
  1. Flow dots stream along each route; count and speed scale with volume.
  2. Disrupted corridor gets a pulsing red ring; its routes' dots slow,
     thin out, and turn red as severity bites.
  3. Timeline auto-play (only when optimizer flows exist): day 0 (normal)
     -> day 1 (shock) -> day N (adapted plan), interpolating widths,
     colors, dot speeds and the SPR/unmet-demand counters — the same
     arithmetic as the Python timeline, run client-side at 60 fps.

Falls back gracefully: if the CDN scripts can't load (offline demo), the
component shows a one-line notice — app.py keeps the static pydeck map
available behind a sidebar toggle, so the demo can never be stranded.

Basemap: previously used maplibre-gl + a CARTO-hosted vector tile style.
Reported bug: inside Streamlit's sandboxed components.html iframe, that
tile/style fetch silently failed in practice, leaving lines/dots floating
over pure black with no landmasses ("the countries does not show"). Fixed
by dropping the live tile-server dependency entirely: land is now a single
static TopoJSON fetch (world-atlas, decoded client-side with
topojson-client) rendered as one deck.gl GeoJsonLayer. This is a much
smaller failure surface than a full raster/vector tile basemap (one GET
instead of many per-zoom tile requests), and if it does fail, it fails
silently — dots/lines still render on black, same as before, never a
blocking error.

Camera state: best-effort persisted to sessionStorage so panning/zooming
survives a Streamlit rerun (which fully remounts this component). Wrapped
in try/catch since some iframe sandboxing configurations block storage
access entirely — if that happens, the camera just resets, same as before
this change (no regression either way).
"""
import json


def build_map_html(payload: dict, height: int = 600) -> str:
    """payload keys (all computed in app.py, never in JS):
      nodes: [{id,name,type,lon,lat,color:[r,g,b],radius}]
      edges: [{id,name,path:[[lon,lat]..],type,color:[r,g,b],cap,
               day0,shock,adapted,disrupted:bool}]
      corridor: {lon,lat,name} | null       — active disrupted chokepoint
      severity: float                        — active scenario severity
      event: {lon,lat,name} | null           — extracted headline event node
      timeline: {enabled:bool, n_days:int,
                 spr:{day0,shock,adapted}, shortfall:{day0,shock,adapted}}
      scenario_label: str
      top_growers: [{name,day0,adapted}]     — routes that pick up the most
                    slack in the adapted plan (empty list if no solve yet or
                    baseline). This is the "what's the better alternative"
                    answer surfaced directly on the primary view, not just
                    buried in the static Timeline tab.
    """
    data_json = json.dumps(payload)
    return """
<div id="wrap" style="position:relative;width:100%;height:""" + str(height - 10) + """px;background:#dbeafe;border-radius:8px;overflow:hidden;font-family:sans-serif;">
  <div id="map" style="position:absolute;inset:0;"></div>
  <div id="fallback" style="display:none;position:absolute;inset:0;color:#475569;align-items:center;justify-content:center;font-size:13px;">
    deck.gl unavailable (offline?) — use the static map toggle in the sidebar.
  </div>
  <div id="hud" style="position:absolute;top:10px;left:10px;background:rgba(255,255,255,0.92);border:1px solid #cbd5e1;border-radius:8px;padding:8px 12px;color:#0f172a;font-size:12px;max-width:320px;box-shadow:0 2px 8px rgba(15,23,42,0.08);">
    <div id="hud-title" style="font-weight:600;font-size:13px;margin-bottom:2px;"></div>
    <div id="hud-sub" style="color:#475569;"></div>
    <div id="hud-alts" style="display:none;margin-top:6px;padding-top:6px;border-top:1px solid #cbd5e1;"></div>
  </div>
  <div id="controls" style="display:none;position:absolute;bottom:10px;left:10px;right:10px;background:rgba(255,255,255,0.94);border:1px solid #cbd5e1;border-radius:8px;padding:8px 14px;color:#0f172a;font-size:12px;align-items:center;gap:12px;box-shadow:0 2px 8px rgba(15,23,42,0.08);">
    <button id="playbtn" style="background:#0f766e;color:#fff;border:none;border-radius:6px;padding:6px 14px;font-size:13px;cursor:pointer;">&#9654; Play disruption</button>
    <input id="dayscrub" type="range" min="0" step="0.01" value="0" style="flex:1;accent-color:#0f766e;">
    <span id="daylabel" style="min-width:64px;font-weight:600;"></span>
    <span style="color:#475569;">SPR draw</span><span id="sprval" style="min-width:70px;font-weight:600;color:#7c3aed;"></span>
    <span style="color:#475569;">unmet</span><span id="shortval" style="min-width:70px;font-weight:600;color:#dc2626;"></span>
  </div>
  <div id="legend" style="position:absolute;top:10px;right:10px;background:rgba(255,255,255,0.92);border:1px solid #cbd5e1;border-radius:8px;padding:6px 10px;color:#475569;font-size:11px;line-height:1.7;box-shadow:0 2px 8px rgba(15,23,42,0.08);">
    <span style="color:#0f766e;">&#9644;</span> normal &nbsp;<span style="color:#dc2626;">&#9644;</span> disrupted &nbsp;<span style="color:#d97706;">&#9644;</span> reroute &nbsp;<span style="color:#7c3aed;">&#9679;</span> SPR<br/>
    <span style="color:#ea580c;">&#9644;</span> domestic &nbsp;<span style="color:#64748b;">&#9644;</span> port&rarr;refinery
  </div>
</div>
<script src="https://unpkg.com/deck.gl@9.0.34/dist.min.js"></script>
<script src="https://unpkg.com/topojson-client@3/dist/topojson-client.min.js"></script>
<script>
const DATA = """ + data_json + """;
(function(){
  if (typeof deck === "undefined") {
    document.getElementById("fallback").style.display = "flex";
    return;
  }
  const TEAL=[42,157,143], RED=[239,35,60], GOLD=[255,183,3], SLATE=[70,90,110], ORANGE=[251,133,0], PURPLE=[131,56,236];

  document.getElementById("hud-title").textContent = "India crude digital twin";
  document.getElementById("hud-sub").textContent = DATA.scenario_label || "";

  // "What's the better alternative" — surfaced directly on the primary
  // view instead of only in the static Timeline tab, per the original ask:
  // don't just show numbers, show what the plan actually reroutes to.
  if (DATA.top_growers && DATA.top_growers.length) {
    const altsEl = document.getElementById("hud-alts");
    altsEl.style.display = "block";
    altsEl.innerHTML = "<div style='font-weight:600;color:#0f172a;'>Better alternatives (adapted plan)</div>" +
      DATA.top_growers.map(g =>
        "<div>" + g.name + ": " + Math.round(g.day0).toLocaleString() + " &rarr; " +
        Math.round(g.adapted).toLocaleString() + " kbpd</div>"
      ).join("");
  }

  // --- geometry precompute: cumulative arc lengths per edge path ---
  DATA.edges.forEach(e => {
    let cum = [0];
    for (let i = 1; i < e.path.length; i++) {
      const dx = e.path[i][0]-e.path[i-1][0], dy = e.path[i][1]-e.path[i-1][1];
      cum.push(cum[i-1] + Math.hypot(dx, dy));
    }
    e.cum = cum; e.len = cum[cum.length-1] || 1;
  });
  function pointAt(e, frac) {
    const target = frac * e.len;
    let i = 1;
    while (i < e.cum.length && e.cum[i] < target) i++;
    if (i >= e.path.length) return e.path[e.path.length-1];
    const seg = e.cum[i]-e.cum[i-1] || 1, t = (target-e.cum[i-1])/seg;
    return [e.path[i-1][0]+t*(e.path[i][0]-e.path[i-1][0]), e.path[i-1][1]+t*(e.path[i][1]-e.path[i-1][1])];
  }

  // --- land layer: one static TopoJSON fetch, decoded once, rendered as
  // a plain GeoJsonLayer under everything else. No live tile server, no
  // per-zoom requests — the smallest possible failure surface for "does
  // geography show up." Fails silently (dots/lines keep working on black)
  // rather than blocking anything if the fetch or decode doesn't work. ---
  let landLayer = null;
  fetch("https://unpkg.com/world-atlas@2/land-110m.json")
    .then(r => r.json())
    .then(topo => {
      const land = topojson.feature(topo, topo.objects.land);
      landLayer = new deck.GeoJsonLayer({
        id: "land", data: land, stroked: true, filled: true,
        getFillColor: [248, 250, 252, 255], getLineColor: [148, 163, 184, 255],
        lineWidthMinPixels: 1,
      });
    })
    .catch(() => { /* land just won't render — everything else still does */ });

  const maxRef = Math.max(1, ...DATA.edges.map(e => Math.max(e.cap||0, e.day0||0, e.adapted||0)));
  const TL = DATA.timeline || {enabled:false};
  const nDays = TL.enabled ? TL.n_days : 1;
  let dayPos = 0.0;           // continuous day position (timeline mode)
  let playing = false;
  let t0 = performance.now();

  // displayed flow for an edge at continuous day d (matches app.py math)
  function dispFlow(e, d) {
    if (!TL.enabled || e.day0 == null) return (e.day0 != null ? e.day0 : e.cap) || 0;
    if (d <= 0.001) return e.day0;
    const shock = e.shock;
    if (d <= 1 || nDays <= 1) {
      const t = Math.min(1, d);           // smooth 0->1 into the shock
      return e.day0 + t * (shock - e.day0);
    }
    const t = (d - 1) / (nDays - 1);
    return shock + t * (e.adapted - shock);
  }
  function lerp3(a, b, t){ return [a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t, a[2]+(b[2]-a[2])*t]; }
  function edgeColor(e, d, flow) {
    if (e.type === "spr_link") return PURPLE;
    if (e.type === "domestic_pipeline") return ORANGE;
    if (e.type === "port_to_refinery") return SLATE;
    if (!TL.enabled || e.day0 == null) return (e.disrupted && DATA.severity > 0) ? RED : TEAL;
    if (d <= 0.001) return TEAL;
    if (e.day0 <= 0.000001) return (e.adapted - e.day0 > 1) ? GOLD : TEAL;
    const chg = (flow - e.day0) / e.day0;
    if (chg <= -0.10) return lerp3(TEAL, RED, Math.min(1, -chg*2));
    if ((e.adapted - e.day0) > 5 && flow > e.day0*1.05) return GOLD;
    return TEAL;
  }
  function widthOf(flow){ return 1.5 + 7.0 * Math.min(1, (flow||0)/maxRef); }
  function interp(v, d){   // {day0,shock,adapted} counters, same math
    if (!TL.enabled || d <= 0.001) return v.day0;
    if (d <= 1 || nDays <= 1) return v.day0 + Math.min(1,d)*(v.shock - v.day0);
    return v.shock + (d-1)/(nDays-1)*(v.adapted - v.shock);
  }

  function buildLayers(nowMs) {
    const d = dayPos;
    const tSec = (nowMs - t0) / 1000;
    const edgeData = DATA.edges.map(e => {
      const f = dispFlow(e, d);
      return {...e, _flow: f, _color: edgeColor(e, d, f), _width: widthOf(f)};
    });

    // flowing dots: count + speed scale with flow; disrupted routes starve
    const dots = [];
    edgeData.forEach(e => {
      if (e.type === "spr_link") return;
      const rel = Math.min(1, e._flow / maxRef);
      if (rel < 0.01) return;
      const n = Math.max(1, Math.round(1 + 4*rel));
      const speed = 0.05 + 0.16*rel;
      for (let i = 0; i < n; i++) {
        const frac = ((tSec*speed) + i/n + (e.id.length%7)/7) % 1;
        dots.push({position: pointAt(e, frac), color: e._color, size: 2.2 + 2.2*rel});
      }
    });

    const layers = [];
    if (landLayer) layers.push(landLayer);
    layers.push(
      new deck.PathLayer({id:"edges", data: edgeData, getPath: x=>x.path,
        getColor: x=>[...x._color, x.type==="shipping_route"?170:120],
        getWidth: x=>x._width, widthUnits:"pixels", widthMinPixels:1.2,
        pickable:true, updateTriggers:{getColor:[d,tSec>0], getWidth:[d]}}),
      new deck.ScatterplotLayer({id:"dots", data: dots, getPosition: x=>x.position,
        getFillColor: x=>[...x.color, 235], getRadius: x=>x.size,
        radiusUnits:"pixels"}),
      new deck.ScatterplotLayer({id:"nodes", data: DATA.nodes,
        getPosition: x=>[x.lon,x.lat], getFillColor: x=>[...x.color, 220],
        getRadius: x=>x.radius, radiusUnits:"meters", stroked:true,
        getLineColor:[15,23,42,160], lineWidthMinPixels:1, pickable:true}),
    );

    if (DATA.corridor && DATA.severity > 0) {
      const pulse = 1 + 0.9*Math.abs(Math.sin(tSec*2.2));
      layers.push(new deck.ScatterplotLayer({id:"pulse", data:[DATA.corridor],
        getPosition: x=>[x.lon,x.lat], getFillColor:[0,0,0,0], stroked:true,
        getLineColor:[239,35,60, Math.round(220 - 150*Math.abs(Math.sin(tSec*2.2)))],
        lineWidthMinPixels:2.5, getRadius: 90000*pulse, radiusUnits:"meters",
        updateTriggers:{getRadius:[tSec], getLineColor:[tSec]}}));
      layers.push(new deck.ScatterplotLayer({id:"pulse-core", data:[DATA.corridor],
        getPosition: x=>[x.lon,x.lat], getFillColor:[239,35,60,230],
        getRadius: 42000, radiusUnits:"meters", pickable:true}));
    }
    if (DATA.event) {
      layers.push(new deck.ScatterplotLayer({id:"event", data:[DATA.event],
        getPosition: x=>[x.lon,x.lat], getFillColor:[15,23,42,240],
        stroked:true, getLineColor:[239,35,60,255], lineWidthMinPixels:3,
        getRadius: 60000, radiusUnits:"meters", pickable:true}));
    }
    return layers;
  }

  // Best-effort camera persistence: a Streamlit rerun fully remounts this
  // component, which used to always snap the view back to the default —
  // one of the most visible "everything reloads" symptoms. sessionStorage
  // survives a remount within the same browser tab, so panning/zooming
  // feels sticky across reruns instead of resetting every time. Wrapped in
  // try/catch: some iframe sandboxing blocks storage access outright, in
  // which case this just silently falls back to the old reset-every-time
  // behavior rather than throwing.
  const VS_KEY = "petrotwin_viewstate_v1";
  let savedViewState = null;
  try {
    const raw = sessionStorage.getItem(VS_KEY);
    if (raw) savedViewState = JSON.parse(raw);
  } catch (e) { /* storage unavailable — fall back to the default view */ }

  const deckgl = new deck.DeckGL({
    container: "map",
    initialViewState: savedViewState || {latitude: 15, longitude: 55, zoom: 2.3, pitch: 28},
    controller: true,
    onViewStateChange: ({viewState}) => {
      try {
        sessionStorage.setItem(VS_KEY, JSON.stringify({
          latitude: viewState.latitude, longitude: viewState.longitude,
          zoom: viewState.zoom, pitch: viewState.pitch, bearing: viewState.bearing || 0,
        }));
      } catch (e) { /* storage unavailable — camera just won't persist */ }
    },
    layers: buildLayers(performance.now()),
    getTooltip: ({object}) => object && {
      html: "<b>" + (object.name || object.id || "") + "</b>" +
            (object._flow != null ? "<br/>flow: " + Math.round(object._flow).toLocaleString() + " kbpd" : "") +
            (object.cap != null && object._flow == null ? "<br/>capacity: " + Math.round(object.cap).toLocaleString() + " kbpd" : ""),
      style: {backgroundColor: "#ffffff", color: "#0f172a", fontSize: "12px", borderRadius: "6px", border: "1px solid #cbd5e1", boxShadow: "0 2px 8px rgba(15,23,42,0.12)"}
    },
  });

  // --- timeline controls ---
  const scrub = document.getElementById("dayscrub");
  const label = document.getElementById("daylabel");
  const sprEl = document.getElementById("sprval");
  const shortEl = document.getElementById("shortval");
  const btn = document.getElementById("playbtn");
  if (TL.enabled) {
    document.getElementById("controls").style.display = "flex";
    scrub.max = nDays;
    function refreshHud() {
      label.textContent = "Day " + (dayPos < 0.05 ? "0 — normal" : dayPos.toFixed(1));
      sprEl.textContent = Math.round(interp(TL.spr, dayPos)).toLocaleString() + " kbpd";
      shortEl.textContent = Math.round(interp(TL.shortfall, dayPos)).toLocaleString() + " kbpd";
    }
    refreshHud();
    scrub.addEventListener("input", () => { playing = false; btn.innerHTML = "&#9654; Play disruption";
      dayPos = parseFloat(scrub.value); refreshHud(); });
    btn.addEventListener("click", () => {
      if (dayPos >= nDays - 0.01) dayPos = 0;
      playing = !playing;
      btn.innerHTML = playing ? "&#10074;&#10074; Pause" : "&#9654; Play disruption";
    });
    window._refreshHud = refreshHud;
  }

  let last = performance.now();
  function frame(now) {
    const dt = (now - last)/1000; last = now;
    if (playing && TL.enabled) {
      dayPos = Math.min(nDays, dayPos + dt * 1.25);   // ~0.8s per day
      scrub.value = dayPos;
      if (window._refreshHud) window._refreshHud();
      if (dayPos >= nDays) { playing = false; btn.innerHTML = "&#9654; Replay"; }
    }
    deckgl.setProps({layers: buildLayers(now)});
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
</script>
"""
