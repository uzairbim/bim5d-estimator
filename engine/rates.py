"""Read, edit and import the rate library for a region."""
import csv
import io
from pathlib import Path

from openpyxl import Workbook, load_workbook

from .estimate import DATA, Library

FIELDS = ["work_item", "material", "labour", "equipment", "source"]


def _region_file(lib, region):
    reg = lib.regions[region]
    return DATA / "rates" / reg.get("rates_file", f"{region}.csv")


def table(region, lib=None):
    """Every work item with its base (converted) rate and any local override."""
    lib = lib or Library()
    reg = lib.regions[region]
    k = reg["fx_per_usd"] * reg["location_factor"]
    local = lib.local_rates.get(region, {})
    rows = []
    for code, wi in lib.work_items.items():
        b = lib.base_rates.get(code)
        base = ([round(float(b[f]) * k, 2) for f in ("material", "labour", "equipment")]
                if b else [0, 0, 0])
        lo = local.get(code)
        rows.append({
            "work_item": code, "description": wi["description"], "unit": wi["unit"],
            "trade": wi["trade"], "base": base,
            "local": ([float(lo["material"] or 0), float(lo["labour"] or 0),
                       float(lo["equipment"] or 0)] if lo else None),
            "source": (lo.get("source") if lo else (b.get("source") if b else "")) or "",
        })
    return {"region": region, "currency": reg["currency"], "factor": round(k, 4), "rows": rows}


def save(region, rows, lib=None):
    """Write local overrides. rows: [{work_item, material, labour, equipment, source}]."""
    lib = lib or Library()
    known = set(lib.work_items)
    clean = []
    for r in rows:
        code = str(r.get("work_item", "")).strip()
        if code not in known:
            continue
        try:
            vals = [round(float(r.get(f) or 0), 4) for f in ("material", "labour", "equipment")]
        except (TypeError, ValueError):
            raise ValueError(f"Rate for {code} is not a number")
        if min(vals) < 0:
            raise ValueError(f"Rate for {code} is negative")
        clean.append({"work_item": code, "material": vals[0], "labour": vals[1],
                      "equipment": vals[2], "source": str(r.get("source") or "user").strip()[:80]})
    path = _region_file(lib, region)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(clean, key=lambda r: r["work_item"]))
    return len(clean)


_ALIASES = {"code": "work_item", "item": "work_item", "work item": "work_item",
            "workitem": "work_item", "mat": "material", "materials": "material",
            "labor": "labour", "plant": "equipment", "equip": "equipment",
            "rate": "rate", "unit rate": "rate", "total": "rate"}


def parse_upload(name, data):
    """Read a CSV or Excel rate sheet. Accepts material/labour/equipment or a single 'rate'."""
    if name.lower().endswith((".xlsx", ".xlsm")):
        ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
        raw = [[("" if c is None else c) for c in row] for row in ws.iter_rows(values_only=True)]
    else:
        raw = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    if not raw:
        return []
    head = [_ALIASES.get(str(h).strip().lower(), str(h).strip().lower()) for h in raw[0]]
    if "work_item" not in head:
        raise ValueError("The sheet needs a 'work_item' (or 'code') column.")
    out = []
    for row in raw[1:]:
        d = dict(zip(head, row))
        if not str(d.get("work_item", "")).strip():
            continue
        if "rate" in d and not any(str(d.get(f, "")).strip() for f in ("material", "labour", "equipment")):
            d["material"], d["labour"], d["equipment"] = d["rate"], 0, 0
        d.setdefault("source", "imported")
        out.append(d)
    return out


def import_rows(region, rows, lib=None):
    """Merge imported rows into the region's overrides."""
    lib = lib or Library()
    current = {c: {"work_item": c, "material": r["material"], "labour": r["labour"],
                   "equipment": r["equipment"], "source": r.get("source", "")}
               for c, r in lib.local_rates.get(region, {}).items()}
    for r in rows:
        current[str(r["work_item"]).strip()] = r
    return save(region, list(current.values()), lib)


def template_xlsx(region, lib=None):
    t = table(region, lib)
    wb = Workbook()
    ws = wb.active
    ws.title = f"Rates {region}"
    ws.append(["work_item", "description", "unit", "material", "labour", "equipment", "source"])
    for r in t["rows"]:
        m, l, e = r["local"] or r["base"]
        ws.append([r["work_item"], r["description"], r["unit"], m, l, e, r["source"]])
    for col, w in zip("ABCDEFG", (12, 48, 8, 12, 12, 12, 30)):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
