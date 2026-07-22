# Data Sources — verified against user-provided PPAC documents

Four documents were added to `data/`: the **India Oil & Gas Ready Reckoner FY2025-26** (PDF, 133pp), the **Monthly Snapshot of India's Oil & Gas, July 2026 issue / data for June 2026** (PDF), the **RR_2024-25_H1 workbook** (Excel, ~90 tables), and the **ICB Notification dated 30.06.2026** (PDF). This replaces most of the earlier web-search approximations in `network.json` with PPAC's own published numbers. Figures below are cited by table/page so they can be checked against the source PDFs directly on a judges' Q&A.

## What changed vs. the Day 1 version

The refinery list grew from 12 to 16 (added Mathura, Haldia, Barauni, Bina — all individually broken out in PPAC Table 4.1), and every refinery capacity now uses PPAC's own installed-capacity figure as of 01.04.2024, converted with PPAC's own 7.33 bbl/tonne factor rather than a rounded estimate. Four of the port-to-refinery pipeline edges were replaced with real named pipelines and their actual capacities (previously invented). An indigenous (domestic) crude layer was added — four production regions feeding the graph through real pipelines — since ~10% of what refineries process is domestic, not imported, and the plan's model spec needs that distinction for grade/cost logic. Total import and price figures are now PPAC-verified rather than estimated.

## Verified figures

Refining capacity: all-India installed capacity was 256.816 MMTPA as of 01.04.2024 (Table 4.1), and PPAC's FY2025-26 chapter highlights separately cite 258.1 MMTPA nameplate capacity as of April 2025 across 22 operational refineries, of which private companies hold ~34.3%. Crude oil processing in FY2025-26 was 272.1 MMT at ~105% average capacity utilization.

Crude oil processing mix: imported crude was 89.7-90.0% of total crude processed in FY2024-25 (Table 4.3), the rest indigenous. High-sulphur crude was ~78.5% of total processing in FY2023-24 (Table 4.2).

Crude imports: 243.2 MMT in FY2024-25, 245.8 MMT in FY2025-26, and 59.8 MMT in Apr-Jun FY2026-27 (Snapshot, June 2026 issue, Table 6). Converted at 7.33 bbl/tonne, FY2025-26 imports are ~4,936 kbpd (~4.94 mbpd) — this is the number now used to scale supplier flows in the graph.

Indigenous production: 28.7 MMT in FY2024-25, 28.0 MMT in FY2025-26 (Snapshot Table 2), ~562 kbpd. Of June 2026 production, 77.3% came from Nomination fields, 12.5% from Pre-NELP fields, and 10% from NELP fields (Snapshot, Highlights).

Crude oil price: the Indian Basket averaged $78.56/bbl in FY2024-25 and $70.99/bbl in FY2025-26, rising to $83.22/bbl in June 2026 (Snapshot Table 25). The ICB Notification (dated 30.06.2026) sets the pricing ratio for 15-31 July 2026 at 79.40% Dated Brent / 20.60% Dubai-Oman.

Pipeline infrastructure: the national crude oil pipeline network was 10,443 km with 153.1 MMTPA capacity as of 31.03.2026, running at 66.7% utilization in FY2025-26 (RR FY2025-26, Chapter 5 highlights). The underlying Excel (Table 5.2, as of 01.10.2024) lists each pipeline individually — Salaya-Mathura (2,646 km, 25 MMTPA, IOCL), Paradip-Haldia-Barauni (1,873 km, 20.4 MMTPA, IOCL), Mundra-Panipat (1,194 km, 8.4 MMTPA, IOCL), Mundra-Bathinda (1,017 km, 11.25 MMTPA, HMPL, running at 116% utilization), Vadinar-Bina (937 km, 7.8 MMTPA, BPCL), Mangla-Bhogat (688 km incl. offshore, 10.71 MMTPA, Cairn), and Duliajan-Digboi-Bongaigaon-Barauni (1,195 km, 8.95 MMTPA, OIL) — all now used directly as edge capacities in `network.json` instead of invented numbers.

## Country-wise import shares — now exact, not estimated

This gap is closed. `dgcis_freeuser_1784552528488_1.xls` — a DGCI&S Foreign Trade Data Dissemination Portal export the user pulled directly ("India's Import By Principal Commodity Group From Jan-2025 To Dec-2025") — lists all 34 countries India imported crude petroleum from in calendar 2025, by quantity (tonnes) and value (INR and USD). These are now the exact percentages used in `network.json`, not an estimate: Russia 32.7%, Iraq 18.8%, Saudi Arabia 13.2%, UAE 10.8%, USA 7.4%, Kuwait 3.1%, Nigeria 2.9%, Angola 2.1%.

The remaining 26 countries, each individually under 2%, used to be pooled into a single "Other" node (9.1% combined) — per an independent-review request ("can we separate each country in the nodes that combine 26 countries together so the network looks full?"), all 25 of them with nonzero 2025 volume are now modeled as their own supplier node with a real export-terminal coordinate, corridor, and shipping edge (Hungary, the 26th, reported exactly 0 tonnes and is correctly omitted): Egypt 1.34%, Colombia 1.09%, Brazil 1.05%, Qatar 1.05%, Oman 0.90%, Libya 0.41%, Mexico 0.37%, Malaysia 0.34%, Venezuela 0.32%, Congo-Brazzaville 0.31%, Turkey 0.29%, Gabon 0.21%, South Korea 0.20%, Ghana 0.19%, Brunei 0.18%, Uruguay 0.14%, Algeria 0.13%, Singapore 0.11%, DR Congo 0.10%, Argentina 0.09%, Panama 0.07%, Togo 0.07%, Canada 0.05%, South Sudan 0.04%, Cameroon 0.02%. See `build_network.py`'s `SUPPLIER_META` for each country's specific terminal and the corridor/exposure reasoning, and KNOWN_LIMITATIONS.md item 9 for the caveat that a few of these (Panama, Singapore, Uruguay) are likely transshipment points rather than producing countries in the source data.

Two independent numbers in this file cross-check cleanly against the PPAC documents, which is why it can be trusted rather than just taken on faith: dividing its total value by quantity gives an implied price of $71.18/bbl for calendar 2025, within 30 cents of PPAC's own $70.99/bbl FY2025-26 average; and its top-5-country share (82.76%) lands within 0.2 points of the 82.57% figure DGCI&S's own published report gave for FY2024-25. Two different DGCI&S data pulls, two different periods, essentially the same answer.

One caveat worth stating plainly: these are calendar-year 2025 (Jan-Dec) percentages applied to PPAC's fiscal-year 2025-26 (Apr'25-Mar'26) volume total, since that's the most authoritative total available. The two periods overlap by nine months but aren't identical — a minor, disclosed approximation, not a gap.

## What is still NOT verified

SPR inventory figures (Vizag/Mangalore/Padur) are not covered in PPAC's Ready Reckoner (SPR sits under a separate Ministry program) and are still sourced from PIB/Wikipedia. If you want to close this one too, the same DGCI&S portal won't help (SPR is a MoPNG strategic reserve program, not a trade statistic) — PIB press releases or a direct RTI to MoPNG would be the path.

## Files

`build_network.py` regenerates `data/network.json` from these figures — rerun it if you get better country-wise or SPR data later rather than hand-editing the JSON.
