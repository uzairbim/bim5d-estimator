"""Engine tests. Run:  python -m pytest -q"""
import ast
import copy
from pathlib import Path

import pytest

from engine.compare import compare
from engine.estimate import Library, check_formula, estimate, evaluate, group_key
from engine.export import to_xlsx
from engine.extract import extract
from engine.schedule import build

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture(scope="module")
def lib():
    return Library()


@pytest.fixture(scope="module")
def duplex():
    return extract(str(SAMPLES / "Ifc2x3_Duplex_Architecture.ifc"), with_mesh=False)["elements"]


@pytest.fixture(scope="module")
def house():
    return extract(str(SAMPLES / "Ifc4_SampleHouse.ifc"), with_mesh=True)


# ---- measuring ---------------------------------------------------------------
def test_slab_quantities_match_its_layers(house):
    slab = next(e for e in house["elements"] if "Floor-Grnd-Susp" in e["name"])
    q = slab["qty"]
    thickness = sum(l["t"] for l in slab["layers"])
    assert thickness == pytest.approx(0.47, abs=0.001)
    assert q["volume"] == pytest.approx(q["footprint"] * 0.47, rel=0.02)


def test_party_wall_matches_revit(duplex):
    # Exported as an open surface model with mixed winding; must still match Revit.
    wall = next(e for e in duplex if "Party Wall" in e["name"] and e["qty"]["length"] > 16)
    assert wall["qty"]["volume"] == pytest.approx(wall["authored"]["volume"], rel=0.06)


def test_quantities_agree_with_revit(duplex, lib):
    rec = estimate(duplex, "SA", lib)["checks"]["reconciliation"]
    assert rec["compared"] > 80 and rec["share"] >= 0.95


def test_no_volume_bigger_than_bounding_box(duplex):
    for e in duplex:
        q = e["qty"]
        if e["ifc_class"] == "IfcSpace":
            continue
        if not q["check"]:
            assert q["volume"] <= q["length"] * q["width"] * q["height"] * 1.05 + 1e-6 or e["ifc_class"] in (
                "IfcColumn", "IfcMember")


def test_meshes_are_packed_arrays(house):
    v, f = next(iter(house["meshes"].values()))
    assert v.dtype.name == "float32" and v.shape[1] == 3
    assert f.dtype.name == "uint32" and f.max() < len(v)


def test_levels_have_elevations(duplex):
    elevs = {e["level"]: e["level_elev"] for e in duplex}
    assert elevs["Level 2"] > elevs["Level 1"]


# ---- formulas ------------------------------------------------------------------
def _f(text, env=None, layers=None):
    return evaluate(ast.parse(text, mode="eval"), env or {}, layers or [])


def test_formula_basics():
    assert _f("volume*100", {"volume": 2}) == 200
    assert _f("length*(section<=0.065)", {"length": 5, "section": 0.05}) == 5
    assert _f("length*(section<=0.065)", {"length": 5, "section": 0.1}) == 0
    assert _f("a or b", {"a": 0, "b": 3}) == 3
    assert _f("x/0", {"x": 1}) == 0
    layers = [{"name": "Concrete, Precast", "t": 0.075}, {"name": "Screed", "t": 0.065}]
    assert _f('t("precast")', layers=layers) == 0.075
    assert _f('has("screed")', layers=layers) == 1


@pytest.mark.parametrize("bad", ["__import__('os')", "open('x')", "().__class__", "[1,2]", "lambda: 1"])
def test_formula_rejects_code(bad):
    with pytest.raises(Exception):
        check_formula(bad)


def test_every_recipe_formula_is_valid(lib):
    for items in lib.recipes.values():
        for i in items:
            check_formula(i["qty"])
            assert i["work_item"] in lib.work_items, i["work_item"]


def test_every_rule_points_to_a_recipe(lib):
    for r in lib.rules:
        assert r["recipe"] in lib.recipes or r["recipe"] == "EXCLUDE", r["recipe"]


def test_every_work_item_has_a_base_rate(lib):
    for code in lib.work_items:
        assert code in lib.base_rates, code


def test_every_recipe_has_a_group(lib):
    for name in lib.recipes:
        assert name in lib.groups, name


# ---- classification & pricing -------------------------------------------------------
def test_everything_in_duplex_is_priced(duplex, lib):
    est = estimate(duplex, "SA", lib)
    assert est["checks"]["unclassified"] == []
    assert est["summary"]["total"] > 0


def test_damp_proofing_is_not_a_roof(house, lib):
    slab = next(e for e in house["elements"] if "Floor-Grnd-Susp" in e["name"])
    assert lib.classify(slab)[0] == "SLAB_ON_GRADE"


def test_mapping_overrides_rule(duplex, lib):
    wall = next(e for e in duplex if "Brick on Block" in e["name"])
    key = group_key(wall)
    assert lib.classify(wall, {key: "RC_WALL"}) == ("RC_WALL", "mapping")
    assert lib.classify(wall, {key: "EXCLUDE"}) == (None, "excluded")


def test_summary_adds_up(duplex, lib):
    s = estimate(duplex, "SA", lib)["summary"]
    sub = (s["direct"] + s["allowances"] + s["prelims"] + s["contingency"] + s["overhead"]
           + s["profit"] + s["escalation"])
    assert s["total"] == pytest.approx(sub * (1 + s["tax_pct"] / 100), abs=1)
    assert s["tax_pct"] == 15  # Saudi VAT


def test_settings_override_markups(duplex, lib):
    a = estimate(duplex, "SA", lib)["summary"]
    b = estimate(duplex, "SA", lib, {"tax_pct": 0, "contingency_pct": 0})["summary"]
    assert b["tax"] == 0 and b["contingency"] == 0 and b["direct"] == a["direct"]


def test_region_changes_currency(duplex, lib):
    assert estimate(duplex, "AE", lib)["currency"] == "AED"
    assert estimate(duplex, "GB", lib)["summary"]["tax_pct"] == 20


def test_rebar_modes_do_not_double_count(lib):
    bar = {"guid": "r1", "ifc_class": "IfcReinforcingBar", "kind": "IfcReinforcingBar", "name": "Bar",
           "type": "", "level": "L1", "materials": [], "layers": [], "qty": {"volume": 0.001, "count": 1}}
    slab = {"guid": "s1", "ifc_class": "IfcSlab", "kind": "IfcSlab", "name": "Slab", "type": "",
            "level": "L1", "materials": [], "layers": [],
            "qty": {"volume": 1.0, "footprint": 5.0, "count": 1}}
    ratio = estimate([bar, slab], "US", lib, {"rebar_mode": "ratio"})
    modeled = estimate([bar, slab], "US", lib, {"rebar_mode": "modeled"})
    kg = lambda est: sum(l["net_qty"] for l in est["lines"] if l["work_item"] == "RBR")
    assert kg(ratio) == pytest.approx(100)        # 1 m3 x 100 kg/m3
    assert kg(modeled) == pytest.approx(7.85)     # the bar only


def test_mep_kinds_from_ifc2x3_types(lib):
    pipe = {"guid": "p", "ifc_class": "IfcFlowSegment", "kind": "IfcPipeSegment", "name": "Pipe Types:Standard",
            "type": "", "level": "L1", "materials": [], "layers": [],
            "qty": {"length": 10, "section": 0.1, "count": 1}}
    est = estimate([pipe], "US", lib)
    assert [l["work_item"] for l in est["lines"]] == ["PIP-M"]
    assert est["lines"][0]["net_qty"] == 10


# ---- schedule, compare, export ----------------------------------------------------
def test_schedule_cash_flow_reaches_total(duplex, lib):
    est = estimate(duplex, "SA", lib)
    s = build(duplex, est, 10)
    assert len(s["months"]) == 10
    assert s["months"][-1]["cumulative"] == pytest.approx(est["summary"]["total"], rel=1e-6)
    first = s["activities"][0]
    assert first["stage"] == "1 Substructure" and first["start"] == 0


def test_compare_finds_changes(duplex, lib):
    b = copy.deepcopy(duplex)[2:]
    b[0]["qty"]["side"] *= 1.5
    ea, eb = estimate(duplex, "SA", lib), estimate(b, "SA", lib)
    c = compare(duplex, b, ea, eb)
    assert c["counts"]["removed"] == 2 and c["counts"]["changed"] >= 1
    assert c["total_after"] < c["total_before"] or c["counts"]["changed"]


def test_excel_export(duplex, lib):
    from io import BytesIO
    from openpyxl import load_workbook
    est = estimate(duplex, "SA", lib)
    wb = load_workbook(BytesIO(to_xlsx("Test", est, build(duplex, est, 12))))
    assert {"Summary", "BOQ", "Element costs", "Elemental NRM1", "Cash flow", "Mapping"} <= set(wb.sheetnames)


# ---- estimator rules ---------------------------------------------------------------
def _el(guid, cls, name, qty, overlaps=(), openings=()):
    return {"guid": guid, "ifc_class": cls, "kind": cls, "name": name, "type": "", "level": "L1",
            "materials": [], "layers": [], "qty": {"count": 1, **qty},
            "overlaps": [list(o) for o in overlaps], "openings": list(openings)}


def test_column_through_slab_is_deducted_from_column(lib):
    col = _el("c", "IfcColumn", "Concrete column", {"volume": 1.0, "length": 3, "perimeter": 2}, [("s", 0.1)])
    slab = _el("s", "IfcSlab", "Slab", {"volume": 10.0, "footprint": 50}, [("c", 0.1)])
    est = estimate([col, slab], "US", lib)
    con = {l["guid"]: l["net_qty"] for l in est["lines"] if l["work_item"].startswith("CON-")}
    assert con["c"] == pytest.approx(0.9) and con["s"] == pytest.approx(10.0)
    assert est["checks"]["overlap_m3"] == pytest.approx(0.1)
    off = estimate([col, slab], "US", lib, {"deduct_overlaps": False})
    assert {l["guid"]: l["net_qty"] for l in off["lines"] if l["work_item"].startswith("CON-")}["c"] == 1.0


def test_steel_keeps_weight_concrete_is_reduced(lib):
    beam = _el("b", "IfcBeam", "Steel beam IPE300", {"volume": 0.01, "length": 6}, [("s", 0.005)])
    slab = _el("s", "IfcSlab", "Slab", {"volume": 10.0, "footprint": 50}, [("b", 0.005)])
    est = estimate([beam, slab], "US", lib)
    q = {l["work_item"]: l["net_qty"] for l in est["lines"]}
    assert q["STL-STR"] == pytest.approx(78.5 * 1.1)    # full steel weight + 10% connections (no plates modelled)
    assert q["CON-SLB"] == pytest.approx(9.995)


def test_small_openings_not_deducted(lib):
    wall = _el("w", "IfcWall", "Block wall 200", {"volume": 2.0, "side": 10.0}, openings=(0.3, 2.0))
    est = estimate([wall], "US", lib)
    blk = next(l for l in est["lines"] if l["work_item"] == "MAS-BLK")
    assert blk["net_qty"] == pytest.approx(10.3)          # 0.3 m2 opening added back, 2.0 stays deducted
    est = estimate([wall], "US", lib, {"min_deduct_m2": 0})
    assert next(l for l in est["lines"] if l["work_item"] == "MAS-BLK")["net_qty"] == pytest.approx(10.0)


def test_accuracy_class_reflects_sample_rates_and_scope(duplex, lib):
    a = estimate(duplex, "GLOBAL", lib)["accuracy"]
    assert a["class"] == 5 and a["low"] < a["high"]       # prices converted from US levels
    sa = estimate(duplex, "SA", lib)["accuracy"]
    assert sa["class"] == 4 and sa["assumed_price_share"] > 0.9   # assumed indicative prices


def test_assumed_prices_are_not_counted_as_yours(lib):
    d = lib.rate_detail("SA", "MAS-BLK")
    assert d["local_share"] == 0 and d["assumed_share"] > 0.99
    assert all(b["kind"] == "assumed" for b in d["build"])
    # a price the user confirms counts as theirs
    lib.prices["SA"] = dict(lib.prices["SA"])
    lib.prices["SA"]["M-BLK"] = {"price": "3.2", "source": "supplier quote"}
    lib._cache.clear()
    d2 = lib.rate_detail("SA", "MAS-BLK")
    assert d2["local_share"] > 0.5
    lib.__init__()


def test_scope_gap_suggests_mep_allowance(duplex, lib):
    est = estimate(duplex, "SA", lib)
    mep = next(s for s in est["scope"] if s["name"] == "MEP services")
    assert not mep["present"] and mep["suggest"]["value"] == 25
    with_allow = estimate(duplex, "SA", lib, {"allowances": [{"name": "MEP services allowance", "kind": "pct", "value": 25}]})
    assert with_allow["summary"]["allowances"] == pytest.approx(with_allow["summary"]["direct"] * 0.25, rel=1e-6)


def test_rooms_give_finishes_without_double_counting(duplex, lib):
    est = estimate(duplex, "SA", lib)
    assert est["rooms_on"] and est["rooms"] >= 10
    codes = {b["work_item"] for b in est["boq"]}
    assert {"FLR-SKRT", "CLG-PNT", "WAL-TILE", "WPF-WET", "LINTEL", "SILL", "SEALANT"} <= codes
    # with rooms on, walls do not carry paint; with walls only, rooms are not priced
    walls = estimate(duplex, "SA", lib, {"finishes_from": "walls"})
    assert not walls["rooms_on"]
    assert not any(l["recipe"].startswith("ROOM_") for l in walls["lines"])
    room_paint = sum(l["net_qty"] for l in est["lines"] if l["work_item"] == "PNT" and l["recipe"].startswith("ROOM_"))
    wall_paint = sum(l["net_qty"] for l in est["lines"] if l["work_item"] == "PNT" and not l["recipe"].startswith("ROOM_"))
    assert room_paint > 0 and wall_paint == 0


def test_bathroom_gets_tiles_and_waterproofing(duplex, lib):
    est = estimate(duplex, "SA", lib)
    bath = next(e for e in duplex if e["ifc_class"] == "IfcSpace" and "Bathroom" in e["name"])
    items = {l["work_item"] for l in est["lines"] if l["guid"] == bath["guid"]}
    assert {"WAL-TILE", "WPF-WET"} <= items and "PNT" not in items


def test_room_perimeter_is_plausible(duplex):
    import math
    for r in (e for e in duplex if e["ifc_class"] == "IfcSpace"):
        q = r["qty"]
        if q["floor_area"] > 1:
            assert q["perimeter"] >= 2 * math.sqrt(math.pi * q["floor_area"]) * 0.97


def test_is1200_one_face_rule(lib):
    wall = _el("w", "IfcWall", "Block wall 200", {"volume": 2.0, "side": 10.0}, openings=([2.0, 1.0, 2.0, "window"],))
    nrm = estimate([wall], "US", lib, {"standard": "NRM2", "finishes_from": "walls"})
    ind = estimate([wall], "US", lib, {"standard": "IS1200", "finishes_from": "walls"})
    pls = lambda e: next(l["net_qty"] for l in e["lines"] if l["work_item"] == "PLS")
    assert pls(nrm) == pytest.approx(20.0)        # both faces, opening deducted twice
    assert pls(ind) == pytest.approx(22.0)        # 0.5-3 m2 opening deducted from one face only


def test_rate_built_up_from_local_prices(lib):
    d = lib.rate_detail("GLOBAL", "CON-SLB")
    assert d["method"] == "built-up" and d["local_share"] == 0
    total = d["material"] + d["labour"] + d["equipment"]
    expect = sum(float(n["qty"]) * float(lib.resources[n["resource"]]["price_usd"]) for n in lib.norms["CON-SLB"])
    assert total == pytest.approx(expect)
    lib.prices["GLOBAL"] = {"M-RMC": {"price": "200"}}
    lib._cache.clear()
    d2 = lib.rate_detail("GLOBAL", "CON-SLB")
    assert d2["material"] == pytest.approx(200) and 0 < d2["local_share"] < 1
    lib.prices["GLOBAL"] = {}
    lib._cache.clear()


def test_every_work_item_has_norms(lib):
    for code in lib.work_items:
        assert lib.norms.get(code), code
        for n in lib.norms[code]:
            assert n["resource"] in lib.resources, n["resource"]


def test_manual_item_and_checklist(duplex, lib):
    est = estimate(duplex, "SA", lib, {"manual_items": [{"description": "Boundary wall", "qty": 10, "rate": 100}]})
    man = [l for l in est["lines"] if l["recipe"] == "MANUAL"]
    assert man and man[0]["amount"] == pytest.approx(1000)
    names = {c["name"]: c["status"] for c in est["checklist"]}
    assert names["Skirting"] == "priced" and names["Testing and commissioning of services"] == "missing"


def test_countries_list():
    import json
    from engine.estimate import DATA
    c = json.loads((DATA / "countries.json").read_text(encoding="utf-8"))
    assert len(c) > 200 and next(x for x in c if x["code"] == "SA")["currency"] == "SAR"


def test_loose_furniture_excluded_by_default(duplex, lib):
    est = estimate(duplex, "SA", lib)
    assert est["summary"]["ffe_count"] > 0 and est["summary"]["ffe_outside"] > 0
    assert not any(l["work_item"] == "FFE" for l in est["lines"])
    inc = estimate(duplex, "SA", lib, {"include_loose_ffe": True})
    assert any(l["work_item"] == "FFE" for l in inc["lines"])
    # built-in joinery is always priced
    assert any(l["work_item"] == "JOIN" for l in est["lines"])


def test_small_vs_large_mechanical_equipment(lib):
    rad = _el("r", "IfcEnergyConversionDevice", "M_Radiator - Hosted", {"volume": 0.05, "count": 1})
    rad["kind"] = "IfcSpaceHeater"
    boiler = _el("b", "IfcEnergyConversionDevice", "Hot Water Boiler", {"volume": 1.2, "count": 1})
    boiler["kind"] = "IfcBoiler"
    est = estimate([rad, boiler], "SA", lib)
    items = {l["guid"]: l["work_item"] for l in est["lines"]}
    assert items == {"r": "MECH-SM", "b": "MECH-EQ"}


def test_no_room_finishes_in_models_without_walls(lib):
    room = {"guid": "s", "ifc_class": "IfcSpace", "kind": "IfcSpace", "name": "Office", "type": "Office",
            "level": "L1", "materials": [], "layers": [], "is_room": True, "room_modeled": [],
            "qty": {"floor_area": 20, "perimeter": 18, "height": 3, "wall_area": 50, "skirting": 17, "count": 1}}
    rooms = [dict(room, guid=f"s{i}") for i in range(4)]
    assert not estimate(rooms, "SA", lib)["rooms_on"]


def test_resources_add_up_to_measured_work(duplex, lib):
    est = estimate(duplex, "SA", lib)
    assert sum(r["cost"] for r in est["resources"]) == pytest.approx(est["summary"]["direct"], rel=0.01)


def test_solar_and_taps(lib):
    pv = _el("p", "IfcBuildingElementProxy", "Photovoltaic-Panel-SolarWorld", {"count": 1, "volume": 0.02})
    tap = _el("t", "IfcFlowTerminal", "Faucet-8inch_Reach-Kohler", {"count": 1})
    est = estimate([pv, tap], "SA", lib)
    assert [l["work_item"] for l in est["lines"]] == ["SOLAR"]
    assert "t" in est["checks"]["excluded"]


def test_friendly_errors():
    from engine.storage import friendly_error
    assert "Export it again" in friendly_error(Exception("Unable to parse IFC SPF header"))
    assert "3D building elements" in friendly_error(ValueError("NO_ELEMENTS"))


def test_adjustment_factor(duplex, lib):
    wall = next(e for e in duplex if "Brick on Block" in e["name"])
    key = group_key(wall)
    base = estimate(duplex, "SA", lib)
    adj = estimate(duplex, "SA", lib, {"adjustments": {key: {"factor": 1.1, "reason": "test"}}})
    b = sum(l["net_qty"] for l in base["lines"] if l["guid"] == wall["guid"] and l["work_item"] == "MAS-BRK")
    a = sum(l["net_qty"] for l in adj["lines"] if l["guid"] == wall["guid"] and l["work_item"] == "MAS-BRK")
    assert a == pytest.approx(b * 1.1, rel=1e-3)


def test_data_files_are_well_formed():
    """Every row of every data table has the header's number of columns (a stray comma in a
    description or a regex like {0,15} silently shifts the columns), and every recipe and rule
    refers to things that exist."""
    import csv
    from pathlib import Path
    from engine.estimate import Library
    data = Path(__file__).resolve().parent.parent / "data"
    for f in data.glob("*.csv"):
        rows = list(csv.reader(f.open(encoding="utf-8")))
        bad = [i + 1 for i, r in enumerate(rows) if r and len(r) != len(rows[0])]
        assert not bad, f"{f.name}: rows {bad[:10]} have the wrong number of columns"
    lib = Library()
    recipes = set(lib.recipes) | {"EXCLUDE"}
    assert not {r["recipe"] for r in lib.rules} - recipes
    for name, lines in lib.recipes.items():
        for line in lines:
            assert line["work_item"] in lib.work_items, (name, line["work_item"])
    used = {line["work_item"] for lines in lib.recipes.values() for line in lines}
    assert not [w for w in used if sum(lib.rate("SA", w)[:3]) == 0], "work items without a Saudi rate"
    groups = {r["recipe"] for r in csv.DictReader((data / "recipe_groups.csv").open(encoding="utf-8"))}
    assert not set(lib.recipes) - groups, "recipes without a cost group"
    tr = {(r["kind"], r["code"]) for r in csv.DictReader((data / "translations.csv").open(encoding="utf-8"))}
    assert not [w for w in used if ("work_item", w) not in tr], "work items without an Arabic name"
    assert not [r for r in lib.recipes if ("recipe", r) not in tr], "recipes without an Arabic name"


def test_codes_are_unique():
    """A resource, work item or translation code defined twice silently replaces the first one
    (a new 'wire' resource once changed the rebar tying-wire price)."""
    import csv
    from collections import Counter
    from pathlib import Path
    data = Path(__file__).resolve().parent.parent / "data"
    for f, cols in [("resources.csv", ("code",)), ("work_items.csv", ("code",)),
                    ("recipe_groups.csv", ("recipe",)), ("translations.csv", ("kind", "code")),
                    ("rates/base_usd.csv", ("work_item",))]:
        rows = list(csv.DictReader((data / f).open(encoding="utf-8")))
        dup = [k for k, n in Counter(tuple(r[c] for c in cols) for r in rows).items() if n > 1]
        assert not dup, f"{f}: {dup}"
