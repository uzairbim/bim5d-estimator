# Research notes (November 2026)

What exists, what quantity surveyors struggle with, and the design decisions that follow.

## 1. Existing tools

| Tool | Type | Notes |
|---|---|---|
| RIB CostX, Autodesk Navisworks Quantification, iTWO, Sigma Estimates, ACCA PriMus | Commercial | Map cost codes to BIM quantities; CostX adds a cost layer to the 3D model. |
| **DataDrivenConstruction (DDC)**: CWICR database, n8n workflow template, OpenConstructionERP | Open source | The LinkedIn project that started this work matches DDC's public n8n template word for word: Revit → AI classification → work decomposition → CWICR prices → HTML/Excel. Needs a Windows-only converter, an OpenAI key and a Qdrant vector DB. OpenConstructionERP (AGPL-3.0) adds BOQ, takeoff, validation rule packs (DIN 276, NRM, MasterFormat, GAEB). |
| **DDC CWICR** | Open data | ~55,000 work items, ~27,000 resources, many regions, Excel/CSV/Parquet. **The repository lists the data licence as CC BY-NC 4.0 (non-commercial) with a separate commercial licence.** Sources disagree, so check `LICENSE-DATA.txt` before commercial use. This project imports rate sheets but does not bundle CWICR data. |
| IfcOpenShell / Bonsai | Open source | Core IFC toolkit (LGPL); Bonsai includes cost scheduling. Used here for reading and geometry. |
| Speckle | Open source | Open-source Revit connector and web sharing; no built-in cost estimating. A possible future input instead of IFC. |

## 2. What quantity surveyors struggle with

- **Trust in model quality** is the most cited problem in QS studies: incomplete models, missing
  information, designers not giving full access. → *Measure from geometry, show every formula, flag
  unpriced elements and broken shapes, compare with a cost-per-m² benchmark.*
- **Revit IFC base quantities are unreliable**: forum reports of wrong or missing base quantities
  (e.g. walls exported as `IfcWall` lack them), many fixes over exporter versions; the exporter
  deliberately does little of its own quantity takeoff. Seen in testing too: one sample slab's
  `GrossVolume` was written in the wrong unit (68,713 for 68.7 m³). → *Quantities are measured from
  the 3D shape in metres; base quantities are not trusted.*
- **Classification**: only about 10% of surveyed practices had a company classification system for
  BIM (Nigeria study). Revit can export Uniformat assembly codes as IFC classification references.
  → *Rules read classification codes when present, keywords otherwise, and a mapping screen +
  optional AI cover the rest.*
- **Approximate quantities / low level of detail** limit 5D. → *Recipes turn one element into several
  work items with explicit allowances (waste, rebar ratios) that the user can see and change.*
- **Inflexible standardised costs** reduce reliability. → *Regional rate overrides, per-project
  mark-ups, Excel import.*

## 3. Measurement standards in Saudi Arabia and the Gulf

- POMI (RICS Principles of Measurement International) is still widely used on international and
  Gulf contracts; NRM2 is the current RICS method for BOQs; NRM1 is for elemental cost plans. The
  contract's measurement clause decides. → *BOQ by trade/MasterFormat, elemental plans by NRM1 and
  Uniformat II.*

## 4. Saudi cost context

- Press reports for 2026 give standard villa construction at about **SAR 4,100–4,800 per m²** (high-end
  SAR 6,000–8,700). Used as a sample benchmark.
- GASTAT's construction cost index rose 2.4% (April 2026) and 2.6% year-on-year (May 2026), driven by
  equipment hire and labour. → *Keep rates editable and dated (the `source` column).*
- VAT in Saudi Arabia is 15%.

## 5. AI classification

- Research (CIB W78 2024) uses LLMs to link IFC elements to cost descriptions; an MDPI study
  reported a 5.1% difference from a manual estimate on 187 electrical components.
- Practitioners advise reviewing AI classifications and spot-checking quantities.
  → *AI is optional, only for types the rules miss, and suggestions need a click to accept.*

## Sources

- DDC CWICR repository: https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR
- CWICR on Hugging Face: https://huggingface.co/datasets/DataDrivenConstruction/cwicr-construction-rates
- DDC n8n template listing: https://aitoolly.com/n8n/workflow/estimate-4d5d-construction-costs-from-revit-bim-models-with-ddc-cwicr
- OpenConstructionERP: https://awesome.ecosyste.ms/projects/github.com%2Fdatadrivenconstruction%2Fopenconstructionerp
- OSArch discussion: https://community.osarch.org/discussion/comment/28865/
- Bonsai: https://opensource.construction/projects/bonsai/
- CIB W78 2024, IFC-based 5D: https://re.public.polimi.it/retrieve/0ace2925-718b-4de4-a078-f66420804682/CIBw78-2024-paper_116.pdf
- CIB W78 2024, LLM cost descriptions: https://re.public.polimi.it/retrieve/19b38145-cd05-44fe-94b3-2f1894d078e7/cibw782024_paper_86.pdf
- MDPI Buildings, MCP/LLM estimating: https://www.mdpi.com/2075-5309/16/3/485
- Revit IFC exporter releases: https://github.com/Autodesk/revit-ifc/releases
- Revit API, ExportBaseQuantities: https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API-MainReference/files/html/518cc0b7-934a-0110-0102-34aa932c4b0e.htm
- Wrong IfcWallBaseQuantities (Autodesk forum): https://forums.autodesk.com/t5/revit-architecture-forum/wrong-ifcwallbasequantities/m-p/9003220
- buildingSMART forum on quantities: https://forums.buildingsmart.org/t/which-software-to-create-lists-of-quantities-of-the-used-building-materials/5181
- IfcClassification with Revit: https://user.buildingsmart.org/knowledge-base/how-to-deal-with-ifcclassification-using-revit-2020/
- Revit Uniformat export issue: https://github.com/Autodesk/revit-ifc/issues/543
- 5D BIM and QS integration (BCU): https://www.open-access.bcu.ac.uk/6979/
- Measurement standards in 5D BIM (FIG 2019): https://www.fig.net/resources/Proceedings/fig_proceedings/fig2019/papers/ts05j/TS05J_amuda-yusuf_adebiyi_10013.pdf
- POMI usage (ISEC): https://www.isec-society.org/ISEC_PRESS/ASEA_SEC_03/pdf/C-15_v3_130.pdf
- NRM1 2nd edition (RICS): https://www.rics.org/content/dam/ricsglobal/documents/standards/nrm_1_order_of_cost_estimating_and_cost_planning_2nd_edition_rics.pdf
- Saudi construction cost index (Arab News): https://www.arabnews.pk/node/2644421
- Saudi villa cost per m² (Zawya): https://www.zawya.com/en/economy/real-estate/saudi-projects-value-hits-2.07trln-construction-real-estate-takes-major-share-1509870
