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
    assert "Roof" not in est["summary"]["gfa_by_level"]


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
