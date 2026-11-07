"""Turn measured elements into a priced estimate (5D).

Everything that decides the price lives in editable files under data/:
  work_items.csv     global catalogue of work items (unit, trade, MasterFormat)
  rules.csv          which recipe an element gets (IFC class + keywords)
  recipes.csv        how one element breaks into work items (quantity formulas)
  recipe_groups.csv  NRM1 / Uniformat element group and build stage of each recipe
  regions.json       currency, tax, overhead, profit, contingency, location factor
  rates/*.csv        base rates (USD) and local overrides per region

A project can add its own mappings ({group key: recipe}) which win over the rules.
"""
import ast
import csv
import json
import operator
import re
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
NONE = "(not priced)"


def _csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def group_key(el):
    """Elements of the same kind and type are mapped together.

    Revit names look like 'Family:Type:123456'; the trailing id is dropped.
    """
    name = el.get("type") or re.sub(r":\d+$", "", el.get("name") or "")
    name = re.sub(r":\d+$", "", name)
    return f"{el.get('kind') or el['ifc_class']}|{name}"


def match_text(el):
    p = el.get("props", {})
    return " ".join([el.get("name", ""), el.get("type", ""), el.get("predefined", ""),
                     *el.get("materials", []), *el.get("classification", []),
                     *(str(v) for v in p.values())])


class Library:
    """All cost data, loaded from data/. Create a new one to pick up edits."""

    def __init__(self, root=DATA):
        self.root = root = Path(root)
        self.work_items = {r["code"]: r for r in _csv(root / "work_items.csv")}
        self.rules = sorted(_csv(root / "rules.csv"), key=lambda r: int(r["priority"]))
        for r in self.rules:
            r["_cls"] = set(r["ifc_class"].split("|"))
            # Lower-case words match any case; UPPER-case words (IFC predefined types) match exactly.
            r["_kw"] = re.compile(r["keywords"], re.I) if r["keywords"].strip() else None
        self.recipes = defaultdict(list)
        for r in _csv(root / "recipes.csv"):
            r["_expr"] = ast.parse(r["qty"], mode="eval")
            self.recipes[r["recipe"]].append(r)
        self.groups = {r["recipe"]: r for r in _csv(root / "recipe_groups.csv")}
        regions = json.loads((root / "regions.json").read_text(encoding="utf-8"))
        self.regions = {k: v for k, v in regions.items() if not k.startswith("_")}
        self.base_rates = {r["work_item"]: r for r in _csv(root / "rates" / "base_usd.csv")}
        self.local_rates = {}
        for code, reg in self.regions.items():
            f = root / "rates" / reg.get("rates_file", f"{code}.csv")
            self.local_rates[code] = {r["work_item"]: r for r in _csv(f)} if f.is_file() else {}

    # -- classification -------------------------------------------------
    def rule_for(self, el):
        text = match_text(el)
        classes = {el["ifc_class"], el.get("kind") or el["ifc_class"]}
        for r in self.rules:
            if classes & r["_cls"] and (r["_kw"] is None or r["_kw"].search(text)):
                return r
        return None

    def classify(self, el, mappings=None):
        """Return (recipe or None, source) where source is 'mapping', 'rule' or 'none'."""
        if mappings:
            m = mappings.get(group_key(el))
            if m:
                return (None, "excluded") if m == "EXCLUDE" else (m, "mapping")
        r = self.rule_for(el)
        if r is None:
            return None, "none"
        if r["recipe"] == "EXCLUDE":   # site context, people, trees...
            return None, "excluded"
        return r["recipe"], "rule"

    # -- rates ------------------------------------------------------------
    def rate(self, region, work_item):
        """Unit rate in the region's currency: (material, labour, equipment, source)."""
        reg = self.regions[region]
        local = self.local_rates[region].get(work_item)
        if local:
            return (float(local["material"] or 0), float(local["labour"] or 0),
                    float(local["equipment"] or 0), local.get("source") or region)
        base = self.base_rates.get(work_item)
        if not base:
            return 0.0, 0.0, 0.0, "NO RATE"
        k = reg["fx_per_usd"] * reg["location_factor"]
        return (float(base["material"]) * k, float(base["labour"]) * k,
                float(base["equipment"]) * k, (base.get("source") or "base") + " (converted)")


# ---- a tiny, safe formula evaluator -----------------------------------------
# numbers, + - * / **, comparisons (give 1 or 0), and/or, t("regex"), has("regex")
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow}
_CMP = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
        ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}


def evaluate(node, env, layers):
    if isinstance(node, ast.Expression):
        return evaluate(node.body, env, layers)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name):
        return float(env.get(node.id, 0.0))
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        a, b = evaluate(node.left, env, layers), evaluate(node.right, env, layers)
        return 0.0 if isinstance(node.op, ast.Div) and b == 0 else _OPS[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -evaluate(node.operand, env, layers)
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _CMP:
        a, b = evaluate(node.left, env, layers), evaluate(node.comparators[0], env, layers)
        return 1.0 if _CMP[type(node.ops[0])](a, b) else 0.0
    if isinstance(node, ast.BoolOp):  # "a or b" -> first non-zero value
        vals = [evaluate(v, env, layers) for v in node.values]
        if isinstance(node.op, ast.Or):
            return next((v for v in vals if v), 0.0)
        return vals[-1] if all(vals) else 0.0
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in ("t", "has") and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
        rx = re.compile(node.args[0].value, re.I)
        hits = [l for l in layers if rx.search(l.get("name") or "")]
        return sum(l["t"] for l in hits) if node.func.id == "t" else float(bool(hits))
    raise ValueError("This formula uses something that is not allowed.")


def check_formula(text):
    """Raise ValueError if a recipe formula is not valid."""
    evaluate(ast.parse(text, mode="eval"), {}, [])


# ---- the estimate --------------------------------------------------------------
FLOOR_RECIPES = {"RC_SLAB", "SLAB_ON_GRADE", "TIMBER_FLOOR"}


def estimate(elements, region, lib=None, settings=None):
    lib = lib or Library()
    settings = settings or {}
    reg = dict(lib.regions[region])
    for k in ("overhead_pct", "profit_pct", "contingency_pct", "tax_pct"):
        if settings.get(k) is not None:
            reg[k] = float(settings[k])
    mappings = settings.get("mappings") or {}
    rebar_mode = settings.get("rebar_mode") or "ratio"

    lines, per_element, groups = [], {}, {}
    unclassified, flagged, excluded = [], [], []
    modeled_rebar_kg = ratio_rebar_kg = 0.0

    for el in elements:
        recipe, source = lib.classify(el, mappings)
        if el["qty"].get("check"):
            flagged.append(el["guid"])
        key = group_key(el)
        g = groups.setdefault(key, {"key": key, "kind": el.get("kind") or el["ifc_class"],
                                    "type": key.split("|", 1)[1], "count": 0, "total": 0.0,
                                    "recipe": recipe, "source": source, "guids": [],
                                    "sample": el["guid"], "materials": el.get("materials", [])[:4]})
        g["count"] += 1
        g["guids"].append(el["guid"])
        if recipe is None:
            (excluded if source == "excluded" else unclassified).append(el["guid"])
            per_element[el["guid"]] = {"recipe": None, "source": source, "total": 0.0}
            continue
        grp = lib.groups.get(recipe, {})
        el_total = 0.0
        for item in lib.recipes.get(recipe, []):
            qty = evaluate(item["_expr"], el["qty"], el.get("layers", []))
            if qty <= 0:
                continue
            opt = (item.get("option") or "").strip()
            if opt == "rebar_ratio":
                ratio_rebar_kg += qty if item["work_item"] == "RBR" else 0
                if rebar_mode == "modeled":
                    continue
            if opt == "rebar_modeled":
                modeled_rebar_kg += qty
                if rebar_mode != "modeled":
                    continue
            waste = float(item["waste_pct"] or 0)
            qty_w = qty * (1 + waste / 100)
            mat, lab, eqp, src = lib.rate(region, item["work_item"])
            unit_rate = mat + lab + eqp
            wi = lib.work_items.get(item["work_item"], {})
            line = {
                "guid": el["guid"], "element": el["name"], "ifc_class": el["ifc_class"],
                "level": el["level"], "recipe": recipe, "work_item": item["work_item"],
                "description": wi.get("description", item["work_item"]),
                "trade": wi.get("trade", "Other"), "unit": wi.get("unit", ""),
                "formula": item["qty"], "net_qty": round(qty, 4), "waste_pct": waste,
                "qty": round(qty_w, 4), "material": round(qty_w * mat, 2),
                "labour": round(qty_w * lab, 2), "equipment": round(qty_w * eqp, 2),
                "rate": round(unit_rate, 2), "amount": round(qty_w * unit_rate, 2),
                "rate_source": src,
                "nrm1": grp.get("nrm1", "Other"), "uniformat": grp.get("uniformat", "Other"),
                "stage": grp.get("stage", "9 Other"),
            }
            lines.append(line)
            el_total += line["amount"]
        per_element[el["guid"]] = {"recipe": recipe, "source": source, "total": round(el_total, 2),
                                   "stage": grp.get("stage", "9 Other")}
        g["total"] += el_total

    # Bill of quantities: one row per work item.
    boq = {}
    for l in lines:
        b = boq.setdefault(l["work_item"], {k: l[k] for k in
                                            ("work_item", "description", "trade", "unit", "rate", "rate_source")})
        b["qty"] = b.get("qty", 0) + l["qty"]
        b["amount"] = b.get("amount", 0) + l["amount"]
        b["elements"] = b.get("elements", 0) + 1
    for b in boq.values():
        b["qty"], b["amount"] = round(b["qty"], 3), round(b["amount"], 2)
    boq = sorted(boq.values(), key=lambda b: (b["trade"], b["work_item"]))

    def group(key):
        out = defaultdict(float)
        for l in lines:
            out[l[key]] += l["amount"]
        return dict(sorted(((k, round(v, 2)) for k, v in out.items()), key=lambda kv: -kv[1]))

    def group_sorted(key):
        return dict(sorted(group(key).items()))

    direct = round(sum(l["amount"] for l in lines), 2)
    contingency = round(direct * reg.get("contingency_pct", 0) / 100, 2)
    overhead = round((direct + contingency) * reg["overhead_pct"] / 100, 2)
    profit = round((direct + contingency + overhead) * reg["profit_pct"] / 100, 2)
    subtotal = direct + contingency + overhead + profit
    tax = round(subtotal * reg["tax_pct"] / 100, 2)
    total = round(subtotal + tax, 2)

    # Gross floor area from floor slabs (not roofs), for cost per m2.
    gfa = sum(e["qty"]["footprint"] for e in elements
              if per_element.get(e["guid"], {}).get("recipe") in FLOOR_RECIPES)
    bench = reg.get("benchmark")

    group_list = sorted(groups.values(), key=lambda g: (g["recipe"] is not None, -g["total"]))
    for g in group_list:
        g["total"] = round(g["total"], 2)

    return {
        "region": region, "region_name": reg["name"], "currency": reg["currency"],
        "summary": {"direct": direct, "contingency": contingency, "overhead": overhead,
                    "profit": profit, "tax": tax, "tax_name": reg["tax_name"], "total": total,
                    "contingency_pct": reg.get("contingency_pct", 0),
                    "overhead_pct": reg["overhead_pct"], "profit_pct": reg["profit_pct"],
                    "tax_pct": reg["tax_pct"], "gfa": round(gfa, 1),
                    "per_m2": round(total / gfa, 2) if gfa > 1 else None,
                    "benchmark": bench},
        "by_trade": group("trade"), "by_level": group("level"),
        "by_nrm1": group_sorted("nrm1"), "by_uniformat": group_sorted("uniformat"),
        "by_stage": group_sorted("stage"),
        "boq": boq, "lines": lines, "per_element": per_element, "groups": group_list,
        "settings": {"rebar_mode": rebar_mode},
        "checks": {"elements": len(elements),
                   "priced": len(elements) - len(unclassified) - len(excluded),
                   "unclassified": unclassified, "excluded": excluded,
                   "geometry_flagged": flagged,
                   "rebar": {"modeled_kg": round(modeled_rebar_kg), "ratio_kg": round(ratio_rebar_kg),
                             "mode": rebar_mode}},
    }
