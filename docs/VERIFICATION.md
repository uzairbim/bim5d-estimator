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

## 1b. MEP against hand calculation

`tools/make_mep_check.py` builds pipes and ducts of known size running straight, at 45° in plan, sloped
(drainage) and vertical (riser):

| Element | Hand | Tool |
|---|---|---|
| DN50 pipe 10 m at 45° | 10 m of pipe up to DN50 | 10.0 m, small pipe (was 7.1 m of *large* pipe) |
| DN100 drain 12 m at 2% fall | 12 m of DN65–150 pipe | 12.0 m, medium pipe (was large pipe) |
| DN200 chilled water riser 9 m | 9 m large pipe + 9 m insulation | 9.0 m + 9.0 m insulation |
| Duct 600 × 400, 8 m (straight and diagonal) | 2 × (0.6 + 0.4) × 8 = 16 m² | 16.5 m² (incl. end caps) |
| Insulation | supply air and chilled water only | supply duct and chilled pipe insulated; exhaust and cold water not |

## 1c. Classification of typical Revit families

Test matrices (`tests/test_real_models.py`) check how typical Revit wall, floor, beam, column and MEP family
names are priced: 20 wall types (block, Concrete Masonry Units, RC with gypsum plaster, RC or thermal
block with stone cladding, gypsum partitions, foundation walls, Arabic names), floors with finish layers
("RC 200 + screed + porcelain" prices the 200 mm concrete and the tiles), timber joist floors, HSS steel,
and 34 MEP families (split AC, drains, fire extinguisher and hose reel cabinets, fire alarm devices,
CCTV, data outlets, manholes, generators, transformers by size, water meters). Errors these found and
fixed are in the change history.

## 1d. Excel workbook

Every workbook of 11 models, in English and Arabic (22 files, 15–16 sheets each), was recalculated in
LibreOffice and scanned: **0 error cells**. The Priced BOQ grand total equals the estimate total.

## 1e. Arithmetic and rules (tests/test_calculations.py)

- Openings by measurement standard on a 10 × 3 m wall with 0.3, 1.5 and 4 m² openings: NRM2 / POMI
  (≤ 0.5 m² not deducted), IS 1200 (masonry > 0.1 m²; plaster one face for 0.5–3 m², both faces above)
  and exact — all equal the hand calculation.
- Every rate = Σ norm × price; your own price and a fixed quote override correctly.
- Mark-up chain (preliminaries → contingency → overhead → profit → escalation → VAT), allowances as %,
  lump sum and per m², and hand-measured items equal the hand calculation.
- Cash flow adds up to the total; revision comparison finds exactly the known changes of the sample
  (1 wall added, 2 doors and 4 cabinets removed); rate packs carry every price.
- Modelled rebar: 3,680 bars of the Revit structural sample weigh 4,188 kg by volume × 7,850 against
  4,229 kg by diameter × length (−1%).
- Doors priced by kind and size: single doors per door, large / double / garage doors per m²,
  aluminium-glass doors per m², fire-rated doors (FD, EI60, T30…) at a fire-door price.
- Rooms exported as a 2D outline (no 3D body) keep their finishes: 5 × 4 m room → 20 m², perimeter
  18 m, paint 54 m² at 3.0 m.

## 1f. Arabic type names and Saudi substructure

- 44 Arabic family names (عمود، رقبة، ميدة، بلاطة هوردي، لبشة، بلوك معزول، طوب أحمر، جبس بورد، حجر رياض،
  كرسي افرنجي، كرسي عربي، مغسلة، خزائن مطبخ، ثلاجة، مصعد، لوحة رئيسية، مكيف سبليت، طفاية حريق، شجرة…) are priced
  as the right item (test matrix in `tests/test_real_models.py`).
- Neck columns and walls below the ground slab get bitumen coating on the part in contact with soil:
  villa 9 neck columns × 1.6 m × 1.5 m = 21.6 m², exactly.

## 1g. Room names (finishes by room type)

25 Arabic and Gulf room names are checked (`test_room_names`): wet rooms (دورة المياه، دورات مياه، مرحاض،
وضوء / Wudu، غرفة غسيل وكي) get floor and wall tiles with waterproofing; plant rooms (غرفة المضخات،
غرفة التكييف، AHU room, pool pump room) get hard-wearing finishes; courtyards and car porches external
paving; lift shafts, light wells (منور), pools and the roof (سطح، Roof terrace) get no room finishes,
because a shaft has none and the roof slab already carries the roof build-up. "Lift lobby" and
"ردهة المصاعد" stay normal rooms.

## 1h. Cash flow months

A 12-month programme gives exactly 12 months of cash flow (it gave 13, with an empty last month, for
most durations through a rounding error). Checked for 3, 6, 7.5, 12, 18, 24 and 36 months.

## 1i. External works and coverings (Saudi site items)

`tools/make_external_check.py` builds site items as Revit generic models usually are, with known sizes:

| Item | Hand | Tool |
|---|---|---|
| خزان أرضي 4 × 3 × 2.5 m + بيارة 2 × 2 × 3 m | 30 + 12 = 42 m³ | 42 m³ (per m³ complete) |
| خزان علوي | 1 nr | 1 nr |
| مظلة سيارات 6 × 5 m | 30 m² | 30 m² |
| Pergola 4 × 3 m | 12 m² | 12 m² |
| Swimming pool 8 × 4 m | 32 m² water area | 32 m² |
| Kerb | 10 m | 10 m |
| كاسرات شمس 3 × 2 m | 6 m² | 6 m² |
| Gate 4 × 2.2 m | 8.8 m² | 8.8 m² |
| Grass 10 × 5 m | 50 m² | 50 m² |

Errors this found and fixed: a car shade named مظلة سيارات was dropped as "cars", sun breakers were
priced as electrical circuit breakers, underground and roof tanks were a 12,000 SAR mechanical item,
glass partitions were blockwork, جدار استنادي was blockwork, and a wall covering named حجر was priced at
the generic finish rate. Assumed prices: underground tank about 960 SAR/m³ (published villa tanks
17,000–33,000 SAR), car shade about 120 SAR/m², pool 2,000 SAR/m² (no published figure found: replace
with a quote).

## 1j. MEP devices priced by what they are

Found on the Revit sample MEP models and fixed: smoke detectors were priced as distribution boards
(2,632 SAR each), telephone outlets as kitchen appliances (2,522 SAR), a 147 kW boiler as a small
device (1,588 SAR) because its 3D family is small, and a 5,000 L polyethylene tank as large plant
(12,914 SAR). Detectors, outlets, terminal boards and fire alarm panels are now recognised by name in
any IFC class; boilers, chillers, AHUs and cooling towers are central plant whatever their size; tanks
rated in litres are roof tanks.

Split air conditioners (مكيف سبليت، مكيف) are priced complete with the outdoor unit, copper piping and
drain (about 2,940 SAR for about 2 tons in Saudi Arabia); split outdoor units in the model are not
priced again, and the assumptions say so. Window units about 1,590 SAR.

Light, socket and switch points: the device alone was priced (socket 48 SAR). When cables are not
modelled (Revit wires do not export to IFC), conduit and wiring are added per point (about 10 m of
20 mm conduit and 3 wires, about 100 SAR), so a socket point is about 150 SAR, in line with Saudi
villa BOQs; the assumptions state it. A test now also refuses a code defined twice in the data (the
first try reused the rebar tying-wire code). Sanitary fixtures likewise: when pipes are not modelled (usual in an
architect's model), each fixture gets its supply and drain connection (about 10 m of pipe with
fittings, about 420 SAR); with modelled pipes they are measured instead, never both.

## 1k. Imperial (feet / inches) projects

`tools/make_units_check.py` writes the same small model in feet and in inches (a 20 × 30 × 1 ft
slab and a 20 ft × 10 ft × 8 in wall, placed 50 ft from the origin). Geometry comes out in metres
either way: slab 55.74 m², 16.99 m³; wall 18.58 m², 3.776 m³. Revit's own volumes and areas in such
files are in ft³ / ft² (or in³ / in²): they were read as m³ and m² (28 times too large in feet),
which upset the Revit comparison and the fall-back volume for shapes that cannot be measured; they
are now converted. In the app, Units "ft · ft² · yd³" also shows the cost per ft² and the floor area
in ft² (summary and client report).

## 1l. Brick walls and toilet partitions

Facing brick (face brick, brick veneer, engineering brick, Klinker, طوب واجهات) stays exposed: no
external render or paint (they were priced on the AdvancedProject façade); common brick (طوب أحمر,
German Ziegel) is still rendered and painted. Brick walls below ground get bitumen coating like block
walls. Toilet cubicle partitions modelled as walls ("WC Trennwand", "Toilet partition") are fitted
joinery per metre run, not 100 mm block or brick walls.

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
| Interior paint with putty (معجون), primer, two coats | painters advertise from 10 SAR/m² (labour) | 16.6 SAR/m² (putty was missing: 11.8) |
| Insulated block 20 cm | 3.4–5 SAR | 4.5 SAR |
| Shell (earthworks, concrete, block) | contractor guides 450–700 SAR/m² | 585 SAR/m² direct (villa example) |
| Turnkey mid-range villa | contractor guides 2,200–3,300 SAR/m² | villa example 1,743 SAR/m² without MEP, kitchen, sanitary, external works (≈ 2,200 with them) |

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
