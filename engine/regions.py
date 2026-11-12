"""Regions (countries), local resource prices, World Bank update and rate packs.

Anyone can set up their own country:
  1. create a region from the country list (currency and VAT filled in),
  2. optionally pull the exchange rate and price level from the World Bank (free, CC BY 4.0),
  3. type local prices for the resources they know (labour, cement, rebar, blocks...);
     every work-item rate is then built up from those prices,
  4. share the result as a "rate pack" file.
"""
import csv
import math
import datetime as dt
import json
import threading
import urllib.request

from .estimate import DATA, Library, user_dir

_lock = threading.Lock()
PACK_FORMAT = "bim5d-ratepack"
REGION_FIELDS = ("name", "currency", "fx_per_usd", "location_factor", "labour_factor", "material_factor",
                 "plant_factor", "tax_name", "tax_pct", "overhead_pct", "profit_pct", "contingency_pct",
                 "prelims_pct", "escalation_pct", "standard", "benchmark", "notes", "fx_source")


def countries():
    return json.loads((DATA / "countries.json").read_text(encoding="utf-8"))


def _shipped():
    return json.loads((DATA / "regions.json").read_text(encoding="utf-8"))


def _load():
    """Countries shipped with the app, with yours (added, changed or deleted) on top."""
    d = _shipped()
    f = user_dir() / "regions.json"
    if f.is_file():
        for k, v in json.loads(f.read_text(encoding="utf-8")).items():
            if v is None:
                d.pop(k, None)
            else:
                d[k] = {**d.get(k, {}), **v}
    return d


def _save(d):
    """Keep only what differs from the shipped countries, in your own folder (kept by new versions)."""
    shipped = _shipped()
    mine = {k: v for k, v in d.items() if shipped.get(k) != v}
    mine.update({k: None for k in shipped if k not in d and not k.startswith("_")})
    f = user_dir() / "regions.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(mine, indent=2, ensure_ascii=False), encoding="utf-8")


def create_region(code, values=None):
    """Create or update a region. `code` is usually the ISO country code."""
    code = str(code).upper().strip()[:12]
    if not code or not code.replace("_", "").isalnum():
        raise ValueError("Region code must be letters/numbers, e.g. NG or NG_LAGOS")
    values = values or {}
    with _lock:
        d = _load()
        reg = d.get(code, {})
        c = next((x for x in countries() if x["code"] == code[:2]), None)
        if not reg:
            reg = {"name": c["name"] if c else code, "currency": c["currency"] if c else "USD",
                   "fx_per_usd": 1.0, "location_factor": 1.0, "labour_factor": 1.0, "material_factor": 1.0,
                   "tax_name": (c or {}).get("tax_name") or "VAT/GST",
                   "tax_pct": (c or {}).get("tax_pct") or 0,
                   "overhead_pct": 10, "profit_pct": 10, "contingency_pct": 5, "prelims_pct": 10,
                   "escalation_pct": 0, "standard": "NRM2",
                   "notes": "Set the exchange rate (or use Update from World Bank) and enter local prices."}
        for k, v in values.items():
            if k in REGION_FIELDS:
                reg[k] = v
        for k in ("fx_per_usd", "location_factor", "labour_factor", "material_factor", "plant_factor",
                  "tax_pct", "overhead_pct", "profit_pct", "contingency_pct", "prelims_pct", "escalation_pct"):
            if k in reg and reg[k] is not None:
                reg[k] = float(reg[k])
        d[code] = reg
        _save(d)
    return code, reg


def delete_region(code):
    with _lock:
        d = _load()
        d.pop(code, None)
        _save(d)


# ---- local resource prices -------------------------------------------------------------
def _prices_path(region):
    """Your prices: in your own folder, over the assumed prices shipped with the app."""
    p = user_dir() / "prices"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{region}.csv"


def _shipped_prices(region):
    f = DATA / "prices" / f"{region}.csv"
    if not f.is_file():
        return {}
    with open(f, newline="", encoding="utf-8") as fh:
        return {r["resource"]: r for r in csv.DictReader(fh)}


def price_table(region, lib=None):
    lib = lib or Library()
    f = lib.factors(region)
    mine = lib.prices.get(region, {})
    rows = []
    for code, r in lib.resources.items():
        est = float(r["price_usd"]) * f["fx"] * f.get(r["type"], f["material"])
        p = mine.get(code)
        rows.append({"resource": code, "name": r["name"], "unit": r["unit"], "type": r["type"],
                     "key": r.get("key") == "1", "estimated": round(est, 4),
                     "price": float(p["price"]) if p else None, "kind": lib.price_kind(region, code),
                     "source": (p or {}).get("source", ""), "date": (p or {}).get("date", "")})
    used = {n["resource"] for ns in lib.norms.values() for n in ns}
    rows.sort(key=lambda x: (not x["key"], x["type"], x["resource"] not in used, x["name"]))
    return {"region": region, "currency": lib.regions[region]["currency"], "factors": f, "rows": rows,
            "filled": sum(1 for x in rows if x["price"] is not None)}


def save_prices(region, rows, lib=None):
    lib = lib or Library()
    clean = []
    for r in rows:
        code = str(r.get("resource", "")).strip()
        if code not in lib.resources or r.get("price") in (None, ""):
            continue
        try:
            price = float(r["price"])
        except (TypeError, ValueError):
            raise ValueError(f"Price for {code} is not a number")
        if not math.isfinite(price) or price < 0:
            raise ValueError(f"Price for {code} must be a positive number")
        clean.append({"resource": code, "price": round(price, 6),
                      "source": str(r.get("source") or "user")[:80],
                      "date": str(r.get("date") or dt.date.today().isoformat())[:10]})
    shipped = _shipped_prices(region)       # an unchanged assumed price stays the app's (a new version updates it)
    clean = [r for r in clean if not (r["resource"] in shipped
                                      and abs(float(shipped[r["resource"]]["price"] or 0) - r["price"]) < 1e-9
                                      and shipped[r["resource"]].get("source", "") == r["source"])]
    with _lock, open(_prices_path(region), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["resource", "price", "source", "date"])
        w.writeheader()
        w.writerows(sorted(clean, key=lambda x: x["resource"]))
    return len(clean)


# ---- World Bank (run on the user's own machine; needs internet) ---------------------
WB = "https://api.worldbank.org/v2/country/{iso}/indicator/{ind}?format=json&mrnev=1"
FX = "PA.NUS.FCRF"          # official exchange rate, local currency per USD (period average)
PLI = "PA.NUS.PPPC.RF"      # price level ratio of PPP conversion factor (GDP) to market rate (US = 1)


def _wb(iso, ind, timeout=20):
    with urllib.request.urlopen(WB.format(iso=iso, ind=ind), timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    rows = data[1] if isinstance(data, list) and len(data) > 1 and data[1] else []
    for row in rows:
        if row.get("value") is not None:
            return float(row["value"]), row.get("date")
    return None, None


def worldbank(region):
    """Fetch exchange rate and price level for the region's country and update factors.

    Labour follows the general price level; materials are traded internationally and
    vary less, so the material factor uses the square root of the price level. These
    are starting points only: your own prices always win.
    """
    iso = region[:2]
    fx, fx_year = _wb(iso, FX)
    pl, pl_year = _wb(iso, PLI)
    if fx is None and pl is None:
        raise ValueError("The World Bank has no data for this country.")
    values = {}
    if fx is not None:
        values["fx_per_usd"] = round(fx, 6)
        values["fx_source"] = f"World Bank {FX} ({fx_year})"
    if pl is not None:
        values.update({"location_factor": round(pl, 4), "labour_factor": round(pl, 4),
                       "material_factor": round(pl ** 0.5, 4), "plant_factor": round(pl ** 0.5, 4)})
        values["notes"] = (f"Price level {pl:.2f} of the US (World Bank {PLI}, {pl_year}). "
                           "Labour factor = price level, material and plant factor = square root of it. "
                           "Replace with local prices where you know them.")
    create_region(region, values)
    return values


# ---- rate packs ----------------------------------------------------------------------------
def export_pack(region, author="", notes=""):
    lib = Library()
    reg = lib.regions[region]
    prices = [{"resource": k, **{x: v.get(x) for x in ("price", "source", "date")}}
              for k, v in lib.prices.get(region, {}).items()]
    rates = [dict(v) for v in lib.local_rates.get(region, {}).values()]
    return {"format": PACK_FORMAT, "version": 1, "created": dt.datetime.now().isoformat(timespec="seconds"),
            "author": author, "notes": notes, "region_code": region,
            "region": {k: reg.get(k) for k in REGION_FIELDS if reg.get(k) is not None},
            "prices": prices, "rates": rates}


def import_pack(pack, as_code=None):
    if not isinstance(pack, dict) or pack.get("format") != PACK_FORMAT:
        raise ValueError("This is not a BIM 5D rate pack file.")
    code = (as_code or pack.get("region_code") or "").upper()
    code, _ = create_region(code, pack.get("region") or {})
    n = save_prices(code, pack.get("prices") or [])
    from . import rates as rates_mod
    m = rates_mod.save(code, pack.get("rates") or []) if pack.get("rates") else 0
    return {"region": code, "prices": n, "rates": m}
