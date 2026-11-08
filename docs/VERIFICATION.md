# Verification: are the quantities and prices right?

Every number below is checked automatically by the tests (`tests/test_real_models.py`), so a future
change that breaks one of them fails the test suite.

## 1. Quantities against hand calculation (Saudi villa example)

`samples/Saudi_Villa_Example.ifc`: two storeys 12 × 12 m, 9 isolated footings 2 × 2 × 0.6 m at 2.1 m below
ground, 6 tie beams 300 × 600, 27 columns 300 × 500, 150 mm ground slab, 200 mm first floor slab, 320 mm
hordi roof, thermal block external walls, hollow block internal walls, 1.2 m parapets, 16 windows
1.5 × 1.5, one door 0.9 × 2.1, rooms with Arabic names. Net quantities, before waste.

| Item | Hand calculation | Tool | Difference |
|---|---|---|---|
| Concrete, all elements | exact boolean union of the solids 105.22 + hordi ribs and topping 144 × (0.07 + 0.25 × 0.23) = 18.36 → **123.58 m³** | **123.75 m³** | +0.14% |
| Footings + tie beams | 9 × 2 × 2 × 0.6 + 6 × 12 × 0.3 × 0.6 = 34.56, junctions once | 34.34 m³ | −0.6% |
| Windows | 16 × 1.5 × 1.5 = **36.0 m²** | 36.0 m² | 0 |
| Lintels | 16 × (1.5 + 0.3) + (0.9 + 0.3) = **30.0 m** | 30.0 m | 0 |
| Marble floor | 2 × 11.6 × 5.6 = **129.9 m²** | 129.9 m² | 0 |
| Slab soffit formwork | 2 × 144 + stair 3 × 1.2 × 1.2 = **292.3 m²** | 292.3 m² | 0 |
| Thermal block (NRM2: openings > 0.5 m² deducted, columns out) | 8 × 12 × 3.3 − 16 × 2.25 − 1.89 − column zones 23.8 + parapets 57.6 ≈ **306 m²** | 305.2 m² | −0.3% |
| Roof waterproofing | 144 + 48 × 0.3 upstand = **158.4 m²** | 158.4 m² | 0 |
| Excavation (ground to underside + 50 mm, 300 mm working space) | 9 × 6.76 × 2.15 + 6 × 11.34 × 0.65 = **175.0 m³** | 175.0 m³ | 0 |
| Floor area | 2 × 144 (roof not counted) = **288 m²** | 288 m² | 0 |
| Majlis wall paint | 23.2 × 3.0 − 2 windows − door = **63.21 m²** | 63.21 m² | 0 |
| Majlis skirting | 23.2 − 0.9 door = **22.3 m** | 22.3 m | 0 |
| Bathroom wall tiles | 11.2 × 3.0 − 2.25 window = **31.35 m²** | 31.35 m² | 0 |
| Bathroom waterproofing | 7.84 + 11.2 × 0.3 upturn = **11.2 m²** | 11.2 m² | 0 |
| Kitchen splashback | 23.2 × 0.4 × 0.6 = **5.57 m²** | 5.57 m² | 0 |

Errors this check found and fixed: excavation dug only the footing's own height (a footing 2.1 m deep
was dug 0.75 m), column formwork ran through the slab (now to the soffit), tie beams used the pad
footing rebar ratio, parapets were plastered both sides instead of rendered outside, and ceilings had
no plaster.

## 2. Real Revit models

Eight public Revit exports (Revit 2010–2021: Autodesk sample projects, an office in architecture,
structure and MEP models, houses) were run end to end. 98–100% of element volumes agree within 5% with
Revit's own volumes (Checks tab). Errors found there and fixed are listed in the change history
(floor area, roof slabs drawn as floors, timber priced as concrete, plumbing fixtures excluded, false
duplicates, curtain wall prices, survey coordinates, memory).

## 3. Prices and cost per m² against the Saudi market (late 2026)

| | Source figure | Tool (assumed prices) |
|---|---|---|
| Rebar | GASTAT June 2026: 3,310 SAR/t (8 mm) | 3,300 SAR/t |
| Ready-mix 350 kg | CEIC / Contractors Authority 2026: 216–228 SAR/m³ | 230 SAR/m³ |
| Cement 50 kg | 15.8 SAR | 15 SAR |
| Hollow block 20 cm | 1.7–4 SAR | 2.5 SAR |
| Insulated block 20 cm | 3.4–5 SAR | 4.5 SAR |
| Shell (earthworks, concrete, block) | contractor guides 450–700 SAR/m² | 563 SAR/m² direct (villa example) |
| Turnkey mid-range villa | contractor guides 2,200–3,300 SAR/m² | villa example 1,685 SAR/m² without MEP, kitchen, sanitary, external works (≈ 2,200 with them) |

Rebar ratios (kg per m³): pad footings 80, ground / tie beams 120, columns 160, beams 140, slabs 100,
hordi slabs 110, walls 90, stairs 110 — inside the published estimating ranges (footings 75–90,
grade beams 100–125, columns 160–225, beams 120–160, slabs 80–110). Replace them with the bar schedule
when it exists (Project settings → Rebar based on modelled bars).

## 4. How to check your own model

1. **Checks tab**: measured volumes against Revit's own; overlaps; duplicates; shapes not measured
   exactly.
2. **Element tab**: click any element: each quantity shows its formula.
3. **Floor area by level** under the cost per m².
4. **Scope check and commonly forgotten items** on the summary.
5. Compare the **Resources** list (cement bags, rebar tonnes, blocks) with your experience of similar
   buildings.

Sources: [GASTAT rebar via Amlak](https://amlak.net.sa/en/107640/),
[CEIC Saudi construction material prices](https://www.ceicdata.com/en/saudi-arabia/average-construction-materials-price/construction-materials-price-average-sand-red),
[Contractors Authority price statistics Jan 2026](https://muqawil.org/public/publications/ca9f7e09bbd5c6607160262b992b564ebd709c4a.pdf),
[Msamer 2026 material prices](https://www.msamer.com/en/blog/construction-material-prices-saudi-2026),
[Site Engineer villa cost 2026](https://site-engineer.net/en/guides/building-cost),
[Raghdan building cost guide](https://raghdan.sa/en/news/building-house-cost-saudi-2025/),
[ExpertConsult Riyadh calculator](https://expertconsult.sa/article/%D8%AD%D8%A7%D8%B3%D8%A8%D8%A9-%D8%AA%D9%83%D9%84%D9%81%D8%A9-%D8%A7%D9%84%D8%A8%D9%86%D8%A7%D8%A1),
[arabian-home insulated block prices](https://arabian-home.com/cement-insulated-block-prices-riyadh/),
[The Constructor reinforcement quantities](https://theconstructor.org/practical-guide/size-and-quantity-of-reinforcement-for-building-works/7365/),
[OneClick LCA reinforcement rates](https://help.oneclicklca.com/en/articles/275888).
