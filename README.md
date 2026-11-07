# BIM 5D Estimator (open source, web based)

Upload a Revit model (exported as IFC). The app measures every element from its 3D geometry,
breaks each element into construction work items, prices them with regional rates,
and shows the cost on the 3D model. Export the estimate to Excel.

Works for any country: rates, currency, VAT/GST, overhead and profit are set per region.

## Run it

```bash
pip install -r requirements.txt
cd web && npm install && cd ..
uvicorn server:app --port 8000
```

Open http://localhost:8000. In Revit use **File → Export → IFC** (IFC 2x3 or IFC4).

## How it works

```
Revit ──IFC──▶ 1 Extract ──▶ 2 Classify ──▶ 3 Decompose ──▶ 4 Price ──▶ 5 Report
               geometry        rules.csv      recipes.csv      rates/       3D + BOQ + Excel
               quantities                                      regions.json
```

1. **Extract** (`engine/extract.py`): IfcOpenShell reads each element: class, name, type, level,
   materials and layer thicknesses. Volume, wall face area, plan area and length are measured from the
   geometry in metres, so the result doesn't depend on missing quantity sets or model units. Shapes that
   aren't closed solids are flagged for review.
2. **Classify** (`data/rules.csv`): IFC class + keywords (regex on name, type and materials) → recipe.
3. **Decompose** (`data/recipes.csv`): one element → several work items with formulas,
   e.g. RC slab → concrete `footprint*t("concrete")`, formwork `footprint`, rebar `volume*100` kg.
   `t("regex")` = thickness of matching material layers, `has("regex")` = 1 if such a layer exists.
4. **Price** (`data/rates/`): `base_usd.csv` is the global rate set. A region file (e.g. `SA.csv`, in local
   currency) overrides it item by item. Items without a local rate use base × exchange rate × location factor.
5. **Report**: totals by trade and level, BOQ, cost per element, model checks, Excel export.

All files in `data/` are plain CSV/JSON you can edit in Excel. The app reloads them on every estimate.

> **All rates shipped here are SAMPLE placeholders.** Replace them with your own prices before use.

## Add a country
Add an entry to `data/regions.json` (currency, exchange rate, location factor, tax, overhead, profit).
Optionally add `data/rates/<CODE>.csv` with local rates.

## Roadmap
- [ ] **AI fallback classifier**: elements with no matching rule go to an LLM, which suggests a recipe; a person approves it and it's saved as a new rule.
- [ ] **CWICR import**: load the open DDC CWICR cost database (55k items, many regions) as a rate source.
- [ ] **Version compare**: upload revision B and see added, removed and changed elements and the cost difference.
- [ ] **4D link**: import a P6 / MS Project schedule, link elements to activities, and show a cash-flow S-curve.
- [ ] **Revit add-in (C#)**: one-click export and push costs back into Revit parameters for colored views.
- [ ] **Projects and users**: save projects in a database (PostgreSQL), with rate libraries per company.
- [ ] **Arabic UI and RTL**, MasterFormat / Uniformat / NRM grouping options.
