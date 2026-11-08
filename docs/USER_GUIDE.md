# User guide

## 1. Export IFC from Revit

1. **File → Export → IFC**.
2. Choose **IFC 2x3 Coordination View 2.0** or **IFC4 Reference View**.
3. **Property Sets** tab: tick **Export Revit property sets** and **Export base quantities**.
4. Good practice that makes pricing more automatic:
   - Give types clear names: `Block Wall 200 Plastered`, `RC Slab 200`, `Steel Beam IPE300`.
   - Set **materials** on layers (walls, floors, roofs). The estimator prices each layer, for example
     only the concrete layer of a floor build-up.
   - Fill **Assembly Code** (Uniformat) on types. It is exported as a classification and used by the rules.
   - Model per floor (walls and columns floor to floor), so the 4D sequence and cost by level are correct.
   - **Place rooms** with clear names (Bathroom, Kitchen, Bedroom, Store, Balcony…). Rooms are exported as
     IfcSpace and drive the finishes: floor, skirting, wall paint or tiles, ceiling paint, waterproofing.
   - Set walls as **External** in their type (IsExternal) so external render and paint go on the right face.

## Set up your country (once)

1. Start page → **Add my country / prices** (or **Rates → Region & sharing** inside a project).
2. Choose the country and click **Create region**. Currency and VAT are filled in.
3. Click **Update from World Bank** (needs internet) or type the exchange rate.
4. Tab **Local prices**: enter the **key prices** first (skilled and unskilled labour per hour, ready-mix,
   cement, sand, aggregate, rebar, blocks, bricks, plywood, timber, paint, tiles, gypsum board, structural
   steel, doors, windows, waterproofing, excavator hire). Add the supplier and date in the source column.
5. Tab **Work item rates**: click any item to see how its rate is built. Type a **fixed rate** only when
   you have a quote for the complete item.
6. **Download rate pack** to share your prices; others use **Import rate pack**.

Saudi Arabia, UAE, Pakistan, India, UK, Germany and the USA already have **assumed** prices (typical market
levels, late 2026), so an estimate works straight away. Type over them with current prices; the accuracy
class moves from Class 4 to Class 3 once at least half the cost uses your own prices.

The "your prices" percentage on each rate, and the accuracy class, show how much of the estimate rests on
your own prices.

## Fastest way to start

1. Start page: check the **Region** (pre-selected from your computer) and click **Try the demo**.
2. Read the **What to do next** box at the top of the Summary and click its buttons in order.
3. When you are ready, upload your own IFC file the same way.

The **?** button (top right) explains every term and answers common questions.

## Sending a project to a colleague

Summary → Project settings → **Download project file**. It contains the model revisions and all your
choices (mappings, allowances, manual items, settings). Your colleague clicks **Open a project file** on
the start page. Prices are shared separately as a rate pack (Prices & rates → Region & sharing).

## Resources (bill of materials)

BOQ tab → **Resources**: total labour hours, cement bags, rebar tonnes, blocks, ready-mix and so on, with
each one's share of the cost and what a 10% price rise would add. Use it to order materials, plan labour
and see which prices to confirm first. The Excel workbook has the same table.

## Defaults a senior estimator would use

- Loose furniture (beds, sofas, chairs, tables) is listed but **not** in the total: it is normally the
  client's separate FF&E budget. Built-in joinery (kitchen cabinets, vanities, wardrobes) is included.
  Tick **Include loose furniture** in Project settings to add it.
- Taps and mixers are part of the sanitary fixture, not priced twice.
- Small mechanical units (radiators, fan coils) and large plant (boilers, chillers, AHUs) have different rates.
- In a model without walls (e.g. an MEP model) room finishes are not priced, so they are not double
  counted with the architectural model.

## 2. Create a project

Open the app, pick the **region**, and drop the .ifc file. The first time, a large model takes about
a minute to measure; after that it opens instantly. Or choose a **sample** to try it.

## The six steps (shown at the top of the panel)

1. **Model**: upload; quantities are measured automatically.
2. **Map**: give every unknown element type a meaning.
3. **Rates**: enter your rates (sample rates keep the estimate at Class 5).
4. **Scope**: check which parts of the building are not in the model and add allowances.
5. **Check**: review overlaps, possible duplicates and quantities that differ from Revit's own values.
6. **Report**: print the client report (PDF) and export the Excel workbook.

A step turns green when it is done.

## 3. Read the summary

- **Total** includes contingency, overhead, profit and VAT (15% in Saudi Arabia).
- **Elements priced**: if some are not priced, open **Mapping**.
- **Cost per m²** is compared with a typical range for the region. A low figure usually means parts
  of the building (services, external works) are not modelled yet.
- **Elemental cost plan**: switch between NRM1, Uniformat and Level.
- **Project settings**: change contingency, overhead, profit, tax and rebar basis for this project.

## Accuracy: how to read and improve it

The summary shows an **accuracy class** and the range the final cost is likely to fall in
(AACE 18R-97 classes as guidance):

| Class | Range | When |
|---|---|---|
| 5 | -50% / +100% | most rates are still sample placeholders |
| 4 | -30% / +50% | important scope missing (MEP, finishes, foundations) without an allowance, or >10% elements unpriced |
| 3 | -20% / +30% | model priced with your rates, scope covered |
| 2 | -15% / +20% | all checks pass and you confirm rates are current market prices |

The list under the class says exactly what to do to narrow the range.

**What the tool already does for accuracy**
- Measures each element from its 3D shape and repairs badly exported shapes.
- Compares every measured volume with Revit's own value (Checks tab); 95%+ agreement is normal.
- Deducts overlapping volume once (column through slab, beam in slab, wall through column).
- Applies the NRM2 rule for small openings (up to 0.5 m², editable).
- Lets you adjust the quantity of a type (Element tab), but only with a written reason.
- Logs every change (Checks tab → Change history).

## 4. Mapping: tell it what unknown elements are

Each row is one element type. Choose **Priced as** and all elements of that type are priced that way.
Choose **Do not price** for things that are not construction work. Your choices are saved with the
project and override the automatic rules. **Reset** goes back to the automatic rule.

Click a row to highlight those elements in 3D.

With an AI key on the server, **Suggest with AI** proposes a recipe for every unknown type, with a
reason and a confidence. Nothing is applied until you click **Accept**.

## 5. Check an element

Click any element in 3D. You see:
- its cost broken into work items, with the **formula** used and the waste allowance,
- the quantities measured from its shape,
- its materials and layer thicknesses, classification and Revit properties,
- when it is built in the 4D sequence.

You can change how its type is priced right there.

## 6. Prices & rates

See *Set up your country* above. Excel is supported too: **Rates to Excel** downloads every item; fill
it in and **Rates from Excel / CSV** imports it (columns `work_item` or `code`, then `material`,
`labour`, `equipment`, or a single `rate`).

## Quantities that are not modelled as objects

The tool adds the quantities an estimator derives from the model:

| From | Derived items |
|---|---|
| Rooms | floor finish (if no floor finish is modelled), skirting = perimeter − door widths, wall paint = perimeter × height − doors and windows, ceiling paint; bathrooms: wall tiles full height + waterproofing with 300 mm upturn; kitchens: splashback tiles; plant rooms: floor hardener; balconies: waterproofing |
| Walls | masonry, plaster and paint per face with the opening rule of your standard; external walls: render + external paint outside, plaster inside |
| Doors / windows | lintels (width + 300 mm bearing) in masonry walls, window sills, sealant both sides, plaster to reveals |
| Foundations / ground slab | excavation with working space, blinding, backfill, hardcore, DPM, anti-termite treatment |
| Slabs / roofs | edge formwork, roof waterproofing with upstands, screed |
| Steel, MEP | protective paint to steel; insulation for chilled / heating pipes and supply / return ducts |

**Wall and ceiling finishes from** (project settings): *Automatic* uses rooms when the model has them,
otherwise both faces of walls. Choose *Walls* if your rooms are incomplete.

**Commonly forgotten items** (summary) lists 28 items (including bitumen coating to foundations, wall insulation for the energy code, water tanks, sewer connection and boundary wall) with their status: priced, allowance, missing or
"normally in preliminaries". Click **Add x%** to cover a missing one with an allowance.

**Items measured by hand**: add anything not in the model (boundary wall, external works, temporary
items). Pick a work item to use its rate, or type your own rate.

## Measurement standard

Project settings → **Measurement standard**: NRM2 / POMI (openings up to 0.5 m² not deducted from
masonry and finishes), IS 1200 (masonry 0.1 m²; finishes: up to 0.5 m² not deducted, 0.5–3 m²
deducted from one face, larger from both), or Exact (every opening deducted). Check the measurement
clause of your contract.

## Things the tool checks in real Revit models

- **Floor area** is measured level by level: the larger of the floor slabs, floor build-ups or rooms. The roof
  level is not counted. If one level is much bigger than the others (paving or a podium modelled as floor), a
  warning appears; open *Floor area by level* under the cost per m² and type the correct total if needed.
- **Revit phases**: elements created in an *Existing* phase or demolished are not priced as new work
  (listed in the assumptions). Map them if they are new.
- **Generic types** ("Generic - 200mm", "Default Floor"): their share of the cost is shown. Above 15% the
  estimate stays Class 4 until you choose what they are in Mapping.
- **Duplicates**: elements or rooms modelled twice in the same place are counted once and listed in Checks.

## Separate models for structure and MEP

Many projects have one Revit model per discipline. Open the architecture project, go to **Compare**, choose the
discipline (Structure, MEP, Electrical, Plumbing…) and click **Add a discipline model**. The estimate then adds up
the latest revision of each discipline, the 3D view shows them together and the summary lists the combined
revisions (for example *Rev 2 + Structure Rev 1 + MEP Rev 1*).

- An element drawn in two models (structural columns kept in the architect's model, or the same Revit element
  exported twice) is counted once; the structure model's copy is kept. They are listed under Checks.
- Floor area matches the structure model's levels to the architect's levels by height.
- To update one discipline, select one of its revisions and use **Upload new revision**.

## Arabic BOQ

Choose العربية (top right): the BOQ, element costs and mapping show Arabic names with English below. The Excel
BOQ has Arabic description, trade and unit columns for Saudi Arabia and other Arab countries. To change a
name, edit `data/translations.csv` in Excel.

## Language and units

Top right: interface language (English, Arabic, Urdu, Spanish, French) and display units
(metric, or ft / ft² / yd³ / lb). Exports stay metric.

## 7. 4D and cash flow

Open **4D**. Set the construction time in months. Drag the slider or press **Play** to watch the
building go up: orange is being built, grey is done. The S-curve shows the monthly and cumulative
cost (including mark-ups).

## 8. Compare revisions

In **Compare**, click **Upload new revision** and choose the new IFC export of the same Revit model.
Then compare the two revisions: added elements are green, changed orange, removed red. The table
shows the cost difference by trade and per element, with the reason (for example "volume 8.2 → 12.3").

## 9. Client report

Click **Client report**. A clean A4 report opens: summary with the accuracy range and cost per m²,
cost build-up, NRM1 elemental summary, **main cost drivers** (the 10 biggest items and the prices that move the total most), trade and level summaries, scope and allowances, assumptions,
exclusions and model quality checks, with a 3D picture. Click the dashed fields to type the client
and estimator names, then **Print / Save as PDF**.

## 10. Export

**Export Excel** downloads the full estimate: summary, NRM1 and Uniformat cost plans, BOQ, every
element's cost lines with formulas, mapping, programme, cash flow with an S-curve chart, and model checks.

## Adapting it to your company

Everything that decides the price is in `data/` as CSV files you can open in Excel. See the README.
Typical changes:
- add your own work items and rates,
- change rebar ratios (kg per m³) in `recipes.csv`,
- add keywords used in your Revit templates to `rules.csv`,
- add a country to `regions.json`.
