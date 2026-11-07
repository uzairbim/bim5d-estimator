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


def test_wall_volume_is_face_times_thickness(duplex):
    wall = next(e for e in duplex if "Party Wall" in e["name"] and e["qty"]["length"] > 16)
    q = wall["qty"]
    assert 0.1 < q["volume"] / q["side"] < 0.4   # thickness in metres


def test_no_volume_bigger_than_bounding_box(duplex):
    for e in duplex:
        q = e["qty"]
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
    sub = s["direct"] + s["contingency"] + s["overhead"] + s["profit"]
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
