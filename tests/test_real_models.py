"""Lessons from real Revit exports (Autodesk samples, offices, houses), kept as small tests."""
import copy
from pathlib import Path

import pytest

from engine.estimate import Library, estimate, gross_floor_area, is_existing
from engine.extract import extract

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture(scope="module")
def lib():
    return Library()


@pytest.fixture(scope="module")
def duplex():
    return extract(str(SAMPLES / "Ifc2x3_Duplex_Architecture.ifc"), with_mesh=False)["elements"]


def _like(els, ifc_class, **changes):
    e = copy.deepcopy(next(x for x in els if x["ifc_class"] == ifc_class))
    e.update(changes)
    return e


@pytest.mark.parametrize("cls,name,materials,recipe", [
    ("IfcSlab", 'Basic Roof:Wood Rafter 8" - Asphalt Shingle - Insulated', ["Wood - Stud Layer"], "ROOF_LIGHT"),
    ("IfcSlab", "Floor:Raft foundation 600", ["Concrete"], "RC_FOOTING"),
    ("IfcSlab", "Floor:Joist floor", ["Wood - Sheathing_floor", "Wood - Stud Layer"], "TIMBER_FLOOR"),
    ("IfcBeam", "Dimension Lumber:2x8", ["Wood - Dimensional Lumber"], "TIMBER_MEMBER"),
    ("IfcColumn", "Timber-Column:Glulam Column", ["Wood"], "TIMBER_MEMBER"),
    ("IfcBeam", "UB-Universal Beam:305x165x40UB", ["Steel"], "STEEL_MEMBER"),
    ("IfcSlab", "Floor:Rug", [], "LOOSE_FFE"),
    ("IfcBuildingElementProxy", "Handtag skåp1:Handtag skåp", ["Handtag, vitt"], None),
    ("IfcBuildingElementProxy", "Kök - Kyl frys-en dörr:Frys", [], "APPLIANCE"),
    ("IfcFlowTerminal", "Water_Heater-Gas-Bradford_White:25 Gallon", [], "MECH_EQUIP"),
    ("IfcBuildingElementProxy", "Air Conditioner-Outside Unit:33x24", [], "MECH_EQUIP"),
    ("IfcBuildingElementProxy", "A_Revit_Suv_5231", [], None),
    ("IfcBuildingElementProxy", "Serena bench with three drawers", ["Birch"], "LOOSE_FFE"),
    ("IfcWall", "Basic Wall:Ext - Riyadh stone on block 200", ["Stone", "Concrete Masonry Units"], "STONE_WALL"),
    ("IfcWall", "Basic Wall:Thermal Block 200", ["Thermal block"], "THERMAL_BLOCK_WALL"),
    ("IfcWall", "Basic Wall:بلوك عازل 20 سم", [], "THERMAL_BLOCK_WALL"),
    ("IfcWall", "Basic Wall:Block 200", ["Concrete Masonry Units"], "BLOCK_WALL"),
    ("IfcBuildingElementProxy", "M_Lavatory - Wall Mounted:485 mmx355 mm - Public", [], "SANITARY"),
    ("IfcBuildingElementProxy", "M_Water Closet - Flush Valve - Wall Mounted:Public", [], "SANITARY"),
    ("IfcBuildingElementProxy", "M_Cooling Tower - Closed Circuit - Counterflow - 177 kW", [], "MECH_EQUIP"),
    ("IfcBuildingElementProxy", "M_Base Cabinet-Single Door:500mm", ["Handle", "Wood"], "JOINERY"),
    ("IfcBuildingElementProxy", "M_Lighting and Appliance Panelboard - 208V MLO - Surface:400 A", [], "ELEC_PANEL"),
    ("IfcBuildingElementProxy", "M_Lighting and Appliance Panelboard - 480V MCB - Surface:100 A", [], "ELEC_DEVICE"),
    ("IfcSlab", "Floor:Hordi Slab 32cm", ["Concrete"], "RIBBED_SLAB"),
    ("IfcSlab", "Floor:بلاطة هوردي 30", [], "RIBBED_SLAB"),
    ("IfcBeam", "Concrete-Rectangular Beam:Tie Beam 30x60", ["Concrete"], "RC_FOOTING"),
    ("IfcSlab", "Floor:Interlock paving 80mm", [], "PAVING"),
    ("IfcSlab", "Floor:Marble flooring 30mm", ["Marble"], "FLOOR_FINISH"),
    ("IfcBuildingElementProxy", "Water Glass:Water Glass", ["Juice"], None),
    ("IfcBuildingElementProxy", "Wine Bottles:Wine Bottles", ["Water"], None),
    ("IfcBuildingElementProxy", "Walvit_Hung Bowl_604118 W:Walvit", ["Porcelain"], "SANITARY"),
    ("IfcFlowTerminal", "DC_Tankworks_PLM_5000L:5000L water tank", [], "MECH_EQUIP"),
])
def test_real_names_are_priced_sensibly(lib, cls, name, materials, recipe):
    el = {"ifc_class": cls, "kind": cls, "name": name, "type": name, "predefined": "",
          "materials": materials, "classification": [], "props": {}}
    assert lib.classify(el)[0] == recipe


@pytest.mark.parametrize("props,name,existing", [
    ({"phase": "Existing"}, "Floor:Generic 150", True),
    ({"phase": "New Construction"}, "Floor:Existing Floor", False),   # the phase wins over the name
    ({"phase": "New Construction", "demolished": "None"}, "Wall", False),
    ({"phase": "Existing", "demolished": "New Construction"}, "Wall", True),
    ({}, "Floor:Existing Floor_3rd floor", True),
    ({}, "Basic Wall:Block 200", False),
])
def test_existing_and_demolished_are_not_new_work(props, name, existing):
    assert is_existing({"name": name, "type": "", "props": props}) is existing


def test_floor_area_counts_each_level_once_and_not_the_roof(duplex, lib):
    els = copy.deepcopy(duplex)
    slab = _like(els, "IfcSlab", guid="roofslab", level="Roof", name="Floor:RC 200")
    slab["qty"]["footprint"] = 500.0
    parapet = _like(els, "IfcWall", guid="parapet", level="Roof")
    parapet["qty"]["height"] = 1.0
    est = estimate(els + [slab, parapet], "SA", lib, {})
    assert "Upper roof" not in est["summary"]["gfa_by_level"]


def test_floor_area_from_floor_build_ups_without_structure(lib):
    def el(guid, level, recipe_name, area):
        return {"guid": guid, "ifc_class": "IfcSlab", "level": level, "qty": {"footprint": area}}, recipe_name
    pairs = [el("a", "L1", "FLOOR_FINISH", 1000), el("b", "L2", "FLOOR_FINISH", 900),
             el("c", "L2", "RC_SLAB", 100)]
    els = [p[0] for p in pairs] + [{"guid": "d", "ifc_class": "IfcDoor", "level": "L1", "qty": {}},
                                   {"guid": "e", "ifc_class": "IfcDoor", "level": "L2", "qty": {}}]
    per = {p[0]["guid"]: {"recipe": p[1]} for p in pairs}
    total, levels = gross_floor_area(els, per)
    assert levels == {"L1": 1000, "L2": 900} and total == 1900


def test_generic_placeholder_types_are_reported(duplex, lib):
    els = copy.deepcopy(duplex)
    for e in els:
        if e["ifc_class"] in ("IfcWall", "IfcWallStandardCase"):
            e["name"] = e["type"] = "Basic Wall:Generic - 200mm"
    est = estimate(els, "SA", lib, {})
    g = est["checks"]["generic"]
    assert g["share"] > 0.15 and "Basic Wall:Generic - 200mm" in g["types"]
    assert any("generic" in r for r in est["accuracy"]["reasons"])


def test_rooms_with_the_same_shape_are_counted_once(duplex, lib):
    rooms = [e for e in duplex if e["ifc_class"] == "IfcSpace"]
    assert rooms
    base = estimate(duplex, "SA", lib, {})
    copy_room = copy.deepcopy(rooms[0])
    copy_room["guid"] = "copy-of-room"
    est = estimate(duplex + [copy_room], "SA", lib, {})
    assert abs(est["summary"]["direct"] - base["summary"]["direct"]) < 1
    assert any(d["kind"] == "same room shape" for d in est["checks"]["duplicates"])


def test_doors_priced_by_count_are_not_flagged(duplex, lib):
    els = copy.deepcopy(duplex)
    for e in els:
        if e["ifc_class"] == "IfcDoor":
            e["qty"]["check"] = 3.0      # volume taken from Revit: fine for a door priced by count
    assert estimate(els, "SA", lib, {})["checks"]["geometry_flagged"] == []


def test_every_name_has_an_arabic_translation(lib):
    ar = lib.translations["ar"]
    assert not [c for c in lib.work_items if f"work_item:{c}" not in ar]
    assert not [r for r in lib.groups if f"recipe:{r}" not in ar]
    assert not [w["trade"] for w in lib.work_items.values() if f'trade:{w["trade"]}' not in ar]
    from engine.estimate import CHECKLIST, SCOPE
    assert not [x[0] for x in SCOPE if f"scope:{x[0]}" not in ar]
    assert not [x[0] for x in CHECKLIST if f"check:{x[0]}" not in ar]
    assert not [g["nrm1"] for g in lib.groups.values() if f'nrm1:{g["nrm1"]}' not in ar]
    assert not [r for r in lib.resources if f"resource:{r}" not in ar]


def test_saudi_excel_boq_is_bilingual(duplex, lib):
    import io
    import openpyxl
    from engine.export import to_xlsx
    sa = openpyxl.load_workbook(io.BytesIO(to_xlsx("t", estimate(duplex, "SA", lib, {}))))["BOQ"]
    head = [c.value for c in sa[1]]
    assert "الوصف" in head and all(r[2] for r in sa.iter_rows(min_row=2, values_only=True) if r[0])
    gb = openpyxl.load_workbook(io.BytesIO(to_xlsx("t", estimate(duplex, "GB", lib, {}))))["BOQ"]
    assert "الوصف" not in [c.value for c in gb[1]]


def test_hordi_slab_concrete_is_ribs_and_topping_only(duplex, lib):
    els = copy.deepcopy(duplex)
    slab = next(e for e in els if e["ifc_class"] == "IfcSlab")
    slab["name"] = slab["type"] = "Floor:Hordi Slab 32cm"
    slab["qty"].update({"footprint": 100.0, "height": 0.32, "volume": 32.0})
    lines = [l for l in estimate(els, "SA", lib, {})["lines"] if l["guid"] == slab["guid"]]
    conc = sum(l["net_qty"] for l in lines if l["work_item"] == "CON-SLB")
    blocks = sum(l["net_qty"] for l in lines if l["work_item"] == "HORDI")
    assert 12 < conc < 14 and blocks == 100


def test_marble_floor_priced_as_marble_not_tiles(duplex, lib):
    els = copy.deepcopy(duplex)
    slab = next(e for e in els if e["ifc_class"] == "IfcSlab")
    slab["name"] = slab["type"] = "Floor:Marble flooring 30mm"
    slab["layers"] = [{"name": "Marble", "t": 0.03}]
    items = {l["work_item"] for l in estimate(els, "SA", lib, {})["lines"] if l["guid"] == slab["guid"]}
    assert "FLR-MRB" in items and "FLR-TIL" not in items


# ---- separate discipline models (architecture + structure + MEP) ---------------------------
def test_element_in_two_models_is_counted_once(duplex, lib):
    arch = [{**e, "model": "Main model"} for e in duplex]
    col = next(e for e in duplex if e["ifc_class"] in ("IfcColumn", "IfcWall", "IfcWallStandardCase"))
    twin = {**copy.deepcopy(col), "guid": "struct-copy", "model": "Structure"}
    base = estimate(arch, "SA", lib, {})
    est = estimate(arch + [twin], "SA", lib, {})
    dup = [d for d in est["checks"]["duplicates"] if d["kind"] == "in two models"]
    assert len(dup) == 1 and dup[0]["b"] == col["guid"]          # the structure model's copy is kept
    assert abs(est["summary"]["direct"] - base["summary"]["direct"]) < 0.02 * base["summary"]["direct"]


def test_levels_of_two_models_are_matched_by_height(duplex, lib):
    arch = [{**e, "model": "Main model"} for e in duplex]
    levels = sorted({(e["level"], e.get("level_elev") or 0) for e in duplex if e.get("level")}, key=lambda x: x[1])
    name, z = levels[-1]
    extra = {**copy.deepcopy(next(e for e in duplex if e["ifc_class"] == "IfcSlab")),
             "guid": "str-slab", "model": "Structure", "level": "L-top SSL", "level_elev": z - 0.05}
    extra["bbox"] = [x + 50 for x in extra["bbox"]]
    gfa = estimate(arch + [extra], "SA", lib, {})["summary"]["gfa_by_level"]
    assert "L-top SSL" not in gfa


def _excel_value(ws, ref, cache):
    """Evaluate the simple formulas of the priced BOQ (=A1*B1, =SUM(A1:A9), =ROUND(x,2), +)."""
    import re
    if ref in cache:
        return cache[ref]
    v = ws[ref].value
    if isinstance(v, str) and v.startswith("="):
        f = re.sub(r"SUM\(([A-Z]+)(\d+):([A-Z]+)(\d+)\)", lambda m: "(" + "+".join(
            f"{m.group(1)}{r}" for r in range(int(m.group(2)), int(m.group(4)) + 1)) + ")", v[1:])
        f = re.sub(r"\b([A-Z]{1,2})(\d+)\b", lambda m: repr(float(_excel_value(ws, m.group(0), cache))), f.replace("ROUND(", "round("))
        v = eval(f)  # only our own generated formulas
    elif not isinstance(v, (int, float)):
        v = 0.0
    cache[ref] = v
    return v


@pytest.mark.parametrize("region", ["SA", "GB"])
def test_priced_boq_formulas_add_up_to_the_estimate(duplex, lib, region):
    import io
    import openpyxl
    from engine.export import to_xlsx
    est = estimate(duplex, region, lib, {"allowances": [{"name": "MEP", "kind": "pct", "value": 25}]})
    ws = openpyxl.load_workbook(io.BytesIO(to_xlsx("t", est)))["Priced BOQ"]
    row = next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 2).value == "GRAND TOTAL")
    col = max(c for c in range(1, ws.max_column + 1) if ws.cell(row, c).value)
    from openpyxl.utils import get_column_letter
    total = _excel_value(ws, f"{get_column_letter(col)}{row}", {})
    assert abs(total - est["summary"]["total"]) < 1.0


def test_survey_coordinates_keep_full_precision(tmp_path):
    """Models exported with UTM survey coordinates (e.g. 2,700,000 m north) measure and display
    exactly like the same model at the origin."""
    import ifcopenshell
    from engine import overlaps
    src = SAMPLES / "Ifc2x3_Duplex_Architecture.ifc"
    m = ifcopenshell.open(str(src))
    for p in m.by_type("IfcLocalPlacement"):
        if p.PlacementRelTo is None:            # every top-level placement moves, as Revit exports it
            c = (list(p.RelativePlacement.Location.Coordinates) + [0, 0, 0])[:3]
            p.RelativePlacement.Location = m.createIfcCartesianPoint((c[0] + 650000, c[1] + 2700000, c[2]))
    far = tmp_path / "far.ifc"
    m.write(str(far))
    a, b = extract(str(src)), extract(str(far))
    qa = {e["guid"]: e["qty"] for e in a["elements"]}
    for e in b["elements"]:
        for k in ("volume", "side", "footprint"):
            assert abs(e["qty"].get(k, 0) - qa[e["guid"]].get(k, 0)) <= 0.01 * max(abs(qa[e["guid"]].get(k, 0)), 0.01)
    assert max(abs(v).max() for v, f in b["meshes"].values() if len(v)) < 2000      # stored near the origin
    assert abs(b["origin"][0] - 650000) <= 1000 and abs(b["origin"][2] + 2700000) <= 1000

    def overlap_total(d):
        found, _ = overlaps.find(d["elements"], d["meshes"])
        return sum(v for vals in found.values() for _, v in vals)
    va, vb = overlap_total(a), overlap_total(b)
    assert abs(va - vb) <= 0.02 * max(va, 1e-3)


def test_roof_slab_modelled_as_floor_gets_the_roof_build_up(duplex, lib):
    els = copy.deepcopy(duplex)
    top = max(e.get("level_elev") or 0 for e in els)
    base = copy.deepcopy(next(e for e in els if e["ifc_class"] == "IfcSlab"))
    base.update({"name": "Floor:RC Slab 200", "type": "Floor:RC Slab 200", "materials": ["Concrete"],
                 "layers": [{"name": "Concrete", "t": 0.2}], "classification": [], "props": {}})
    assert lib.classify(base)[0] == "RC_SLAB"
    roof = {**copy.deepcopy(base), "guid": "roof-slab", "level": "Upper roof", "level_elev": top + 3.0, "predefined": "FLOOR"}
    roof["bbox"] = [roof["bbox"][0], roof["bbox"][1], top + 2.8, roof["bbox"][3], roof["bbox"][4], top + 3.0]
    found = {**copy.deepcopy(base), "guid": "fdn-slab", "level": "Foundation", "level_elev": -2.0, "predefined": "FLOOR"}
    est = estimate(els + [roof, found], "SA", lib, {})
    items = lambda g: {l["work_item"] for l in est["lines"] if l["guid"] == g}
    assert {"ROF-WP", "ROF-INS"} <= items("roof-slab")
    assert "ROF-WP" not in items("fdn-slab")
    assert "Upper roof" not in est["summary"]["gfa_by_level"]


def test_external_wall_known_from_its_name(duplex, lib):
    from engine.estimate import is_external
    assert is_external({"name": "Basic Wall:Ext - Thermal Block 200", "type": ""})
    assert is_external({"name": "جدار خارجي 20", "type": ""})
    assert not is_external({"name": "Basic Wall:Int - Hollow Block 150", "type": ""})
    assert not is_external({"name": "Basic Wall:Ext - Block", "external": False})


def test_single_material_answers_has(duplex, lib):
    from engine.estimate import layers_of
    assert layers_of({"materials": ["Marble"]})[0]["name"] == "Marble"
    assert layers_of({"layers": [{"name": "Tile", "t": 0.01}], "materials": ["Marble"]})[0]["name"] == "Tile"


def test_saudi_villa_example_is_priced_like_a_saudi_estimator_would(lib):
    """The demo villa: hordi roof with the roof build-up, tie beams with bitumen, thermal block with
    render and lintels, marble and porcelain floors, Arabic wet rooms, roof not in the floor area."""
    els = extract(str(SAMPLES / "Saudi_Villa_Example.ifc"), with_mesh=False)["elements"]
    est = estimate(els, "SA", lib, {})
    boq = {b["work_item"]: b["qty"] for b in est["boq"]}
    for wi in ("HORDI", "BIT-COAT", "MAS-TBLK", "MAS-BLK", "FLR-MRB", "FLR-TIL", "ROF-WP", "ROF-INS",
               "ROF-TILE", "EXT-RND", "LINTEL", "WAL-TILE", "WPF-WET", "CON-FTG", "RBR"):
        assert boq.get(wi, 0) > 0, wi
    assert est["summary"]["gfa"] == pytest.approx(288, abs=1)
    assert not est["checks"]["unclassified"]
    assert 1200 < est["summary"]["per_m2"] < 2600          # shell and finishes, no MEP, SAR/m2


def test_crossing_beams_are_not_called_duplicates(lib):
    """Tie beams of one type crossing at columns overlap a little: a junction, not a duplicate."""
    els = extract(str(SAMPLES / "Saudi_Villa_Example.ifc"))
    from engine import overlaps
    found, _ = overlaps.find(els["elements"], els["meshes"])
    for e in els["elements"]:
        e["overlaps"] = found.get(e["guid"], [])
    est = estimate(els["elements"], "SA", lib, {})
    assert est["checks"]["overlaps"] and not est["checks"]["duplicates"]


# ---- independent verification against hand calculations (docs/VERIFICATION.md) -------------
@pytest.fixture(scope="module")
def villa(lib):
    from engine import overlaps
    d = extract(str(SAMPLES / "Saudi_Villa_Example.ifc"))
    found, _ = overlaps.find(d["elements"], d["meshes"])
    for e in d["elements"]:
        e["overlaps"] = found.get(e["guid"], [])
    return d, estimate(d["elements"], "SA", lib, {})


def _net(est, wi):
    return sum(l["net_qty"] for l in est["lines"] if l["work_item"] == wi)


def test_concrete_equals_the_exact_union_of_the_solids(villa):
    """Every overlap (column in tie beam, beams crossing) is counted once: the priced concrete equals
    the boolean union of all concrete solids (plus the hordi ribs and 70 mm topping)."""
    import manifold3d as m3
    import numpy as np
    d, est = villa
    rec = {g: p["recipe"] for g, p in est["per_element"].items()}
    solids = [m3.Manifold(m3.Mesh(vert_properties=np.asarray(d["meshes"][e["guid"]][0], np.float32),
                                  tri_verts=np.asarray(d["meshes"][e["guid"]][1], np.uint32).reshape(-1, 3)))
              for e in d["elements"]
              if rec.get(e["guid"]) in ("RC_FOOTING", "SLAB_ON_GRADE", "RC_SLAB", "RC_COLUMN", "STAIR_RC")]
    union = m3.Manifold.batch_boolean(solids, m3.OpType.Add).volume()
    hordi = 144 * (0.07 + 0.25 * 0.23)          # 12 x 12 m, 320 mm: topping + ribs at 23% of the rest
    conc = sum(_net(est, w) for w in ("CON-FTG", "CON-SOG", "CON-SLB", "CON-COL", "CON-STR", "CON-BEM"))
    assert conc == pytest.approx(union + hordi, rel=0.01)


def test_hand_calculated_quantities(villa):
    d, est = villa
    # 16 windows 1.5 x 1.5 and one door 0.9 x 2.1
    assert _net(est, "WIN") == pytest.approx(16 * 1.5 * 1.5, rel=0.01)
    # lintels: opening width + 2 x 150 mm bearing
    assert _net(est, "LINTEL") == pytest.approx(16 * 1.8 + 1.2, rel=0.01)
    # marble on half of each floor: 2 x 11.6 x 5.6
    assert _net(est, "FLR-MRB") == pytest.approx(2 * 11.6 * 5.6, rel=0.01)
    # slab soffits: first floor + hordi roof (12 x 12 each); stair soffit 3 x 1.2 x 1.2
    assert _net(est, "FRM-SLB") == pytest.approx(288 + 3 * 1.2 * 1.2, rel=0.01)
    # thermal block: 8 walls 12 x 3.3 less 2 windows each (and the door), less column zones; parapets 4 x 12 x 1.2
    walls = 8 * 12 * 3.3 - 16 * 2.25 - 0.9 * 2.1
    assert _net(est, "MAS-TBLK") == pytest.approx(walls + 4 * 12 * 1.2 - 8 * 3 * 0.3 * 3.3, rel=0.03)
    # roof waterproofing: roof area + 300 mm upstand on the perimeter
    assert _net(est, "ROF-WP") == pytest.approx(144 + 48 * 0.3, rel=0.01)
    # footings 9 x 2 x 2 x 0.6 plus tie beams 6 x 12 x 0.3 x 0.6, junctions counted once
    assert _net(est, "CON-FTG") == pytest.approx(21.6 + 12.96, rel=0.03)
    # excavation from ground level to the underside (+50 mm blinding), 300 mm working space each side:
    # 9 pads 2 x 2 at 2.10 m deep, 6 tie beams 12 x 0.3 at 0.60 m deep
    pad = (4 + 8 * 0.3 + 0.36) * (2.1 + 0.05)
    beam = (3.6 + 24.6 * 0.3 + 0.36) * (0.6 + 0.05)
    assert _net(est, "EARTH-EXC") == pytest.approx(9 * pad + 6 * beam, rel=0.02)
    # floor area: two floors of 12 x 12, roof not counted
    assert est["summary"]["gfa"] == pytest.approx(288, abs=0.5)


def test_room_finishes_match_hand_calculation(villa):
    d, est = villa
    room = {e["name"]: e["guid"] for e in d["elements"] if e["ifc_class"] == "IfcSpace"}
    q = lambda name, wi: sum(l["net_qty"] for l in est["lines"] if l["guid"] == room[name] and l["work_item"] == wi)
    # majlis 5.8 x 5.8 x 3.0 with two windows 1.5 x 1.5 and the 0.9 x 2.1 entrance door
    assert q("1 مجلس رجال", "PNT") == pytest.approx(23.2 * 3.0 - 2 * 2.25 - 0.9 * 2.1, abs=0.05)
    assert q("1 مجلس رجال", "FLR-SKRT") == pytest.approx(23.2 - 0.9, abs=0.05)
    assert q("1 مجلس رجال", "CLG-PNT") == pytest.approx(5.8 * 5.8, abs=0.05)
    # bathroom 2.8 x 2.8: full-height wall tiles less one window, waterproofing with 300 mm upturn
    assert q("4 حمام", "WAL-TILE") == pytest.approx(11.2 * 3.0 - 2.25, abs=0.05)
    assert q("4 حمام", "WPF-WET") == pytest.approx(7.84 + 11.2 * 0.3, abs=0.05)
    # kitchen splashback 600 mm on 40% of the perimeter, taken off the paint
    assert q("2 مطبخ", "WAL-TILE") == pytest.approx(23.2 * 0.4 * 0.6, abs=0.05)


def test_pipes_and_ducts_measured_along_their_run(tmp_path, lib):
    """A 10 m DN50 pipe at 45 degrees is 10 m of small pipe; a sloped DN100 drain is medium pipe;
    ducts: area = perimeter x length; insulation on chilled water and supply air only."""
    import subprocess
    import sys as _sys
    out = tmp_path / "mep.ifc"
    subprocess.run([_sys.executable, str(SAMPLES.parent / "tools" / "make_mep_check.py"), str(out)], check=True)
    els = extract(str(out), with_mesh=False)["elements"]
    est = estimate(els, "SA", lib, {})
    by_name = {e["name"]: e["guid"] for e in els}
    q = lambda n, wi: sum(l["net_qty"] for l in est["lines"] if l["guid"] == by_name[n] and l["work_item"] == wi)
    assert q("Pipe DN50 diagonal 45", "PIP-S") == pytest.approx(10, abs=0.05)
    assert q("Pipe DN50 straight", "PIP-S") == pytest.approx(10, abs=0.05)
    assert q("Pipe DN100 sloped drain", "PIP-M") == pytest.approx(12, abs=0.05)
    assert q("Pipe DN200 chilled riser", "PIP-L") == pytest.approx(9, abs=0.05)
    assert q("Pipe DN200 chilled riser", "PIP-INS") == pytest.approx(9, abs=0.05)
    assert q("Pipe DN50 straight", "PIP-INS") == 0
    for n in ("Duct 600x400 straight", "Duct 600x400 diagonal"):
        assert q(n, "DUCT") == pytest.approx(2 * (0.6 + 0.4) * 8, rel=0.04)       # + end caps
    assert q("Duct 600x400 straight", "DUCT-INS") > 0 and q("Duct 600x400 diagonal", "DUCT-INS") == 0


def test_floor_type_with_finish_layers_prices_the_concrete_too(duplex, lib):
    s = copy.deepcopy(next(e for e in duplex if e["ifc_class"] == "IfcSlab"))
    s.update({"guid": "layered", "name": "Floor:RC 200 + screed + porcelain", "type": "Floor:RC 200 + screed + porcelain",
              "materials": ["Concrete", "Screed", "Porcelain tile"], "classification": [], "props": {},
              "layers": [{"name": "Porcelain tile", "t": 0.02}, {"name": "Screed", "t": 0.05}, {"name": "Concrete", "t": 0.2}]})
    s["qty"].update({"footprint": 100.0, "volume": 27.0})
    assert lib.classify(s)[0] == "RC_SLAB"
    q = {l["work_item"]: l["net_qty"] for l in estimate([s], "SA", lib, {})["lines"]}
    assert q["CON-SLB"] == pytest.approx(20.0) and q["SCR"] == pytest.approx(100) and q["FLR-TIL"] == pytest.approx(100)
    # a finish-only build-up (no structural layer) stays a floor finish
    f = {**s, "layers": [{"name": "Porcelain tile", "t": 0.02}, {"name": "Screed", "t": 0.05}], "materials": ["Porcelain tile", "Screed"]}
    assert lib.classify(f)[0] == "FLOOR_FINISH"


@pytest.mark.parametrize("name,materials,recipe", [
    ("Basic Wall:Generic - 200mm", ["Concrete Masonry Units"], "BLOCK_WALL"),
    ("Basic Wall:RC 250 + gypsum plaster", ["Concrete, Cast-in-Place gray", "Gypsum Plaster"], "RC_WALL"),
    ("Basic Wall:Interior - 138mm Partition (1-hr)", ["Gypsum Wall Board", "Metal Stud Layer"], "DRYWALL"),
    ("Basic Wall:Concrete 200 + stone cladding", ["Concrete, Cast-in-Place gray", "Stone"], "RC_WALL"),
    ("Basic Wall:Foundation - 300mm Concrete", ["Concrete"], "RC_FOOTING"),
    ("Basic Wall:Ext Thermal Block 200 + Stone", ["Thermal block", "Stone"], "THERMAL_BLOCK_WALL"),
    ("Basic Wall:Block 200 + Riyadh stone", ["Concrete Block", "Stone"], "STONE_WALL"),
    ("Basic Wall:Block 200 Gypsum plaster both sides", ["Concrete Block", "Gypsum plaster"], "BLOCK_WALL"),
    ("Basic Wall:جدار خرساني 25 سم", ["خرسانة"], "RC_WALL"),
    ("Basic Wall:Exterior - Brick on CMU", ["Brick, Common", "Concrete Masonry Units"], "CAVITY_WALL"),
])
def test_typical_revit_wall_types(lib, name, materials, recipe):
    el = {"ifc_class": "IfcWall", "kind": "IfcWall", "name": name, "type": name, "predefined": "",
          "materials": materials, "classification": [], "props": {}}
    assert lib.classify(el)[0] == recipe


def test_stone_cladding_on_concrete_and_thermal_block_replaces_render(lib):
    from engine.estimate import evaluate
    import ast
    env = {"finish1": 10.0, "side": 10.0, "ext": 1.0}
    stone = [{"name": "Stone", "t": 0.03}]
    for recipe in ("RC_WALL", "THERMAL_BLOCK_WALL"):
        items = {i["work_item"]: evaluate(i["_expr"], env, stone) for i in lib.recipes[recipe]}
        assert items.get("STONE-CLAD") == 10 and not items.get("EXT-PNT") and not items.get("EXT-RND")


@pytest.mark.parametrize("cls,pre,name,materials,recipe", [
    ("IfcSlab", "FLOOR", "Floor:Insulation on Concrete 250", ["Concrete", "Insulation"], "RC_SLAB"),
    ("IfcSlab", "FLOOR", 'Floor:Wood Joist 10" - Wood Finish', ["Wood - Flooring", "Wood - Dimensional Lumber"], "TIMBER_FLOOR"),
    ("IfcSlab", "FLOOR", "Floor:Timber Suspended Floor", ["Timber"], "TIMBER_FLOOR"),
    ("IfcSlab", "BASESLAB", "Foundation Slab:150mm Foundation Slab", ["Concrete"], "SLAB_ON_GRADE"),
    ("IfcSlab", "FLOOR", "Floor:Tiles 20mm", ["Ceramic Tile"], "FLOOR_FINISH"),
    ("IfcBeam", "BEAM", "HSS-Hollow Structural Section:HSS6X4X.250", [], "STEEL_MEMBER"),
    ("IfcColumn", "COLUMN", "HSS-Hollow Structural Section-Column:HSS6X6X.500", ["Metal - Steel"], "STEEL_MEMBER"),
    ("IfcBeam", "BEAM", "K-Series Bar Joist-Rod Web:16K5", ["Metal - Steel"], "STEEL_MEMBER"),
    ("IfcBeam", "BEAM", "Precast-Inverted Tee:IT24LB", ["Concrete, Precast"], "RC_BEAM"),
])
def test_typical_revit_floor_beam_column_types(lib, cls, pre, name, materials, recipe):
    el = {"ifc_class": cls, "kind": cls, "name": name, "type": name, "predefined": pre, "materials": materials,
          "classification": [], "props": {}, "layers": [], "qty": {"height": 0.25}}
    assert lib.classify(el)[0] == recipe


def test_container_with_priced_parts_is_not_priced_again(duplex, lib):
    els = copy.deepcopy(duplex)
    wall = next(e for e in els if e["ifc_class"] in ("IfcWall", "IfcWallStandardCase"))
    part = {**copy.deepcopy(wall), "guid": "part-1", "assembly": wall["guid"]}
    base = estimate(copy.deepcopy(duplex), "SA", lib, {})["summary"]["direct"]
    est = estimate(els + [part], "SA", lib, {})
    assert est["per_element"].get(wall["guid"], {}).get("total", 0) == 0
    assert est["summary"]["direct"] == pytest.approx(base, rel=0.02)


@pytest.mark.parametrize("cls,name,recipe", [
    ("IfcBuildingElementProxy", "M_Split System - Indoor Unit - Wall Mounted:2.5 kW", "MECH_EQUIP"),
    ("IfcWasteTerminal", "Floor Drain 100mm", "DRAIN"),
    ("IfcBuildingElementProxy", "M_Fire Extinguisher Cabinet - Recessed", "FIRE_EQUIP"),
    ("IfcFireSuppressionTerminal", "Fire Hose Reel Cabinet", "FIRE_EQUIP"),
    ("IfcFireSuppressionTerminal", "M_Sprinkler - Pendent - Hosted", "SPRINKLER"),
    ("IfcBuildingElementProxy", "M_Fire Alarm Horn Strobe - Wall", "CONTROLS"),
    ("IfcFlowController", "M_Check Valve", "VALVE"),
    ("IfcBuildingElementProxy", "Water Meter", "VALVE"),
    ("IfcBuildingElementProxy", "CCTV Camera - Dome", "CONTROLS"),
    ("IfcCommunicationsAppliance", "Data Outlet - CAT6", "OUTLET"),
    ("IfcBuildingElementProxy", "M_Manhole 600x600", "MANHOLE"),
    ("IfcElectricGenerator", "Diesel Generator 250 kVA", "POWER_PLANT"),
    ("IfcSanitaryTerminal", "M_Water Closet - Flush Tank", "SANITARY"),
    ("IfcBuildingElementProxy", "Kitchen Cabinet Base 600", "JOINERY"),
])
def test_typical_revit_mep_families(lib, cls, name, recipe):
    el = {"ifc_class": cls, "kind": cls, "name": name, "type": name, "predefined": "", "materials": [],
          "classification": [], "props": {}, "qty": {"volume": 0.05}}
    assert lib.classify(el)[0] == recipe


@pytest.mark.parametrize("name,w,h,item,qty", [
    ("M_Single-Flush:0915 x 2134mm", 0.915, 2.134, "DOR", 1),
    ("M_Door-Overhead-Sectional:2400 x 2000mm", 4.0, 2.0, "DOR-L", 8.0),
    ("M_Double-Flush:1730 x 2134mm", 1.73, 2.134, "DOR-L", 1.73 * 2.134),
    ("Türelement 2-flg - Drehflügel - Glas", 2.0, 2.5, "DOR-G", 5.0),
    ("Interior_Door_EI60_Single", 0.9, 2.1, "DOR-F", 1),
    ("باب حريق 90×210", 0.9, 2.1, "DOR-F", 1),
])
def test_doors_priced_by_kind_and_size(lib, name, w, h, item, qty):
    el = {"guid": "d", "ifc_class": "IfcDoor", "kind": "IfcDoor", "name": name, "type": name, "predefined": "",
          "materials": [], "classification": [], "props": {}, "level": "L1", "openings": [],
          "qty": {"count": 1, "area": w * h, "ow": w, "oh": h, "volume": 0.1, "height": h, "length": w}}
    q = {l["work_item"]: l["net_qty"] for l in estimate([el], "SA", lib, {})["lines"]}
    assert q.get(item) == pytest.approx(qty, rel=0.01)
    assert sum(1 for k in q if k.startswith("DOR")) == 1


def test_rooms_exported_as_2d_outline_keep_their_finishes(tmp_path, lib):
    import subprocess
    import sys as _sys
    out = tmp_path / "flat.ifc"
    subprocess.run([_sys.executable, str(SAMPLES.parent / "tools" / "make_flat_rooms.py"), str(out)], check=True)
    els = extract(str(out), with_mesh=False)["elements"]
    rooms = {e["name"].split()[0]: e for e in els if e["ifc_class"] == "IfcSpace"}
    assert rooms["Bedroom"]["qty"]["floor_area"] == pytest.approx(20) and rooms["Bedroom"]["qty"]["perimeter"] == pytest.approx(18)
    assert rooms["Bathroom"]["qty"]["floor_area"] == pytest.approx(6) and rooms["Bathroom"]["qty"]["height_assumed"] == 1
    est = estimate(els, "SA", lib, {"finishes_from": "rooms"})
    q = lambda r, wi: sum(l["net_qty"] for l in est["lines"] if l["guid"] == rooms[r]["guid"] and l["work_item"] == wi)
    assert q("Bedroom", "PNT") == pytest.approx(18 * 3.0) and q("Bathroom", "WAL-TILE") == pytest.approx(10 * 3.0)
    assert any("2D outline" in a for a in est["assumptions"])


def test_modelled_rebar_weight_equals_diameter_times_length(lib):
    import math
    import ifcopenshell
    import ifcopenshell.util.unit as uu
    f = SAMPLES / "Ifc4_Revit_STR.ifc"
    m = ifcopenshell.open(str(f))
    sc = uu.calculate_unit_scale(m)
    by_hand = sum(math.pi * (b.NominalDiameter * sc / 2) ** 2 * b.BarLength * sc * 7850
                  for b in m.by_type("IfcReinforcingBar") if b.NominalDiameter and b.BarLength)
    est = estimate(extract(str(f), with_mesh=False)["elements"], "SA", lib, {"rebar_mode": "modeled"})
    tool = sum(l["net_qty"] for l in est["lines"] if l["recipe"] == "REBAR_MODELED")
    assert tool == pytest.approx(by_hand, rel=0.03)


@pytest.mark.parametrize("cls,name,recipe", [
    ("IfcColumn", "رقبة عمود 30×50", "RC_COLUMN"), ("IfcBeam", "ميدة 30×60", "RC_FOOTING"),
    ("IfcSlab", "بلاطة هوردي 32 سم", "RIBBED_SLAB"), ("IfcSlab", "بلاطة أرضية 15 سم", "SLAB_ON_GRADE"),
    ("IfcSlab", "لبشة 80 سم", "RC_FOOTING"), ("IfcWall", "جدار بلوك معزول 20 سم", "THERMAL_BLOCK_WALL"),
    ("IfcWall", "جدار طوب أحمر 20 سم", "BRICK_WALL"), ("IfcWall", "قاطع جبس بورد 10 سم", "DRYWALL"),
    ("IfcWall", "جدار حجر رياض 30 سم", "STONE_WALL"), ("IfcStair", "درج خرساني", "STAIR_RC"),
    ("IfcCovering", "سقف مستعار جبس", "CEILING"), ("IfcCovering", "أرضية سيراميك 60×60", "FLOOR_FINISH"),
    ("IfcBuildingElementProxy", "كرسي افرنجي", "SANITARY"), ("IfcBuildingElementProxy", "كرسي عربي", "SANITARY"),
    ("IfcBuildingElementProxy", "مغسلة", "SANITARY"), ("IfcBuildingElementProxy", "خزائن مطبخ", "JOINERY"),
    ("IfcBuildingElementProxy", "ثلاجة مطبخ", "APPLIANCE"), ("IfcBuildingElementProxy", "مصعد", "LIFT"),
    ("IfcBuildingElementProxy", "فيش كهرباء", "OUTLET"), ("IfcBuildingElementProxy", "لوحة كهرباء رئيسية", "ELEC_PANEL"),
    ("IfcBuildingElementProxy", "مكيف سبليت 24000", "MECH_EQUIP"), ("IfcBuildingElementProxy", "طفاية حريق", "FIRE_EQUIP"),
    ("IfcBuildingElementProxy", "سرير", "LOOSE_FFE"), ("IfcBuildingElementProxy", "شجرة", None),
    ("IfcBuildingElementProxy", "شطاف", None),
])
def test_arabic_type_names(lib, cls, name, recipe):
    el = {"ifc_class": cls, "kind": cls, "name": name, "type": name, "predefined": "", "materials": [],
          "classification": [], "props": {}, "layers": [], "qty": {"height": 0.2, "volume": 0.1}}
    assert lib.classify(el)[0] == recipe


def test_neck_columns_below_ground_get_bitumen(villa):
    d, est = villa
    cols = {e["guid"] for e in d["elements"] if e["ifc_class"] == "IfcColumn" and e["level"] == "Foundation"}
    upper = {e["guid"] for e in d["elements"] if e["ifc_class"] == "IfcColumn" and e["level"] != "Foundation"}
    bit = lambda gs: sum(l["net_qty"] for l in est["lines"] if l["guid"] in gs and l["work_item"] == "BIT-COAT")
    assert bit(cols) == pytest.approx(9 * 1.6 * 1.5, rel=0.01) and bit(upper) == 0
