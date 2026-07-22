"""
Rebuilds data/network.json using authoritative PPAC figures extracted from the
user-provided source documents:
  - India's Oil & Gas Ready Reckoner for FY 2025-26 (PPAC, PDF)
  - Monthly Ready Reckoner / Snapshot of India Oil & Gas, June 2026 (PPAC, PDF)
  - RR_2024-25_H1_Final_WebUpload.xlsx (PPAC, Excel — Tables 4.1-4.3, 5.2, 8.24)
  - ICB Notification 30.06.2026 (PPAC — Indian Crude Basket pricing ratio)

Run: python3 build_network.py  (writes data/network.json)
"""
import json

BBL_PER_TONNE = 7.33  # PPAC's own conversion factor (Table 8.24 footnote)


def kbpd(mmtpa):
    return round(mmtpa * 1e6 * BBL_PER_TONNE / 365 / 1000, 1)


# ---------------------------------------------------------------------------
# Authoritative refinery capacities as of 01.04.2024 (Table 4.1, RR Excel /
# PDF). Jamnagar = RIL DTA (33) + SEZ (35.2) combined complex.
# ---------------------------------------------------------------------------
REFINERY_MMTPA = {
    "ref_jamnagar": ("Jamnagar Refinery (Reliance, SEZ+DTA)", 68.2, 21.1, "any (heavy-sour capable)", 22.34, 69.85),
    "ref_vadinar": ("Vadinar Refinery (Nayara Energy)", 20.0, 11.8, "medium-heavy sour capable", 22.47, 69.73),
    "ref_kochi": ("Kochi Refinery (BPCL)", 15.5, 10.8, "medium sour capable", 9.95, 76.26),
    "ref_mangalore": ("Mangalore Refinery (MRPL/ONGC)", 15.0, 10.6, "light-medium sweet", 12.87, 74.84),
    "ref_paradip": ("Paradip Refinery (IOCL)", 15.0, 12.2, "heavy-sour capable", 20.31, 86.61),
    "ref_panipat": ("Panipat Refinery (IOCL)", 15.0, 10.5, "medium sour capable", 29.39, 76.97),
    "ref_gujarat": ("Gujarat Refinery / Koyali (IOCL)", 13.7, 10.0, "medium sour capable", 22.15, 73.2),
    "ref_visakhapatnam": ("Visakhapatnam Refinery (HPCL)", 13.7, 7.8, "light-sweet preferred", 17.68, 83.22),
    "ref_mumbai_bpcl": ("Mumbai Refinery (BPCL)", 12.0, 5.6, "light-sweet preferred", 19.0, 72.85),
    "ref_bathinda": ("Guru Gobind Singh Refinery (HMEL, Bathinda)", 11.3, 12.6, "medium sour capable", 30.21, 74.95),
    "ref_chennai": ("Manali Refinery (CPCL, Chennai)", 10.5, 9.5, "medium sour capable", 13.17, 80.27),
    "ref_mumbai_hpcl": ("Mumbai Refinery (HPCL)", 9.5, 10.4, "light-medium sweet", 19.02, 72.83),
    "ref_mathura": ("Mathura Refinery (IOCL)", 8.0, 8.4, "medium sour capable", 27.49, 77.67),
    "ref_haldia": ("Haldia Refinery (IOCL)", 8.0, 10.4, "medium sour capable", 22.03, 88.12),
    "ref_bina": ("Bina Refinery (BORL/BPCL)", 7.8, 11.58, "medium-heavy sour capable", 24.18, 78.24),
    "ref_barauni": ("Barauni Refinery (IOCL)", 6.0, 7.8, "medium sour capable", 25.47, 85.97),
}

# National context (Table 4.1/4.3, RR Excel; RR FY25-26 PDF highlights)
ALL_INDIA_INSTALLED_MMTPA = 256.816  # 01.04.2024, Table 4.1
NATIONAL_NAMEPLATE_MMTPA_FY2526 = 258.1  # RR FY25-26 chapter highlights, as of Apr 2025
IMPORTED_CRUDE_SHARE_FY2425 = 0.8974  # Table 4.3, Apr-Sep 2024-25 (P)
CRUDE_IMPORTS_MMT_FY2526 = 245.8  # Snapshot Jun'26, Table 6
CRUDE_IMPORTS_MMT_FY2425 = 243.2
INDIGENOUS_CRUDE_MMT_FY2526 = 28.0  # Snapshot Jun'26, Table 2
INDIA_BASKET_PRICE_USD_BBL_FY2526 = 70.99  # Snapshot Jun'26, Table 25
INDIA_BASKET_PRICE_USD_BBL_JUN26 = 83.22
ICB_RATIO_JUL2026 = {"Dated Brent": 79.40, "Dubai/Oman": 20.60}  # ICB Notification 30.06.2026

TOTAL_IMPORT_KBPD = kbpd(CRUDE_IMPORTS_MMT_FY2526)  # ~4936 kbpd
TOTAL_DOMESTIC_KBPD = kbpd(INDIGENOUS_CRUDE_MMT_FY2526)  # ~562 kbpd

# ---------------------------------------------------------------------------
# Supplier country shares — EXACT, from DGCI&S's own country-wise import
# register (dgcis_freeuser_1784552528488_1.xls, "India's Import By
# PRINCIPAL COMMODITY GROUP From Jan-2025 To Dec-2025", PETROLEUN: CRUDE
# rows, pulled via the DGCI&S Foreign Trade Data Dissemination Portal).
# 34 countries reported. Percentages below are import-quantity shares
# (tonnes) for calendar Jan-Dec 2025.
# Cross-checked: this file's implied price ($105.09bn / 201.4 Mt @ 7.33
# bbl/t = $71.18/bbl) lines up with PPAC's own $70.99/bbl FY2025-26
# average (different but overlapping period), and its top-5 share
# (82.76%) lines up with the DGCI&S report's 82.57% for FY2024-25 —
# two independent consistency checks that this file is genuine.
#
# Independent-review request: the remaining 26 countries below the top-8
# threshold used to be pooled into a single "Other" node — accurate in
# total volume but made the network look emptier than it really is, and
# genuinely obscured that "Other" mixes Gulf, Mediterranean, African,
# American, and Southeast Asian suppliers with very different chokepoint
# exposure (flagged as a limitation — see KNOWN_LIMITATIONS.md item 9,
# now resolved). All 25 of them with nonzero 2025 volume (Hungary
# reported exactly 0 tonnes and is omitted) are now modeled individually,
# straight from the same source file, so the map shows the real country
# count instead of one aggregate blob. Coordinates below are each
# country's real principal crude export terminal (Ras Laffan for Qatar,
# Ceyhan for Turkey, etc.) — see SUPPLIER_META comments and DATA_SOURCES.md
# for the corridor/exposure reasoning per country.
# ---------------------------------------------------------------------------
SUPPLIER_SHARE = {
    "sup_russia": 0.3266,
    "sup_iraq": 0.1875,
    "sup_saudi": 0.1323,
    "sup_uae": 0.1075,
    "sup_usa": 0.0737,
    "sup_kuwait": 0.0312,
    "sup_nigeria": 0.0294,
    "sup_angola": 0.0210,
    # The 25 formerly-pooled "Other" countries, each individually below the
    # top-8's >2% threshold but real, named, and separately routed. Exact
    # DGCI&S PETROLEUM:CRUDE quantity shares, calendar 2025.
    "sup_egypt": 0.0134,
    "sup_colombia": 0.0109,
    "sup_brazil": 0.0105,
    "sup_qatar": 0.0105,
    "sup_oman": 0.0090,
    "sup_libya": 0.0041,
    "sup_mexico": 0.0037,
    "sup_malaysia": 0.0034,
    "sup_venezuela": 0.0032,
    "sup_congo_p": 0.0031,
    "sup_turkey": 0.0029,
    "sup_gabon": 0.0021,
    "sup_korea": 0.0020,
    "sup_ghana": 0.0019,
    "sup_brunei": 0.0018,
    "sup_uruguay": 0.0014,
    "sup_algeria": 0.0013,
    "sup_singapore": 0.0011,
    "sup_congo_d": 0.0010,
    "sup_argentina": 0.0009,
    "sup_panama": 0.0007,
    "sup_togo": 0.0007,
    "sup_canada": 0.0005,
    "sup_south_sudan": 0.0004,
    "sup_cameroon": 0.0002,
}

SUPPLIER_META = {
    "sup_russia": ("Russia (Baltic/Black Sea export)", 60.3, 28.7, "medium-sour"),
    "sup_iraq": ("Iraq (Basra terminal)", 30.5, 47.8, "heavy-sour"),
    "sup_saudi": ("Saudi Arabia (Ras Tanura)", 26.6, 50.2, "light-medium-sour"),
    "sup_uae": ("UAE (Fujairah)", 25.1, 56.3, "light-sweet"),
    "sup_usa": ("USA (Gulf Coast — Houston/Corpus Christi)", 29.7, -95.0, "light-sweet"),
    "sup_kuwait": ("Kuwait (Mina Al-Ahmadi)", 29.1, 48.1, "medium-sour"),
    "sup_nigeria": ("Nigeria (Bonny/Escravos)", 4.4, 7.1, "light-sweet"),
    "sup_angola": ("Angola (Luanda/Cabinda)", -8.8, 13.2, "light-medium-sweet"),
    # Each coordinate below is that country's real principal crude export
    # terminal, not a capital city or a rough regional guess — same
    # standard as the top-8 above. "Grade" is a documented best-effort
    # generalization (not a PPAC figure) where no obvious single grade
    # applies. A few of these (Panama, Singapore, Uruguay) are DGCI&S's
    # recorded "country of consignment" rather than a producing country —
    # very likely transshipment/blending points, not wells — disclosed as
    # such rather than silently treated as upstream production.
    "sup_egypt": ("Egypt (Sidi Kerir, Mediterranean)", 31.15, 29.65, "light-sweet"),
    "sup_colombia": ("Colombia (Covenas)", 9.4, -75.7, "light-sweet"),
    "sup_brazil": ("Brazil (Campos Basin/Rio de Janeiro)", -22.9, -43.2, "light-sweet"),
    "sup_qatar": ("Qatar (Ras Laffan)", 25.9, 51.6, "light-sweet"),
    "sup_oman": ("Oman (Mina Al Fahal)", 23.6, 58.5, "medium-sour"),
    "sup_libya": ("Libya (Es Sider)", 30.6, 18.4, "light-sweet"),
    "sup_mexico": ("Mexico (Dos Bocas/Cayo Arcas)", 18.7, -92.2, "heavy-sour"),
    "sup_malaysia": ("Malaysia (Kerteh)", 4.5, 103.4, "light-sweet"),
    "sup_venezuela": ("Venezuela (Jose terminal)", 10.1, -64.7, "heavy-sour"),
    "sup_congo_p": ("Congo-Brazzaville (Pointe-Noire)", -4.8, 11.85, "light-sweet"),
    "sup_turkey": ("Turkey (Ceyhan)", 36.9, 35.9, "medium-sour"),
    "sup_gabon": ("Gabon (Port-Gentil)", -0.7, 8.75, "light-sweet"),
    "sup_korea": ("South Korea (Ulsan)", 35.5, 129.4, "mixed"),
    "sup_ghana": ("Ghana (Takoradi)", 4.9, -1.75, "light-sweet"),
    "sup_brunei": ("Brunei (Muara)", 5.0, 115.1, "light-sweet"),
    "sup_uruguay": ("Uruguay (Montevideo, transshipment)", -34.9, -56.2, "mixed"),
    "sup_algeria": ("Algeria (Arzew)", 36.75, 3.9, "light-sweet"),
    "sup_singapore": ("Singapore (trading hub)", 1.29, 103.85, "mixed"),
    "sup_congo_d": ("DR Congo (Muanda)", -5.9, 12.35, "light-sweet"),
    "sup_argentina": ("Argentina (Bahia Blanca)", -38.7, -62.3, "light-medium-sweet"),
    "sup_panama": ("Panama (Pacific transshipment terminal)", 9.0, -79.5, "mixed"),
    "sup_togo": ("Togo (Lome)", 6.1, 1.2, "mixed"),
    # Atlantic coast (Saint John, NB — Irving Oil terminal), not the
    # Pacific coast: a Vancouver-based Pacific route would cross the
    # antimeridian, which searoute represents as a continuously
    # decreasing longitude (e.g. -279 instead of 81) rather than wrapping
    # back into [-180, 180] — deck.gl handles that fine for the path
    # itself, but it's an unnecessary edge case to introduce for one
    # 0.05%-share country when a real Atlantic terminal avoids it outright.
    "sup_canada": ("Canada (Saint John, NB — Atlantic export)", 45.25, -66.05, "heavy"),
    "sup_south_sudan": ("South Sudan (via Port Sudan)", 19.6, 37.2, "heavy"),
    "sup_cameroon": ("Cameroon (Kribi)", 2.95, 9.9, "light-sweet"),
}

# Domestic (indigenous) crude — regional split based on PPAC's own
# production-by-regime breakdown (Nomination ~77% dominated by ONGC
# offshore Mumbai + onshore Gujarat/Assam; DSF/PRE-NELP/NELP/OALP the rest).
# Snapshot Jun'26 Table 3 gives regime shares nationally; we further split
# "Nomination" geographically using known field geography (Mumbai
# offshore >> Gujarat onshore, Assam, Rajasthan) since PPAC doesn't publish
# a state-wise split at this granularity in the provided documents.
DOMESTIC_SHARE = {
    "sup_domestic_offshore_mumbai": 0.55,
    "sup_domestic_rajasthan": 0.25,
    "sup_domestic_assam": 0.12,
    "sup_domestic_gujarat": 0.08,
}
DOMESTIC_META = {
    "sup_domestic_offshore_mumbai": ("Mumbai High offshore fields (ONGC)", 19.2, 71.6),
    "sup_domestic_rajasthan": ("Barmer/Mangala fields, Rajasthan (Cairn/Vedanta)", 25.75, 71.05),
    "sup_domestic_assam": ("Assam onshore fields (OIL/ONGC)", 27.3, 95.3),
    "sup_domestic_gujarat": ("Gujarat onshore fields (ONGC — Ankleshwar/Mehsana/Gandhar)", 22.5, 72.6),
}

PORTS = {
    "port_sikka": ("Sikka / Jamnagar", 22.4, 69.83),
    "port_vadinar": ("Vadinar", 22.47, 69.73),
    "port_mundra": ("Mundra", 22.84, 69.70),
    "port_kandla": ("Kandla", 23.0, 70.2),
    "port_mumbai": ("Mumbai", 18.92, 72.85),
    "port_new_mangalore": ("New Mangalore", 12.9, 74.8),
    "port_kochi": ("Kochi", 9.95, 76.26),
    "port_paradip": ("Paradip", 20.31, 86.61),
    "port_chennai": ("Chennai", 13.1, 80.3),
    "port_visakhapatnam": ("Visakhapatnam", 17.7, 83.3),
    "port_haldia": ("Haldia", 22.0, 88.1),
}

CORRIDORS = {
    "corridor_hormuz": ("Strait of Hormuz", 26.6, 56.25, True, 30),
    "corridor_redsea_suez": ("Bab-el-Mandeb / Red Sea–Suez", 12.6, 43.4, True, 12),
    "corridor_cape": ("Cape of Good Hope (bypass route)", -34.3, 18.5, False, 20),
    "corridor_malacca": ("Strait of Malacca", 2.8, 101.4, True, 3),
}

SPR = {
    "spr_vizag": ("Visakhapatnam SPR cavern", 17.72, 83.28, 1.33, 140, "ref_visakhapatnam"),
    "spr_mangalore": ("Mangalore SPR cavern", 12.92, 74.82, 1.5, 155, "ref_mangalore"),
    "spr_padur": ("Padur SPR cavern (Udupi)", 13.35, 74.75, 2.5, 180, "ref_mangalore"),
}

nodes = []
edges = []

for sid, (name, mmtpa, nelson, grade_pref, lat, lon) in REFINERY_MMTPA.items():
    nodes.append({
        "id": sid, "type": "refinery", "name": name, "lat": lat, "lon": lon,
        "capacity_kbpd": kbpd(mmtpa), "installed_capacity_mmtpa": mmtpa,
        "nelson_complexity": nelson, "grade_preference": grade_pref,
    })

for sid, share in SUPPLIER_SHARE.items():
    name, lat, lon, grade = SUPPLIER_META[sid]
    flow = round(TOTAL_IMPORT_KBPD * share, 1)
    nodes.append({
        "id": sid, "type": "supplier", "name": name, "lat": lat, "lon": lon,
        "share_pct": round(share * 100, 1), "flow_kbpd": flow, "grade": grade,
    })

for sid, share in DOMESTIC_SHARE.items():
    name, lat, lon = DOMESTIC_META[sid]
    flow = round(TOTAL_DOMESTIC_KBPD * share, 1)
    nodes.append({
        "id": sid, "type": "supplier", "subtype": "domestic", "name": name,
        "lat": lat, "lon": lon, "share_pct": round(share * 100, 1),
        "flow_kbpd": flow, "grade": "domestic-mixed",
    })

for cid, (name, lat, lon, chokepoint, share) in CORRIDORS.items():
    nodes.append({
        "id": cid, "type": "corridor", "name": name, "lat": lat, "lon": lon,
        "chokepoint": chokepoint, "baseline_share_of_imports_pct": share,
    })

port_capacity_kbpd = {
    "port_sikka": 1950, "port_vadinar": 750, "port_mundra": 420, "port_kandla": 300,
    "port_mumbai": 750, "port_new_mangalore": 450, "port_kochi": 350, "port_paradip": 750,
    "port_chennai": 250, "port_visakhapatnam": 300, "port_haldia": 250,
}
for pid, (name, lat, lon) in PORTS.items():
    nodes.append({
        "id": pid, "type": "port", "name": name, "lat": lat, "lon": lon,
        "capacity_kbpd": port_capacity_kbpd[pid],
    })

for sid, (name, lat, lon, inv, draw, link) in SPR.items():
    nodes.append({
        "id": sid, "type": "spr", "name": name, "lat": lat, "lon": lon,
        "inventory_mmt": inv, "max_draw_rate_kbpd": draw,
    })

# ---------------------------------------------------------------------------
# Shipping-route edges: supplier -> port (import flows)
# ---------------------------------------------------------------------------
shipping_edges = [
    dict(id="e_russia_vadinar", source="sup_russia", target="port_vadinar", capacity_kbpd=950,
         transit_days=22, via_corridor="corridor_redsea_suez", chokepoint_exposure=0.55,
         alt_corridor="corridor_cape", alt_transit_days=28, grade="medium-sour"),
    dict(id="e_russia_sikka", source="sup_russia", target="port_sikka", capacity_kbpd=780,
         transit_days=22, via_corridor="corridor_redsea_suez", chokepoint_exposure=0.55,
         alt_corridor="corridor_cape", alt_transit_days=28, grade="medium-sour"),
    dict(id="e_iraq_sikka", source="sup_iraq", target="port_sikka", capacity_kbpd=520,
         transit_days=9, via_corridor="corridor_hormuz", chokepoint_exposure=1.0,
         alt_corridor=None, alt_transit_days=None, grade="heavy-sour"),
    dict(id="e_iraq_paradip", source="sup_iraq", target="port_paradip", capacity_kbpd=480,
         transit_days=11, via_corridor="corridor_hormuz", chokepoint_exposure=1.0,
         alt_corridor=None, alt_transit_days=None, grade="heavy-sour"),
    dict(id="e_saudi_sikka", source="sup_saudi", target="port_sikka", capacity_kbpd=280,
         transit_days=9, via_corridor="corridor_hormuz", chokepoint_exposure=1.0,
         alt_corridor=None, alt_transit_days=None, grade="light-medium-sour"),
    dict(id="e_saudi_mundra", source="sup_saudi", target="port_mundra", capacity_kbpd=220,
         transit_days=8, via_corridor="corridor_hormuz", chokepoint_exposure=1.0,
         alt_corridor=None, alt_transit_days=None, grade="light-medium-sour"),
    dict(id="e_uae_sikka", source="sup_uae", target="port_sikka", capacity_kbpd=400,
         transit_days=5, via_corridor="corridor_hormuz", chokepoint_exposure=0.3,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    dict(id="e_usa_mumbai", source="sup_usa", target="port_mumbai", capacity_kbpd=150,
         transit_days=23, via_corridor=None, chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    dict(id="e_usa_sikka", source="sup_usa", target="port_sikka", capacity_kbpd=110,
         transit_days=24, via_corridor=None, chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    dict(id="e_kuwait_sikka", source="sup_kuwait", target="port_sikka", capacity_kbpd=220,
         transit_days=10, via_corridor="corridor_hormuz", chokepoint_exposure=1.0,
         alt_corridor=None, alt_transit_days=None, grade="medium-sour"),
    dict(id="e_nigeria_kochi", source="sup_nigeria", target="port_kochi", capacity_kbpd=140,
         transit_days=18, via_corridor="corridor_cape", chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    dict(id="e_nigeria_new_mangalore", source="sup_nigeria", target="port_new_mangalore", capacity_kbpd=90,
         transit_days=19, via_corridor="corridor_cape", chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    dict(id="e_angola_kochi", source="sup_angola", target="port_kochi", capacity_kbpd=140,
         transit_days=20, via_corridor="corridor_cape", chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="light-medium-sweet"),
    # --- The 25 formerly-pooled "Other" countries, each given one edge to a
    # single sensible Indian port based on real geography (Gulf/Med/Red-Sea
    # countries -> a west-coast port via their real corridor; Atlantic/
    # Americas countries -> via_corridor=None same as USA; Southeast Asia ->
    # Malacca). Capacity is sized at roughly 1.6x each country's actual
    # 2025 import flow (same generous-margin convention as every other
    # supplier edge here), floored at 10 kbpd so the smallest countries
    # still get a real, visible, constraint-satisfying route rather than a
    # degenerate near-zero one.
    dict(id="e_egypt_sikka", source="sup_egypt", target="port_sikka", capacity_kbpd=106,
         transit_days=16, via_corridor="corridor_redsea_suez", chokepoint_exposure=0.6,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    dict(id="e_colombia_mumbai", source="sup_colombia", target="port_mumbai", capacity_kbpd=86,
         transit_days=26, via_corridor=None, chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    dict(id="e_brazil_kochi", source="sup_brazil", target="port_kochi", capacity_kbpd=83,
         transit_days=21, via_corridor="corridor_cape", chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    dict(id="e_qatar_sikka", source="sup_qatar", target="port_sikka", capacity_kbpd=83,
         transit_days=9, via_corridor="corridor_hormuz", chokepoint_exposure=1.0,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    dict(id="e_oman_sikka", source="sup_oman", target="port_sikka", capacity_kbpd=71,
         transit_days=7, via_corridor="corridor_hormuz", chokepoint_exposure=0.2,
         alt_corridor=None, alt_transit_days=None, grade="medium-sour"),
    dict(id="e_libya_sikka", source="sup_libya", target="port_sikka", capacity_kbpd=32,
         transit_days=17, via_corridor="corridor_redsea_suez", chokepoint_exposure=0.6,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    dict(id="e_mexico_mumbai", source="sup_mexico", target="port_mumbai", capacity_kbpd=29,
         transit_days=26, via_corridor=None, chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="heavy-sour"),
    dict(id="e_malaysia_chennai", source="sup_malaysia", target="port_chennai", capacity_kbpd=27,
         transit_days=9, via_corridor="corridor_malacca", chokepoint_exposure=0.4,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    dict(id="e_venezuela_mumbai", source="sup_venezuela", target="port_mumbai", capacity_kbpd=25,
         transit_days=27, via_corridor=None, chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="heavy-sour"),
    dict(id="e_congo_p_kochi", source="sup_congo_p", target="port_kochi", capacity_kbpd=24,
         transit_days=19, via_corridor="corridor_cape", chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    # Turkey/Algeria/South Sudan deliberately land at Kandla/New Mangalore/
    # Visakhapatnam rather than joining every other Gulf/Med supplier at
    # Sikka — preserves the multi-supplier-per-port diversification the
    # old pooled "Other" edges to these three ports used to provide (see
    # KNOWN_LIMITATIONS.md item 9), now via real, individually-named
    # countries instead of an aggregate.
    dict(id="e_turkey_kandla", source="sup_turkey", target="port_kandla", capacity_kbpd=23,
         transit_days=16, via_corridor="corridor_redsea_suez", chokepoint_exposure=0.6,
         alt_corridor=None, alt_transit_days=None, grade="medium-sour"),
    dict(id="e_gabon_kochi", source="sup_gabon", target="port_kochi", capacity_kbpd=16,
         transit_days=19, via_corridor="corridor_cape", chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    # Lands at Haldia rather than Chennai — port_haldia otherwise loses its
    # only shipping-route inflow now that the pooled "Other" node (which
    # used to feed it) is gone, which left the port_throughput constraint
    # for Haldia summing over zero edges and crashing the solver (caught
    # by test_optimizer.py's full-suite run, not a hypothetical).
    dict(id="e_korea_haldia", source="sup_korea", target="port_haldia", capacity_kbpd=15,
         transit_days=15, via_corridor="corridor_malacca", chokepoint_exposure=0.4,
         alt_corridor=None, alt_transit_days=None, grade="mixed"),
    dict(id="e_ghana_kochi", source="sup_ghana", target="port_kochi", capacity_kbpd=15,
         transit_days=19, via_corridor="corridor_cape", chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    dict(id="e_brunei_chennai", source="sup_brunei", target="port_chennai", capacity_kbpd=15,
         transit_days=10, via_corridor="corridor_malacca", chokepoint_exposure=0.4,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    dict(id="e_uruguay_mumbai", source="sup_uruguay", target="port_mumbai", capacity_kbpd=11,
         transit_days=28, via_corridor=None, chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="mixed"),
    dict(id="e_algeria_new_mangalore", source="sup_algeria", target="port_new_mangalore", capacity_kbpd=10,
         transit_days=17, via_corridor="corridor_redsea_suez", chokepoint_exposure=0.6,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    dict(id="e_singapore_chennai", source="sup_singapore", target="port_chennai", capacity_kbpd=10,
         transit_days=8, via_corridor="corridor_malacca", chokepoint_exposure=0.4,
         alt_corridor=None, alt_transit_days=None, grade="mixed"),
    dict(id="e_congo_d_kochi", source="sup_congo_d", target="port_kochi", capacity_kbpd=10,
         transit_days=19, via_corridor="corridor_cape", chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    dict(id="e_argentina_kochi", source="sup_argentina", target="port_kochi", capacity_kbpd=10,
         transit_days=24, via_corridor="corridor_cape", chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="light-medium-sweet"),
    dict(id="e_panama_mumbai", source="sup_panama", target="port_mumbai", capacity_kbpd=10,
         transit_days=26, via_corridor=None, chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="mixed"),
    dict(id="e_togo_kochi", source="sup_togo", target="port_kochi", capacity_kbpd=10,
         transit_days=19, via_corridor="corridor_cape", chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="mixed"),
    dict(id="e_canada_mumbai", source="sup_canada", target="port_mumbai", capacity_kbpd=10,
         transit_days=24, via_corridor=None, chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="heavy"),
    dict(id="e_south_sudan_visakhapatnam", source="sup_south_sudan", target="port_visakhapatnam", capacity_kbpd=10,
         transit_days=18, via_corridor="corridor_redsea_suez", chokepoint_exposure=0.6,
         alt_corridor=None, alt_transit_days=None, grade="heavy"),
    dict(id="e_cameroon_kochi", source="sup_cameroon", target="port_kochi", capacity_kbpd=10,
         transit_days=19, via_corridor="corridor_cape", chokepoint_exposure=0.0,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
    # --- Added to fix a connectivity gap: Kandla, Mundra and New Mangalore
    # each had only 0-1 supplier routes feeding them, which starved their
    # downstream refineries (Gujarat/Koyali, Panipat, Bathinda, Mangalore)
    # even at baseline with zero disruption. Real ports of this size
    # receive multiple grades from multiple sources; these routes restore
    # that diversification without changing any supplier's total
    # flow_kbpd (the optimizer still caps each supplier's combined outflow
    # across all of its edges at its real production/export volume).
    dict(id="e_iraq_kandla", source="sup_iraq", target="port_kandla", capacity_kbpd=260,
         transit_days=10, via_corridor="corridor_hormuz", chokepoint_exposure=1.0,
         alt_corridor=None, alt_transit_days=None, grade="heavy-sour"),
    dict(id="e_saudi_new_mangalore", source="sup_saudi", target="port_new_mangalore", capacity_kbpd=220,
         transit_days=10, via_corridor="corridor_hormuz", chokepoint_exposure=1.0,
         alt_corridor=None, alt_transit_days=None, grade="light-medium-sour"),
    dict(id="e_uae_mundra", source="sup_uae", target="port_mundra", capacity_kbpd=200,
         transit_days=6, via_corridor="corridor_hormuz", chokepoint_exposure=0.3,
         alt_corridor=None, alt_transit_days=None, grade="light-sweet"),
]
for e in shipping_edges:
    e["type"] = "shipping_route"
    edges.append(e)

# ---------------------------------------------------------------------------
# Port -> refinery edges. Where a named PPAC pipeline exists (Table 5.2),
# use its real capacity and note the pipeline name + length.
# ---------------------------------------------------------------------------
port_to_refinery = [
    dict(id="e_sikka_jamnagar", source="port_sikka", target="ref_jamnagar", capacity_kbpd=kbpd(68.2)),
    dict(id="e_sikka_mathura", source="port_sikka", target="ref_mathura", capacity_kbpd=kbpd(25.0),
         pipeline_name="Salaya-Mathura Pipeline (SMPL)", operator="IOCL", length_km=2646),
    dict(id="e_vadinar_vadinar_ref", source="port_vadinar", target="ref_vadinar", capacity_kbpd=kbpd(20.0)),
    dict(id="e_vadinar_bina", source="port_vadinar", target="ref_bina", capacity_kbpd=kbpd(7.8),
         pipeline_name="Vadinar-Bina Pipeline", operator="BPCL", length_km=937),
    dict(id="e_mundra_panipat", source="port_mundra", target="ref_panipat", capacity_kbpd=kbpd(8.4),
         pipeline_name="Mundra-Panipat Pipeline", operator="IOCL", length_km=1194),
    dict(id="e_mundra_bathinda", source="port_mundra", target="ref_bathinda", capacity_kbpd=kbpd(11.25),
         pipeline_name="Mundra-Bathinda Pipeline (HMPL)", operator="HMPL", length_km=1017),
    dict(id="e_kandla_gujarat", source="port_kandla", target="ref_gujarat", capacity_kbpd=kbpd(13.7)),
    dict(id="e_mumbai_bpcl_ref", source="port_mumbai", target="ref_mumbai_bpcl", capacity_kbpd=kbpd(12.0)),
    dict(id="e_mumbai_hpcl_ref", source="port_mumbai", target="ref_mumbai_hpcl", capacity_kbpd=kbpd(9.5)),
    dict(id="e_new_mangalore_ref", source="port_new_mangalore", target="ref_mangalore", capacity_kbpd=kbpd(15.0)),
    dict(id="e_kochi_ref", source="port_kochi", target="ref_kochi", capacity_kbpd=kbpd(15.5)),
    dict(id="e_paradip_ref", source="port_paradip", target="ref_paradip", capacity_kbpd=kbpd(15.0)),
    dict(id="e_paradip_haldia_ref", source="port_paradip", target="ref_haldia", capacity_kbpd=kbpd(20.4),
         pipeline_name="Paradip-Haldia-Barauni Pipeline (PHBPL)", operator="IOCL", length_km=1873,
         shared_capacity_group="phbpl", shared_capacity_group_cap=kbpd(20.4)),
    dict(id="e_paradip_barauni_ref", source="port_paradip", target="ref_barauni", capacity_kbpd=kbpd(20.4),
         pipeline_name="Paradip-Haldia-Barauni Pipeline (PHBPL) — continues past Haldia", operator="IOCL",
         length_km=1873, note="Shares physical pipeline capacity with e_paradip_haldia_ref; not additive.",
         shared_capacity_group="phbpl", shared_capacity_group_cap=kbpd(20.4)),
    dict(id="e_chennai_ref", source="port_chennai", target="ref_chennai", capacity_kbpd=kbpd(10.5)),
    dict(id="e_visakhapatnam_ref", source="port_visakhapatnam", target="ref_visakhapatnam", capacity_kbpd=kbpd(13.7)),
    # Independent audit finding M2: e_other_haldia (below) ships crude INTO
    # port_haldia, but port_haldia had zero outgoing edges — Haldia refinery
    # is actually fed via the PHBPL pipeline from Paradip (e_paradip_haldia_ref
    # above), not from its own port. That made the port_haldia route on the
    # map a dead end the optimizer could never use (contract=flow=0 always).
    # This edge gives port_haldia a real outlet.
    dict(id="e_haldia_port_to_ref", source="port_haldia", target="ref_haldia", capacity_kbpd=160.0),
]
for e in port_to_refinery:
    e["type"] = "port_to_refinery"
    edges.append(e)

# ---------------------------------------------------------------------------
# Domestic (indigenous) crude edges — pipelines from Table 5.2
# ---------------------------------------------------------------------------
domestic_edges = [
    dict(id="e_domestic_offshore_mumbai_port", source="sup_domestic_offshore_mumbai", target="port_mumbai",
         capacity_kbpd=kbpd(33.5), transit_days=1,
         pipeline_name="Mumbai High-Uran-Trunk + Heera-Uran-Trunk + Bombay-Uran Trunk (ONGC offshore)"),
    dict(id="e_domestic_rajasthan_vadinar", source="sup_domestic_rajasthan", target="port_vadinar",
         capacity_kbpd=kbpd(8.71), transit_days=0,
         pipeline_name="Mangla-Bhogat Pipeline + Bhogat Marine", operator="Cairn/Vedanta", length_km=688),
    dict(id="e_domestic_assam_barauni", source="sup_domestic_assam", target="ref_barauni",
         capacity_kbpd=kbpd(8.95), transit_days=0,
         pipeline_name="Duliajan-Digboi-Bongaigaon-Barauni Pipeline", operator="OIL", length_km=1195.4),
    dict(id="e_domestic_gujarat_koyali", source="sup_domestic_gujarat", target="ref_gujarat",
         capacity_kbpd=kbpd(7.665), transit_days=0,
         pipeline_name="Mehsana-Nawagam + Nawagam-Koyali trunk lines", operator="ONGC"),
]
for e in domestic_edges:
    e["type"] = "domestic_pipeline"
    edges.append(e)

# ---------------------------------------------------------------------------
# SPR links
# ---------------------------------------------------------------------------
for sid, (name, lat, lon, inv, draw, link) in SPR.items():
    edges.append({
        "id": f"e_{sid}_link", "source": sid, "target": link, "type": "spr_link",
        "drawdown_capacity_kbpd": draw,
    })

network = {
    "meta": {
        "description": "India crude import + indigenous-production Supply Chain Knowledge Graph — typed nodes (supplier, corridor, port, refinery, spr) and typed edges (shipping_route, port_to_refinery, domestic_pipeline, spr_link). Built for ET AI Hackathon 2026 PS2 digital twin.",
        "units": {
            "flow_capacity": "thousand barrels per day (kbpd)",
            "spr_inventory": "million metric tonnes (MMT)",
            "transit_time": "days",
        },
        "verified_from_provided_documents": {
            "all_india_installed_refining_capacity_mmtpa_01_04_2024": ALL_INDIA_INSTALLED_MMTPA,
            "national_nameplate_capacity_mmtpa_fy2025_26_apr2025": NATIONAL_NAMEPLATE_MMTPA_FY2526,
            "operational_refineries_count_fy2025_26": 22,
            "private_sector_share_of_capacity_pct": 34.3,
            "crude_imports_mmt_fy2024_25": CRUDE_IMPORTS_MMT_FY2425,
            "crude_imports_mmt_fy2025_26": CRUDE_IMPORTS_MMT_FY2526,
            "crude_imports_kbpd_fy2025_26": TOTAL_IMPORT_KBPD,
            "indigenous_crude_mmt_fy2025_26": INDIGENOUS_CRUDE_MMT_FY2526,
            "indigenous_crude_kbpd_fy2025_26": TOTAL_DOMESTIC_KBPD,
            "imported_crude_share_of_processing_fy2024_25": IMPORTED_CRUDE_SHARE_FY2425,
            "india_basket_crude_price_usd_bbl_fy2025_26_avg": INDIA_BASKET_PRICE_USD_BBL_FY2526,
            "india_basket_crude_price_usd_bbl_jun_2026": INDIA_BASKET_PRICE_USD_BBL_JUN26,
            "icb_pricing_ratio_jul_2026": ICB_RATIO_JUL2026,
            "country_wise_import_qty_tonnes_cy2025_dgcis": 201405614,
            "country_wise_import_value_usd_cy2025_dgcis": 105088359111,
            "implied_price_usd_bbl_cy2025_dgcis": 71.18,
            "top5_supplier_combined_share_pct_cy2025_dgcis": 82.76,
            "top5_supplier_combined_share_pct_fy2024_25_dgcis_report": 82.57,
            "top5_supplier_combined_share_pct_fy2022_23_dgcis_report": 75.23,
            "national_crude_pipeline_network_km_31_03_2026": 10443,
            "national_crude_pipeline_capacity_mmtpa_31_03_2026": 153.1,
            "national_crude_pipeline_utilisation_pct_fy2025_26": 66.7,
            "bbl_per_tonne_conversion_factor": BBL_PER_TONNE,
        },
        "assumptions": [
            "Refinery capacities are the official installed capacities as of 01.04.2024 (PPAC Ready Reckoner Table 4.1), converted to kbpd using PPAC's own 1 MT = 7.33 bbl factor (Table 8.24 footnote). Jamnagar is modeled as the combined RIL DTA (33 MMTPA) + SEZ (35.2 MMTPA) complex.",
            "16 of India's 22-23 operational refineries are modeled (those in Table 4.1 individually broken out), covering 5,004.5 of 5,157.4 kbpd of all-India installed capacity as of 01.04.2024 — ~97% of national capacity. Omitted: Guwahati, Digboi, Bongaigaon, Numaligarh, Tatipaka (small/Northeast, individually <1.5% of capacity each).",
            "Total import volume (245.8 MMT, FY2025-26) and indigenous production (28.0 MMT, FY2025-26) are PPAC-verified (Snapshot of India Oil & Gas, June 2026). Supplier-country shares are now EXACT, from DGCI&S's own country-wise crude import register for calendar Jan-Dec 2025 (dgcis_freeuser_1784552528488_1.xls, pulled by the user via the DGCI&S Foreign Trade Data Dissemination Portal) — 34 reporting countries; the top 8 (each >2% of import quantity: Russia, Iraq, Saudi Arabia, UAE, USA, Kuwait, Nigeria, Angola) are modeled individually and the remaining 26 are pooled into 'Other'. These calendar-2025 percentages are applied to the PPAC-verified FY2025-26 volume total — a deliberate choice to combine the most granular available country split with the most authoritative available total, even though the two periods (calendar vs. fiscal year) don't perfectly overlap. Two independent cross-checks support treating this file as reliable: its implied average price ($71.18/bbl) is within 30 cents of PPAC's own $70.99/bbl FY2025-26 average, and its top-5 combined share (82.76%) is within 0.2 points of the DGCI&S report's own 82.57% figure for FY2024-25.",
            "Indigenous crude is split across 4 representative production regions (Mumbai offshore, Rajasthan, Assam, Gujarat onshore) using known field geography; PPAC's regime-wise split (Nomination/DSF/Pre-NELP/NELP/OALP, Snapshot Table 3) gives the national total but not this geographic breakdown, so the regional percentages themselves are an approximation layered on a verified total.",
            "Named pipeline capacities and lengths (Salaya-Mathura, Paradip-Haldia-Barauni, Mundra-Panipat, Mundra-Bathinda, Vadinar-Bina, Mangla-Bhogat, Duliajan-Digboi-Bongaigaon-Barauni) are taken directly from PPAC Table 5.2 (as of 01.10.2024) — these replace earlier invented port-to-refinery capacities and are now real, citable infrastructure.",
            "chokepoint_exposure on each shipping_route edge = fraction of that route's volume that physically transits the named corridor (not binary) — e.g. UAE's Fujairah terminal sits outside the Strait of Hormuz, so its exposure is set well below 1.0 even though most UAE production originates inside the Gulf. This remains a modeling judgment call, not a PPAC figure.",
            "AIS/tanker positions are NOT real telemetry — this is a topology model over public port/route/capacity/pipeline data, not live ship tracking.",
            "SPR inventory levels (Vizag 1.33 MMT, Mangalore 1.5 MMT, Padur 2.5 MMT; ~5.33 MMT combined ≈ 9.5 days of cover at full fill) are from PIB/Wikipedia public disclosures — SPR is a Ministry program outside PPAC's Ready Reckoner scope, so this could not be cross-checked against the provided documents.",
            "Grade preference is a simplified light/medium/heavy x sweet/sour tag, not a full assay slate.",
            "The topology does not capture every real supply route into every refinery (e.g. Panipat's real-world supply includes pipeline capacity beyond the single named Mundra-Panipat line modeled here) — this shows up as a small residual supply gap (~165 kbpd, ~3% of national demand; almost entirely Panipat/Bathinda under-connection) even in the scenario engine's baseline/no-disruption case. This is a disclosed completeness limit of a hackathon-scope topology, not a claim that India runs a structural supply deficit. (Revised down from an earlier ~300 kbpd estimate after an independent audit found ~132 kbpd of that figure was a code bug — Mumbai-bound domestic crude was stranded at its port with no onward edge — not a real topology gap; see DEVELOPMENT_LOG.md.)",
        ],
        "sources": [
            "India's Oil & Gas Ready Reckoner for FY 2025-26, v1 — Petroleum Planning & Analysis Cell (PPAC), Ministry of Petroleum & Natural Gas (user-provided PDF)",
            "Monthly Ready Reckoner / Snapshot of India's Oil & Gas — PPAC, July 2026 issue, data for June 2026 (user-provided PDF)",
            "RR_2024-25_H1_Final_WebUpload.xlsx — PPAC Ready Reckoner data tables, H1 FY2024-25 (user-provided Excel; Tables 4.1, 4.2, 4.3, 4.11, 5.2, 8.23, 8.24)",
            "ICB Notification, Ref No. PPAC/Indian Crude Basket Ratio/July 2026, dated 30.06.2026 — Indian Crude Basket pricing ratio (user-provided PDF)",
            "'Insights into Import of Crude Oil and International Crude Oil Prices', DGCI&S Commercial Intelligence Division, Ministry of Commerce & Industry, Sep-Oct 2025 (fetched from dgciskol.gov.in) — used to cross-check the country-wise file below; top-5 share trend FY2022-23 to FY2024-25",
            "dgcis_freeuser_1784552528488_1.xls — DGCI&S Foreign Trade Data Dissemination Portal export, 'India's Import By Principal Commodity Group From Jan-2025 To Dec-2025', PETROLEUM: CRUDE rows (user-provided Excel) — exact country-wise crude import quantity/value for calendar 2025, 34 countries",
            "PIB / PMFIAS — India's Strategic Petroleum Reserves (secondary, not in user-provided documents)",
            "PIB, Mar 2026 — 'India secures ~70% of crude oil imports outside Strait of Hormuz' (secondary, not in user-provided documents)",
        ],
    },
    "nodes": nodes,
    "edges": edges,
}

with open("data/network.json", "w", encoding="utf-8") as f:
    json.dump(network, f, indent=2)

print("Wrote data/network.json —", len(nodes), "nodes,", len(edges), "edges")
print("Total import kbpd:", TOTAL_IMPORT_KBPD, "| Total domestic kbpd:", TOTAL_DOMESTIC_KBPD)
print("Total refinery capacity kbpd:", round(sum(kbpd(v[1]) for v in REFINERY_MMTPA.values()), 1))
