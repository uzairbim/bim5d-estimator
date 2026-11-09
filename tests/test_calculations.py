"""Arithmetic and rules checked by hand: openings by measurement standard, rate build-up, mark-ups,
allowances, manual items, cash flow, revision comparison, rate packs."""
import copy
import math
from pathlib import Path

import pytest

from engine.compare import compare
from engine.estimate import Library, estimate
from engine.extract import extract
from engine.schedule import build

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture(scope="module")
def lib():
    return Library()


def _wall(openings):
    """A 10 x 3 m block wall, 200 mm, internal, with the given openings [area, w, h, kind]."""
    return {"guid": "w", "ifc_class": "IfcWall", "kind": "IfcWall", "name": "Basic Wall:Block 200",
            "type": "Basic Wall:Block 200", "predefined": "", "materials": ["Concrete Block"], "layers": [],
            "classification": [], "props": {}, "level": "L1", "level_elev": 0.0, "external": False,
            "openings": openings, "bbox": [0, 0, 0, 10, 0.2, 3],
            "qty": {"count": 1, "volume": 6 - 0.2 * sum(o[0] for o in openings), "side": 30 - sum(o[0] for o in openings),
                    "area": 30, "footprint": 2, "height": 3, "length": 10, "width": 0.2, "perimeter": 20.4,
                    "surface": 60, "section": 3, "check": 0}}


def _q(est, wi):
    return sum(l["net_qty"] for l in est["lines"] if l["work_item"] == wi)


# openings: one of 0.3 m2 (small), one of 1.5 m2 (medium), one of 4 m2 (large)
OPENINGS = [[0.3, 0.5, 0.6, "void"], [1.5, 1.0, 1.5, "window"], [4.0, 2.0, 2.0, "door"]]


@pytest.mark.parametrize("standard,masonry,plaster", [
    # NRM2 / POMI: openings up to 0.5 m2 not deducted, from masonry or finishes (each face)
    ("NRM2", 30 - 1.5 - 4.0, 2 * (30 - 1.5 - 4.0)),
    ("POMI", 30 - 1.5 - 4.0, 2 * (30 - 1.5 - 4.0)),
    # IS 1200: masonry deducts above 0.1 m2; plaster: up to 0.5 none, 0.5-3 one face, above 3 both faces
    ("IS1200", 30 - 0.3 - 1.5 - 4.0, 2 * 30 - 1.5 - 2 * 4.0),
    # exact: everything deducted
    ("EXACT", 30 - 0.3 - 1.5 - 4.0, 2 * (30 - 0.3 - 1.5 - 4.0)),
])
def test_openings_by_measurement_standard(lib, standard, masonry, plaster):
    est = estimate([_wall(OPENINGS)], "SA", lib, {"standard": standard, "finishes_from": "walls"})
    assert _q(est, "MAS-BLK") == pytest.approx(masonry, abs=0.01)
    assert _q(est, "PLS") == pytest.approx(plaster, abs=0.01)


def test_rate_is_the_sum_of_norms_times_prices(lib):
    for wi in ("MAS-BLK", "CON-SLB", "PLS", "RBR", "FLR-TIL", "ROF-WP"):
        d = lib.rate_detail("SA", wi)
        total = d["material"] + d["labour"] + d["equipment"]
        by_hand = sum(float(n["qty"]) * lib.resource_price("SA", n["resource"])[0]
                      for n in lib.norms[wi])
        assert total == pytest.approx(by_hand, rel=1e-6), wi


def test_your_price_and_fixed_rate_override(lib):
    l2 = Library()
    l2.prices.setdefault("SA", {})["M-BLK"] = {"price": 10.0, "source": "my supplier", "date": "2026-11"}
    l2._cache.clear()
    d = l2.rate_detail("SA", "MAS-BLK")
    assert d["material"] == pytest.approx(lib.rate_detail("SA", "MAS-BLK")["material"]
                                          + 12.5 * (10.0 - lib.resource_price("SA", "M-BLK")[0]), rel=1e-6)
    l2.local_rates.setdefault("SA", {})["MAS-BLK"] = {"work_item": "MAS-BLK", "material": 50, "labour": 20,
                                                      "equipment": 0, "source": "quote"}
    l2._cache.clear()
    d = l2.rate_detail("SA", "MAS-BLK")
    assert d["material"] + d["labour"] + d["equipment"] == pytest.approx(70)


def test_mark_up_chain_and_allowances_by_hand(lib):
    settings = {"prelims_pct": 10, "contingency_pct": 5, "overhead_pct": 8, "profit_pct": 7, "escalation_pct": 2,
                "tax_pct": 15, "gfa_m2": 200,
                "allowances": [{"name": "MEP", "kind": "pct", "value": 20}, {"name": "Ext", "kind": "lump", "value": 1000},
                               {"name": "Fit", "kind": "per_m2", "value": 10}],
                "manual_items": [{"description": "Boundary wall", "work_item": "MAS-BLK", "qty": 100},
                                 {"description": "Gate", "qty": 1, "unit": "nr", "rate": 5000}]}
    est = estimate([_wall([])], "SA", lib, settings)
    s = est["summary"]
    measured = sum(l["amount"] for l in est["lines"])
    assert s["direct"] == pytest.approx(measured, abs=0.05)
    gate = [l for l in est["lines"] if l.get("description") == "Gate"]
    assert gate and gate[0]["amount"] == pytest.approx(5000)
    wall = [l for l in est["lines"] if l["work_item"] == "MAS-BLK" and l["recipe"] == "MANUAL"]
    d = lib.rate_detail("SA", "MAS-BLK")
    assert wall[0]["qty"] == pytest.approx(100)
    assert wall[0]["amount"] == pytest.approx(100 * (d["material"] + d["labour"] + d["equipment"]), rel=1e-3)
    allow = s["direct"] * 0.20 + 1000 + 10 * 200
    assert s["allowances"] == pytest.approx(allow, abs=0.05)
    c = s["direct"] + allow
    p = c * 0.10
    cg = (c + p) * 0.05
    oh = (c + p + cg) * 0.08
    pr = (c + p + cg + oh) * 0.07
    es = (c + p + cg + oh + pr) * 0.02
    sub = c + p + cg + oh + pr + es
    assert s["total"] == pytest.approx(sub * 1.15, abs=0.5)
    assert s["per_m2"] == pytest.approx(s["total"] / 200, abs=0.01)


def test_cash_flow_adds_up_to_the_total(lib):
    els = extract(str(SAMPLES / "Saudi_Villa_Example.ifc"), with_mesh=False)["elements"]
    est = estimate(els, "SA", lib, {})
    sched = build(els, est, 10)
    rows = sched["cashflow"] if "cashflow" in sched else sched["months"]
    assert rows[-1]["cumulative"] == pytest.approx(est["summary"]["total"], rel=0.002)
    assert all(b["cumulative"] >= a["cumulative"] for a, b in zip(rows, rows[1:]))
    for months in (3, 6, 12, 18, 24, 36, 7.5):  # a 12-month job has 12 months of cash flow, not 13
        assert len(build(els, est, months)["months"]) == math.ceil(months)
    stage = lambda g: est["per_element"][g]["stage"] if "stage" in est["per_element"][g] else None
    # substructure starts before the roof
    acts = sched.get("activities") or []
    if acts:
        first = {a["stage"]: a["start"] for a in acts}
        assert first.get("1 Substructure", 0) <= min(v for k, v in first.items() if k != "1 Substructure")


def test_revision_comparison_finds_the_known_changes(lib):
    a = extract(str(SAMPLES / "Ifc2x3_Duplex_Architecture.ifc"), with_mesh=False)["elements"]
    b = extract(str(SAMPLES / "Ifc2x3_Duplex_Architecture_Rev2.ifc"), with_mesh=False)["elements"]
    ea, eb = estimate(a, "SA", lib, {}), estimate(b, "SA", lib, {})
    c = compare(a, b, ea, eb)
    removed = [r for r in c["rows"] if r["status"] == "removed"]
    added = [r for r in c["rows"] if r["status"] == "added"]
    kinds = sorted({next(e["ifc_class"] for e in a if e["guid"] == r["guid"]) for r in removed})
    # Rev 2: 2 doors and 4 cabinets removed, 1 wall added, ground slab made thicker
    assert c["counts"]["removed"] == 6 and "IfcDoor" in kinds
    assert c["counts"]["added"] == 1 and next(e for e in b if e["guid"] == added[0]["guid"])["ifc_class"].startswith("IfcWall")
    assert c["total_after"] - c["total_before"] == pytest.approx(eb["summary"]["total"] - ea["summary"]["total"], abs=1)
    assert sum(t["delta"] for t in c["by_trade"]) == pytest.approx(eb["summary"]["direct"] - ea["summary"]["direct"], abs=1)


def test_rate_pack_round_trip(tmp_path, monkeypatch):
    from engine import regions
    lib = Library()
    pack = regions.export_pack("SA", "tester")
    assert {p["resource"] for p in pack["prices"]} == set(lib.prices["SA"])
    # importing under a new code creates the same prices
    monkeypatch.setattr(regions, "_prices_path", lambda r: tmp_path / f"{r}.csv")
    saved = {}
    monkeypatch.setattr(regions, "create_region", lambda code, values=None: (code, values))
    n = regions.save_prices("ZZ", pack["prices"], lib)
    assert n == len(pack["prices"])
    rows = (tmp_path / "ZZ.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) == n + 1


def test_assumptions_come_with_templates_for_translation(lib):
    els = extract(SAMPLES / "Saudi_Villa_Example.ifc")["elements"]
    e = estimate(els, "SA", lib, {"assumptions": ["Soil report by others"]})
    assert len(e["assumptions"]) == len(e["assumptions_t"])
    for text, (tpl, vals) in zip(e["assumptions"], e["assumptions_t"]):
        assert tpl.format(**vals) == text
    assert e["assumptions"][-1] == "Soil report by others"
    assert any("VAT at 15% is included" in a for a in e["assumptions"])


def _room(mods, covers):
    return {"guid": "r", "ifc_class": "IfcSpace", "kind": "IfcSpace", "name": "Bathroom", "type": "Bathroom",
            "predefined": "", "materials": [], "classification": [], "props": {}, "layers": [], "level": "L1",
            "level_elev": 0, "bbox": [0, 0, 0, 3, 2, 3], "is_room": True, "room_doors": [[0.8, 2.1]],
            "room_windows": [], "room_modeled": mods, "room_wall_covers": covers,
            "qty": {"count": 1, "floor_area": 6, "perimeter": 10, "height": 3, "volume": 18, "footprint": 6,
                    "wall_area": 30 - 0.8 * 2.1, "skirting": 9.2}}


def _cover(guid, name, area, bbox):
    flat = bbox[5] - bbox[2] < 0.1
    return {"guid": guid, "ifc_class": "IfcCovering", "kind": "IfcCovering", "name": name, "type": name,
            "predefined": "", "materials": [], "classification": [], "props": {}, "layers": [], "level": "L1",
            "level_elev": 0, "bbox": bbox, "qty": {"count": 1, "area": area, "footprint": area if flat else 0.03,
                                                   "height": 0.02 if flat else 3, "volume": area * 0.02}}


def test_modelled_coverings_are_not_counted_twice_in_rooms(lib):
    """A bathroom gets floor tiles and wall tiles from the room, unless they are modelled as coverings:
    a marble floor covering replaces the room's floor tiles; 20 m² of modelled wall tiles leave
    28.32 - 20 = 8.32 m² for the room."""
    def qty(els):
        est = estimate(els, "SA", lib, {"finishes_from": "rooms"})
        out = {}
        for l in est["lines"]:
            out[(l["guid"], l["work_item"])] = out.get((l["guid"], l["work_item"]), 0) + l["net_qty"]
        return out
    alone = qty([_room([], [])])
    assert alone[("r", "FLR-TIL")] == pytest.approx(6) and alone[("r", "WAL-TILE")] == pytest.approx(28.32)
    both = qty([_room(["f"], ["w"]), _cover("f", "رخام", 6, [0, 0, 0, 3, 2, 0.02]),
                _cover("w", "Wall tiles", 20, [0, 0, 0, 3, 0.01, 3])])
    assert ("r", "FLR-TIL") not in both and both[("f", "FLR-MRB")] == pytest.approx(6)
    assert both[("r", "WAL-TILE")] == pytest.approx(8.32) and both[("w", "WAL-TILE")] == pytest.approx(20)


def test_arabic_workbook_has_arabic_assumptions(lib):
    import io
    from openpyxl import load_workbook
    from engine.export import to_xlsx
    els = extract(str(SAMPLES / "Saudi_Villa_Example.ifc"), with_mesh=False)["elements"]
    est = estimate(els, "SA", lib, {})
    data = to_xlsx("Villa", est, None, "ar")
    ws = load_workbook(io.BytesIO(data if isinstance(data, bytes) else data.getvalue()))["Assumptions"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    vat = [r for r in rows if r[1] and "VAT at 15% is included" in r[1]][0]
    assert vat[2] == "ضريبة القيمة المضافة بنسبة 15% مضمّنة في الإجمالي."
    assert all(r[2] for r in rows if r[0])      # every assumption and default exclusion is in Arabic


def test_connections_per_point_only_when_not_modelled(lib):
    """A WC and a socket get their pipe / wiring connections when the model has no pipes / cables,
    and none when pipes and cables are modelled (they are measured then)."""
    def el(guid, cls, name, **q):
        return {"guid": guid, "ifc_class": cls, "kind": cls, "name": name, "type": name, "predefined": "",
                "materials": [], "classification": [], "props": {}, "layers": [], "level": "L1",
                "level_elev": 0, "bbox": [0, 0, 0, 1, 1, 1], "qty": {"count": 1, **q}}
    base = [el("wc", "IfcSanitaryTerminal", "WC"), el("s", "IfcOutlet", "Socket")]
    extra = [el("p", "IfcPipeSegment", "Pipe", length=5, section=0.05, volume=0.01),
             el("c", "IfcCableSegment", "Cable", length=5, section=0.01, volume=0.001)]
    def items(els):
        return {l["work_item"] for l in estimate(els, "SA", lib, {})["lines"]}
    assert {"PLB-PT", "WIRE-PT"} <= items(base)
    assert not {"PLB-PT", "WIRE-PT"} & items(base + extra)


def test_modelled_skirting_is_not_counted_twice(lib):
    room = _room([], ["k"])
    room["name"] = room["type"] = "Bedroom"
    skirt = _cover("k", "Skirting 100", 0.9, [0, 0, 0, 3, 0.01, 0.1])
    skirt["predefined"] = "SKIRTINGBOARD"
    skirt["qty"]["length"] = 5.0
    est = estimate([room, skirt], "SA", lib, {"finishes_from": "rooms"})
    q = {(l["guid"], l["work_item"]): l["net_qty"] for l in est["lines"]}
    assert q[("k", "FLR-SKRT")] == pytest.approx(5.0)
    assert q[("r", "FLR-SKRT")] == pytest.approx(9.2 - 5.0)


@pytest.mark.parametrize("predefined, recipe", [
    ("SKIRTINGBOARD", "SKIRTING_COVER"), ("INSULATION", "INSULATION_COVER"), ("MEMBRANE", "MEMBRANE_COVER"),
    ("ROOFING", "ROOF_COVER"), ("FLOORING", "FLOOR_FINISH"), ("CEILING", "CEILING"), ("CLADDING", "WALL_COVER"),
])
def test_covering_predefined_types(lib, predefined, recipe):
    el = {"ifc_class": "IfcCovering", "kind": "IfcCovering", "name": "Generic", "type": "Generic",
          "predefined": predefined, "materials": [], "classification": [], "props": {}, "layers": [], "qty": {}}
    assert lib.classify(el)[0] == recipe
