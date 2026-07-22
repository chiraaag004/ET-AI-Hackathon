# AI-Driven Energy Supply Chain Resilience for India

**ET AI Hackathon 2026 — Problem Statement 2**

A working digital twin of India's crude-oil import network: a 71-node knowledge graph, a disruption scenario engine, and a two-stage stochastic optimizer (with CVaR risk-aversion) that recommends an adaptive procurement response in under a second — presented through a 5-tab Streamlit dashboard, in plain language or full technical depth.

This isn't a mockup. The Strait-of-Hormuz closure this build treats as its worst-case scenario has been the real, ongoing situation since 28 February 2026 — see [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md) §8 for the model checked directly against real-world reporting.

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Run the test suite (111 tests):

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/ -v
```

Regenerate the knowledge graph from source data (only needed if you change `build_network.py`):

```bash
python3 build_network.py
```

## What's in the dashboard

| Tab | What it shows |
|---|---|
| **Current System** | Plain-English explanation, baseline stat cards, live import map. |
| **Scenarios** | Pick a disruption via clickable pill-cards; get a plain-language impact story and an updated map. |
| **News** | The same story, triggered by a real, dated 2026 headline instead of a manual pick. |
| **Details & Charts** | KPIs, the full technical briefing, cost/shift/refinery charts, and a 4-slider robustness stress-test. |
| **Data & Methods** | Sources, assumptions, node/edge tables, PPAC-verified figures, and the real-world validation comparison. |

## Architecture

```
Source documents (PPAC, DGCI&S)
        |
        v
build_network.py  -->  Knowledge Graph (data/network.json) -- 71 nodes, 65 edges
        |
        +--> signal_extractor.py   (headline -> disruption signal)
        +--> scenario_engine.py    (degrades edge capacity by chokepoint severity)
        +--> optimizer.py          (2-stage stochastic LP + CVaR, Pyomo/HiGHS)
        |
        v
briefing_generator.py  (plain-language translation)
        |
        v
app.py  -- 5-tab Streamlit dashboard
```

Full diagram: `PS2_Digital_Twin_Presentation.pptx` (slide 4) or Figure 1 in `PS2_Digital_Twin_Report.docx`.

## Repository structure

```
app.py                   Streamlit dashboard (5 tabs)
optimizer.py             Adaptive Procurement Orchestrator -- 2-stage stochastic LP + CVaR
scenario_engine.py       Disruption Scenario Modeller
signal_extractor.py      Geopolitical Risk Intelligence Agent (headline -> signal)
briefing_generator.py    Plain-language translation of optimizer output
build_network.py         Builds data/network.json from cited source data
animated_map.py          Client-side animated map rendering
llm.py                   Pluggable LLM interface (optional, ANTHROPIC_API_KEY)
data/network.json        The generated knowledge graph (71 nodes, 65 edges)
tests/                   111 automated tests across 8 files
.streamlit/config.toml   App theme

SPEC.md                  Original one-page model formulation
KNOWN_LIMITATIONS.md      Every disclosed scope cut and approximation
DATA_SOURCES.md           Full data provenance and methodology
TESTING.md                What the test suite covers (and doesn't)
DEVELOPMENT_LOG.md         Build history and bug fixes
AUDIT_FINDINGS.md          Independent audit of the solved model

PS2_Digital_Twin_Presentation.pptx   Presentation deck (incl. architecture diagram)
PS2_Digital_Twin_Report.docx         Detailed technical report
DEMO_VIDEO_SCRIPT.md                 3-4 minute demo video script
```

Raw source documents (PPAC PDFs/Excel, DGCI&S export) live in `data/` for provenance but are **not** parsed at runtime — every figure they contain is extracted once into `build_network.py` as a cited constant. They're excluded from version control (see `.gitignore`) since they're large, third-party government publications the app doesn't depend on at runtime.

## Data sources

PPAC's India Oil & Gas Ready Reckoner (FY2025-26), PPAC's Monthly Snapshot (June 2026), the ICB Notification (30.06.2026), and a DGCI&S Foreign Trade Data Dissemination Portal export (calendar-2025 country-wise crude imports). Full citations and cross-checks in `DATA_SOURCES.md`.

## Known limitations

Every scope cut is documented before anyone has to ask about it — single-period SPR modeling, no rerouting-with-delay, no disruption-time freight spike, the fairness objective, and an unimplemented grade-compatibility constraint from the original spec. Full list: `KNOWN_LIMITATIONS.md`.

## License / attribution

Built for ET AI Hackathon 2026. Underlying data is sourced from PPAC (Petroleum Planning & Analysis Cell, Ministry of Petroleum & Natural Gas) and DGCI&S (Ministry of Commerce & Industry), both Government of India public sources.
