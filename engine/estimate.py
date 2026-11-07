"""Turn measured elements into a priced estimate (5D).

Everything that decides the price lives in editable files under data/:
  work_items.csv  - global catalogue of work items (unit, trade, MasterFormat)
  rules.csv       - which recipe an element gets (IFC class + keywords)
  recipes.csv     - how one element breaks into work items (quantity formulas)
  regions.json    - currency, tax, overhead, profit, location factor
  rates/*.csv     - base rates (USD) and local overrides per region
"""
import ast
import csv
import json
import operator
import re
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def _csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


class Library:
    """All cost data, loaded from data/. Reload to pick up edits."""

    def __init__(self, root=DATA):
        root = Path(root)
        self.work_items = {r["code"]: r for r in _csv(root / "work_items.csv")}
        self.rules = sorted(_csv(root / "rules.csv"), key=lambda r: int(r["priority"]))
        for r in self.rules:
            r["_cls"] = set(r["ifc_class"].split("|"))
            r["_kw"] = re.compile(r["keywords"], re.I) if r["keywords"].strip() else None
        self.recipes = defaultdict(list)
        for r in _csv(root / "recipes.csv"):
            r["_expr"] = ast.parse(r["qty"], mode="eval")
            self.recipes[r["recipe"]].append(r)
        regions = json.loads((root / "regions.json").read_text())
        self.regions = {k: v for k, v in regions.items() if not k.startswith("_")}
        self.base_rates = {r["work_item"]: r for r in _csv(root / "rates" / "base_usd.csv")}
        self.local_rates = {}
        for code, reg in self.regions.items():
            f = root / "rates" / reg.get("rates_file", "_none_")
            self.local_rates[code] = {r["work_item"]: r for r in _csv(f)} if f.is_file() else {}

    # -- classification -------------------------------------------------
    def classify(self, el):
        text = " ".join([el["name"], el["type"], *el["materials"]]).lower()
        for r in self.rules:
            if el["ifc_class"] in r["_cls"] and (r["_kw"] is None or r["_kw"].search(text)):
                return r["recipe"]
        return None

    # -- rates ------------------------------------------------------------
    def rate(self, region, work_item):
        """Unit rate in the region's currency: (material, labour, equipment, source)."""
        reg = self.regions[region]
        local = self.local_rates[region].get(work_item)
        if local:
            return (float(local["material"]), float(local["labour"]),
                    float(local["equipment"]), local.get("source") or region)
        base = self.base_rates.get(work_item)
        if not base:
            return 0.0, 0.0, 0.0, "NO RATE"
        k = reg["fx_per_usd"] * reg["location_factor"]
        return (float(base["material"]) * k, float(base["labour"]) * k,
                float(base["equipment"]) * k, (base.get("source") or "base") + " x factor")


# A tiny, safe formula evaluator (numbers, + - * /, and/or, t("regex"), has("regex")).
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow}


def _eval(node, env, layers):
    if isinstance(node, ast.Expression):
        return _eval(node.body, env, layers)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name):
        return float(env.get(node.id, 0.0))
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        a, b = _eval(node.left, env, layers), _eval(node.right, env, layers)
        return 0.0 if isinstance(node.op, ast.Div) and b == 0 else _OPS[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand, env, layers)
    if isinstance(node, ast.BoolOp):  # "a or b" -> first non-zero value
        vals = [_eval(v, env, layers) for v in node.values]
        if isinstance(node.op, ast.Or):
            return next((v for v in vals if v), 0.0)
        return vals[-1] if all(vals) else 0.0
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t"
            and len(node.args) == 1 and isinstance(node.args[0], ast.Constant)):
        rx = re.compile(node.args[0].value, re.I)
        return sum(l["t"] for l in layers if rx.search(l["name"] or ""))
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "has"
            and len(node.args) == 1 and isinstance(node.args[0], ast.Constant)):
        rx = re.compile(node.args[0].value, re.I)
        return 1.0 if any(rx.search(l["name"] or "") for l in layers) else 0.0
    raise ValueError(f"Formula not allowed: {ast.dump(node)}")


def estimate(elements, region, lib=None):
    lib = lib or Library()
    reg = lib.regions[region]
    lines, unclassified, flagged = [], [], []
    per_element = {}

    for el in elements:
        recipe = lib.classify(el)
        if el["qty"].get("check"):
            flagged.append(el["guid"])
        if recipe is None:
            unclassified.append(el["guid"])
            per_element[el["guid"]] = {"recipe": None, "total": 0.0}
            continue
        el_total = 0.0
        for item in lib.recipes[recipe]:
            qty = _eval(item["_expr"], el["qty"], el.get("layers", []))
            if qty <= 0:
                continue
            qty *= 1 + float(item["waste_pct"] or 0) / 100
            mat, lab, eqp, src = lib.rate(region, item["work_item"])
            unit_rate = mat + lab + eqp
            wi = lib.work_items.get(item["work_item"], {})
            line = {
                "guid": el["guid"], "element": el["name"], "ifc_class": el["ifc_class"],
                "level": el["level"], "recipe": recipe, "work_item": item["work_item"],
                "description": wi.get("description", item["work_item"]),
                "trade": wi.get("trade", "Other"), "unit": wi.get("unit", ""),
                "qty": round(qty, 3), "material": round(qty * mat, 2),
                "labour": round(qty * lab, 2), "equipment": round(qty * eqp, 2),
                "rate": round(unit_rate, 2), "amount": round(qty * unit_rate, 2),
                "rate_source": src,
            }
            lines.append(line)
            el_total += line["amount"]
        per_element[el["guid"]] = {"recipe": recipe, "total": round(el_total, 2)}

    # Bill of quantities: one row per work item.
    boq = {}
    for l in lines:
        b = boq.setdefault(l["work_item"], {k: l[k] for k in
                                            ("work_item", "description", "trade", "unit", "rate", "rate_source")})
        b["qty"] = round(b.get("qty", 0) + l["qty"], 3)
        b["amount"] = round(b.get("amount", 0) + l["amount"], 2)
        b["elements"] = b.get("elements", 0) + 1
    boq = sorted(boq.values(), key=lambda b: (b["trade"], b["work_item"]))

    def group(key):
        g = defaultdict(float)
        for l in lines:
            g[l[key]] += l["amount"]
        return dict(sorted(((k, round(v, 2)) for k, v in g.items()), key=lambda kv: -kv[1]))

    direct = round(sum(l["amount"] for l in lines), 2)
    overhead = round(direct * reg["overhead_pct"] / 100, 2)
    profit = round((direct + overhead) * reg["profit_pct"] / 100, 2)
    subtotal = direct + overhead + profit
    tax = round(subtotal * reg["tax_pct"] / 100, 2)
    return {
        "region": region, "region_name": reg["name"], "currency": reg["currency"],
        "summary": {"direct": direct, "overhead": overhead, "profit": profit,
                    "tax": tax, "tax_name": reg["tax_name"], "total": round(subtotal + tax, 2),
                    "overhead_pct": reg["overhead_pct"], "profit_pct": reg["profit_pct"],
                    "tax_pct": reg["tax_pct"]},
        "by_trade": group("trade"), "by_level": group("level"), "by_class": group("ifc_class"),
        "boq": boq, "lines": lines, "per_element": per_element,
        "checks": {"elements": len(elements), "priced": len(elements) - len(unclassified),
                   "unclassified": unclassified, "geometry_flagged": flagged},
    }
