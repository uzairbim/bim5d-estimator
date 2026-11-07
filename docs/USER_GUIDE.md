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

## 2. Create a project

Open the app, pick the **region**, and drop the .ifc file. The first time, a large model takes about
a minute to measure; after that it opens instantly. Or choose a **sample** to try it.

## 3. Read the summary

- **Total** includes contingency, overhead, profit and VAT (15% in Saudi Arabia).
- **Elements priced**: if some are not priced, open **Mapping**.
- **Cost per m²** is compared with a typical range for the region. A low figure usually means parts
  of the building (services, external works) are not modelled yet.
- **Elemental cost plan**: switch between NRM1, Uniformat and Level.
- **Project settings**: change contingency, overhead, profit, tax and rebar basis for this project.

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

## 6. Rates

Click **Rates**. Each work item shows the base rate converted to your currency. Type your own
material, labour and equipment rates to override it. **Download Excel** gives the full table; fill it
in and **Import** it back. Accepted columns: `work_item` (or `code`), `material`, `labour`,
`equipment`, or a single `rate`.

## 7. 4D and cash flow

Open **4D**. Set the construction time in months. Drag the slider or press **Play** to watch the
building go up: orange is being built, grey is done. The S-curve shows the monthly and cumulative
cost (including mark-ups).

## 8. Compare revisions

In **Compare**, click **Upload new revision** and choose the new IFC export of the same Revit model.
Then compare the two revisions: added elements are green, changed orange, removed red. The table
shows the cost difference by trade and per element, with the reason (for example "volume 8.2 → 12.3").

## 9. Export

**Export Excel** downloads the full estimate: summary, NRM1 and Uniformat cost plans, BOQ, every
element's cost lines with formulas, mapping, programme, cash flow with an S-curve chart, and model checks.

## Adapting it to your company

Everything that decides the price is in `data/` as CSV files you can open in Excel. See the README.
Typical changes:
- add your own work items and rates,
- change rebar ratios (kg per m³) in `recipes.csv`,
- add keywords used in your Revit templates to `rules.csv`,
- add a country to `regions.json`.
