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

# Who keeps the shared volume when two elements overlap (lower number keeps it).
# Follows normal measurement practice: slabs measured through, columns stop at the
# slab soffit, beams measured below the slab, walls between frame members.
# Steel always keeps its weight; the concrete around it is reduced instead.
OVERLAP_PRIORITY = {
    "STEEL_MEMBER": -1, "STEEL_PLATE": -1,
    "RC_PILE": 0, "RC_FOOTING": 0,
    "SLAB_ON_GRADE": 1, "RC_SLAB": 1, "ROOF_RC": 1, "TIMBER_FLOOR": 1, "ROOF_LIGHT": 1,
    "RC_COLUMN": 2, "RC_BEAM": 3, "RC_WALL": 4, "STAIR_RC": 4,
    "CAVITY_WALL": 5, "BLOCK_WALL": 5, "BRICK_WALL": 5, "DRYWALL": 6,
}

# AACE 18R-97 style classes used to express the expected accuracy range.
ACCURACY = {
    5: ("Class 5 - concept", -0.50, 1.00),
    4: ("Class 4 - feasibility", -0.30, 0.50),
    3: ("Class 3 - budget", -0.20, 0.30),
    2: ("Class 2 - control / tender check", -0.15, 0.20),
}

DEFAULT_EXCLUSIONS = [
    "Land, legal and authority fees",
    "Design and supervision fees",
    "Loose furniture and equipment unless modelled",
    "Utility connections and off-site infrastructure",
    "Client contingency and finance costs",
]

# What a complete building normally contains, and what to suggest when it is missing.
SCOPE = [
    ("Substructure", ("1 Substructure",), "Foundations allowance", 8),
    ("Frame and upper floors", ("2.1 Frame", "2.2 Upper floors"), None, None),
    ("Roof", ("2.3 Roof",), None, None),
    ("External walls / envelope", ("2.5 External walls", "2.6 Windows and external doors"), None, None),
    ("Internal walls and doors", ("2.7 Internal walls and partitions", "2.8 Internal doors"), None, None),
    ("Internal finishes", ("3.1 Wall finishes", "3.2 Floor finishes", "3.3 Ceiling finishes"),
     "Internal finishes allowance", 12),
    ("MEP services", ("5.",), "MEP services allowance (not modelled)", 25),
    ("External works", ("8",), "External works allowance", 5),
]


def _deductions(elements, recipes, deduct):
    """Overlap volume each element gives up, and the overlap records."""
    give = defaultdict(float)
    records, seen = [], set()
    if not deduct:
        return give, records
    for e in elements:
        for other, vol in e.get("overlaps") or []:
            pair = tuple(sorted((e["guid"], other)))
            if pair in seen:
                continue
            seen.add(pair)
            ra, rb = recipes.get(pair[0]), recipes.get(pair[1])
            pa, pb = OVERLAP_PRIORITY.get(ra), OVERLAP_PRIORITY.get(rb)
            if pa is None or pb is None:
                continue
            if pa == pb:
                loser, kind = pair[1], "same type" if ra == rb else "overlap"
            else:
                loser, kind = (pair[1] if pa < pb else pair[0]), "overlap"
            give[loser] += vol
            records.append({"a": pair[0], "b": pair[1], "volume": vol, "loser": loser, "kind": kind})
    return give, records


def _env(el, give, min_open):
    """Quantities used by the formulas, after overlap and opening rules."""
    q = dict(el["qty"])
    d = give.get(el["guid"], 0.0)
    if d > 0 and q.get("volume", 0) > 0:
        d = min(d, q["volume"] * 0.95)
        f = (q["volume"] - d) / q["volume"]
        q["volume_gross"] = q["volume"]
        for k in ("volume", "side", "area", "surface"):
            if k in q:
                q[k] = q[k] * f
        q["overlap"] = d
    small = sum(a for a in el.get("openings") or [] if a <= min_open)
    q["openings_small"] = small
    q["side_m"] = q.get("side", 0.0) + small          # face measured to the rule
    q["footprint_m"] = q.get("footprint", 0.0) + small
    return q


def estimate(elements, region, lib=None, settings=None):
    lib = lib or Library()
    settings = settings or {}
    reg = dict(lib.regions[region])
    for k in ("overhead_pct", "profit_pct", "contingency_pct", "tax_pct", "prelims_pct", "escalation_pct"):
        if settings.get(k) is not None:
            reg[k] = float(settings[k])
    reg.setdefault("prelims_pct", 10)
    reg.setdefault("escalation_pct", 0)
    mappings = settings.get("mappings") or {}
    rebar_mode = settings.get("rebar_mode") or "ratio"
    deduct = settings.get("deduct_overlaps", True) is not False
    min_open = float(settings.get("min_deduct_m2") if settings.get("min_deduct_m2") is not None else 0.5)
    adjust = settings.get("adjustments") or {}

    # classify first (overlap rules depend on how each element is priced)
    cls = {e["guid"]: lib.classify(e, mappings) for e in elements}
    give, overlap_records = _deductions(elements, {g: r for g, (r, _) in cls.items()}, deduct)

    lines, per_element, groups = [], {}, {}
    unclassified, flagged, excluded = [], [], []
    modeled_rebar_kg = ratio_rebar_kg = 0.0
    recon = []

    for el in elements:
        recipe, source = cls[el["guid"]]
        q0 = el["qty"]
        if q0.get("check") in (1.0, 3.0):
            flagged.append(el["guid"])
        key = group_key(el)
        g = groups.setdefault(key, {"key": key, "kind": el.get("kind") or el["ifc_class"],
                                    "type": key.split("|", 1)[1], "count": 0, "total": 0.0,
                                    "recipe": recipe, "source": source, "guids": [],
                                    "sample": el["guid"], "materials": el.get("materials", [])[:4],
                                    "adjust": adjust.get(key)})
        g["count"] += 1
        g["guids"].append(el["guid"])
        av = (el.get("authored") or {}).get("volume")
        if av and q0.get("volume") and recipe is not None and q0.get("check") == 0:
            recon.append((el["guid"], q0["volume"], av))
        if recipe is None:
            (excluded if source == "excluded" else unclassified).append(el["guid"])
            per_element[el["guid"]] = {"recipe": None, "source": source, "total": 0.0}
            continue
        env = _env(el, give, min_open)
        adj = adjust.get(key) or {}
        factor = float(adj.get("factor") or 1.0)
        grp = lib.groups.get(recipe, {})
        el_total = 0.0
        for item in lib.recipes.get(recipe, []):
            qty = evaluate(item["_expr"], env, el.get("layers", [])) * factor
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
                "formula": item["qty"] + (f" x {factor:g} (adjusted)" if factor != 1 else ""),
                "net_qty": round(qty, 4), "waste_pct": waste,
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
                                   "stage": grp.get("stage", "9 Other"),
                                   "overlap_m3": round(env.get("overlap", 0.0), 4),
                                   "openings_kept_m2": round(env.get("openings_small", 0.0), 3)}
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

    by_nrm1 = group_sorted("nrm1")
    direct = round(sum(l["amount"] for l in lines), 2)

    # Gross floor area from floor slabs (not roofs), for cost per m2 and allowances.
    gfa = sum(e["qty"]["footprint"] for e in elements
              if per_element.get(e["guid"], {}).get("recipe") in FLOOR_RECIPES)
    if settings.get("gfa_m2"):
        gfa = float(settings["gfa_m2"])

    # ---- scope coverage and allowances --------------------------------------
    scope = []
    for name, prefixes, allowance, pct in SCOPE:
        cost = sum(v for k, v in by_nrm1.items() if any(k.startswith(p) for p in prefixes))
        scope.append({"name": name, "cost": round(cost, 2), "present": cost > 0,
                      "suggest": None if cost > 0 or not allowance else
                      {"name": allowance, "kind": "pct", "value": pct}})
    allowances = []
    for a in settings.get("allowances") or []:
        kind, val = a.get("kind", "lump"), float(a.get("value") or 0)
        amount = direct * val / 100 if kind == "pct" else val * gfa if kind == "per_m2" else val
        allowances.append({**a, "amount": round(amount, 2)})
    allow_total = round(sum(a["amount"] for a in allowances), 2)

    construction = direct + allow_total
    prelims = round(construction * reg["prelims_pct"] / 100, 2)
    contingency = round((construction + prelims) * reg.get("contingency_pct", 0) / 100, 2)
    overhead = round((construction + prelims + contingency) * reg["overhead_pct"] / 100, 2)
    profit = round((construction + prelims + contingency + overhead) * reg["profit_pct"] / 100, 2)
    escalation = round((construction + prelims + contingency + overhead + profit)
                       * reg["escalation_pct"] / 100, 2)
    subtotal = construction + prelims + contingency + overhead + profit + escalation
    tax = round(subtotal * reg["tax_pct"] / 100, 2)
    total = round(subtotal + tax, 2)

    # ---- reconciliation with the authoring tool's own quantities -------------
    within = [abs(o / a - 1) <= 0.05 for _, o, a in recon]
    outliers = sorted(({"guid": g_, "measured": round(o, 4), "authored": round(a, 4),
                        "diff_pct": round((o / a - 1) * 100, 1)} for g_, o, a in recon
                       if abs(o / a - 1) > 0.05), key=lambda r: -abs(r["diff_pct"]))
    reconciliation = {"compared": len(recon), "within_5pct": sum(within),
                      "share": round(sum(within) / len(recon), 3) if recon else None,
                      "outliers": outliers[:50]}

    # ---- accuracy class ---------------------------------------------------------
    sample_cost = sum(b["amount"] for b in boq if str(b["rate_source"]).upper().startswith("SAMPLE"))
    sample_share = sample_cost / direct if direct else 1.0
    unpriced_share = len(unclassified) / max(len(elements), 1)
    flagged_cost = sum(per_element[g_]["total"] for g_ in flagged if g_ in per_element)
    missing = [s_["name"] for s_ in scope if not s_["present"] and s_["name"] in
               ("MEP services", "Internal finishes", "Substructure")]
    covered = {a.get("name", "").split(" ")[0] for a in allowances}
    missing_uncovered = [m for m in missing if m.split(" ")[0] not in covered and
                         not any(m.split(" ")[0].lower() in a.get("name", "").lower() for a in allowances)]
    reasons = []
    if sample_share > 0.5:
        cls_ = 5
        reasons.append(f"{sample_share:.0%} of the cost uses SAMPLE rates. Enter real rates.")
    elif missing_uncovered or unpriced_share > 0.1:
        cls_ = 4
        if missing_uncovered:
            reasons.append("Not in the model and no allowance yet: " + ", ".join(missing_uncovered) + ".")
        if unpriced_share > 0.1:
            reasons.append(f"{unpriced_share:.0%} of elements are not priced. Use Mapping.")
    else:
        cls_ = 3
        if sample_share > 0:
            reasons.append(f"{sample_share:.0%} of the cost still uses SAMPLE rates.")
        if direct and flagged_cost / direct > 0.05:
            reasons.append("More than 5% of the cost is on shapes that could not be measured exactly.")
        if reconciliation["share"] is not None and reconciliation["share"] < 0.9:
            reasons.append("Less than 90% of quantities agree with the model's own values. Check the outliers.")
        if not reasons and settings.get("rates_verified"):
            cls_ = 2
    if cls_ > 2 and not reasons:
        reasons.append("Confirm your rates are current market prices (tick 'Rates checked') to reach Class 2.")
    label, lo_pct, hi_pct = ACCURACY[cls_]
    accuracy = {"class": cls_, "label": label, "low_pct": lo_pct, "high_pct": hi_pct,
                "low": round(total * (1 + lo_pct), -2), "high": round(total * (1 + hi_pct), -2),
                "reasons": reasons, "sample_rate_share": round(sample_share, 3)}

    # ---- assumptions & exclusions -------------------------------------------------
    ov_total = sum(r["volume"] for r in overlap_records)
    rb = {"modeled_kg": round(modeled_rebar_kg), "ratio_kg": round(ratio_rebar_kg), "mode": rebar_mode}
    assumptions = [
        "Quantities are measured from the 3D model. Work that is not modelled is excluded "
        "unless it is listed as an allowance.",
        ("Reinforcement is taken from the modelled bars." if rebar_mode == "modeled" else
         "Reinforcement is an allowance by ratio (kg per m³ of concrete) until bar schedules are available."),
        f"Openings up to {min_open:g} m² are not deducted from masonry and finishes (NRM2 practice).",
        (f"Overlaps between elements are deducted once ({len(overlap_records)} overlaps, {ov_total:.2f} m³): "
         "slabs measured through, columns to slab soffit, beams below slab, walls between frame members."
         if deduct else "Overlaps between elements are NOT deducted."),
        f"Waste allowances are included in quantities as shown per item.",
        f"Preliminaries {reg['prelims_pct']:g}%, contingency {reg.get('contingency_pct', 0):g}%, "
        f"overhead {reg['overhead_pct']:g}%, profit {reg['profit_pct']:g}%, escalation {reg['escalation_pct']:g}%.",
        f"{reg['tax_name']} at {reg['tax_pct']:g}% is included in the total.",
        f"Prices in {reg['currency']} at the date of the rates used.",
    ]
    if sample_share > 0:
        assumptions.append(f"{sample_share:.0%} of the measured cost uses SAMPLE placeholder rates.")
    assumptions += [a for a in settings.get("assumptions") or [] if a]
    exclusions = settings.get("exclusions")
    if exclusions is None:
        exclusions = DEFAULT_EXCLUSIONS
    exclusions = list(exclusions) + [f"{s_['name']} (not in the model)" for s_ in scope
                                     if not s_["present"] and not s_["suggest"]
                                     and s_["name"] not in ("Roof",)]

    group_list = sorted(groups.values(), key=lambda g: (g["recipe"] is not None, -g["total"]))
    for g in group_list:
        g["total"] = round(g["total"], 2)

    return {
        "region": region, "region_name": reg["name"], "currency": reg["currency"],
        "summary": {"direct": direct, "allowances": allow_total, "prelims": prelims,
                    "contingency": contingency, "overhead": overhead, "profit": profit,
                    "escalation": escalation, "tax": tax, "tax_name": reg["tax_name"], "total": total,
                    "prelims_pct": reg["prelims_pct"], "escalation_pct": reg["escalation_pct"],
                    "contingency_pct": reg.get("contingency_pct", 0),
                    "overhead_pct": reg["overhead_pct"], "profit_pct": reg["profit_pct"],
                    "tax_pct": reg["tax_pct"], "gfa": round(gfa, 1),
                    "per_m2": round(total / gfa, 2) if gfa > 1 else None,
                    "benchmark": reg.get("benchmark")},
        "accuracy": accuracy, "scope": scope, "allowances": allowances,
        "assumptions": assumptions, "exclusions": exclusions,
        "by_trade": group("trade"), "by_level": group("level"),
        "by_nrm1": by_nrm1, "by_uniformat": group_sorted("uniformat"),
        "by_stage": group_sorted("stage"),
        "boq": boq, "lines": lines, "per_element": per_element, "groups": group_list,
        "settings": {"rebar_mode": rebar_mode, "deduct_overlaps": deduct, "min_deduct_m2": min_open},
        "checks": {"elements": len(elements),
                   "priced": len(elements) - len(unclassified) - len(excluded),
                   "unclassified": unclassified, "excluded": excluded,
                   "geometry_flagged": flagged, "rebar": rb,
                   "overlaps": overlap_records, "overlap_m3": round(ov_total, 3),
                   "duplicates": [r for r in overlap_records if r["kind"] == "same type"],
                   "reconciliation": reconciliation},
    }
