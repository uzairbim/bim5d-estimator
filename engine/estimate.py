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


NOT_MATCHED_PROPS = {"phase", "demolished"}
STRUCTURAL_LAYER = re.compile(r"concrete|beton|b[ée]ton|hormig|calcestruzzo|\brc\b|\brcc\b|cast.?in|in.?situ|"
                              r"structur|\bstb\b|خرسان", re.I)
GROUND_SLAB = re.compile(r"on grade|ground|\bsog\b|grnd|bodenplatte|ارضي|أرضي", re.I)
EXISTING_PHASE = re.compile(r"exist|bestand|existant|existente|bestaand|موجود|قائم", re.I)
EXISTING_NAME = re.compile(r"\bexisting\b|\(existing\)|\bbestand\b|\bexistant", re.I)
NO_DEMOLITION = re.compile(r"^\s*(none|keine|aucune|ninguna|geen|nessuna|لا يوجد|-)?\s*$", re.I)


def is_existing(el):
    """Built already or demolished, per the Revit phase (or 'Existing' in the type name)."""
    p = el.get("props", {})
    if not NO_DEMOLITION.match(p.get("demolished", "")):
        return True
    if p.get("phase"):
        return bool(EXISTING_PHASE.search(p["phase"]))
    return bool(EXISTING_NAME.search(f'{el.get("name", "")} {el.get("type", "")}'))


FLOOR_COVER_RECIPES = {"FLOOR_FINISH", "FLOOR_STONE", "FLOOR_WOOD", "FLOOR_SOFT"}
FINISH_FLOOR_RECIPES = FLOOR_COVER_RECIPES | {"SCREED_LAYER"}
FIRE_DOOR = re.compile(r"fire|(?<![a-z])fd ?\d|(?<![a-z])ei ?\d{2}|(?<![a-z])rated\b|brandschutz|(?<![a-z])t(30|60|90)\b|coupe.?feu|حريق", re.I)
GLASS_DOOR = re.compile(r"glass|\bglas\b|- glas|aluminium|aluminum|storefront|curtain wall|زجاج|ألمنيوم|المنيوم", re.I)

# Typical whole-building cost per m2 relative to a mid-range house (indicative ratios from
# international cost guides). The region's benchmark is for a house; other types are scaled.
BUILDING_TYPES = {
    "residential": ("Villa / house", 1.0), "apartments": ("Apartment building", 0.95),
    "office": ("Office", 1.15), "retail": ("Retail / shops", 1.0), "school": ("School", 1.0),
    "mosque": ("Mosque", 1.2), "hotel": ("Hotel (4 star)", 1.7), "hospital": ("Hospital", 2.2),
    "warehouse": ("Warehouse / light industrial", 0.5),
}


def _benchmark(base, building_type):
    if not base:
        return None
    label, f = BUILDING_TYPES.get(building_type or "residential", BUILDING_TYPES["residential"])
    if f == 1.0:
        return {**base, "type_label": label, "base_label": base["label"], "factor": 1.0}
    return {**base, "low": round(base["low"] * f, -1), "high": round(base["high"] * f, -1), "type_label": label,
            "base_label": base["label"], "factor": f, "label": f"{label}: {f:g} x {base['label']} (assumed ratio)"}
GENERIC_TYPE = re.compile(r"\bgeneric\b|\bdefault\b|placeholder|allgemein|g[ée]n[ée]rique|gen[ée]rico|"
                          r"\bstandaard\b|عام", re.I)


def _level_clusters(elements):
    """Level name for floor area. With several discipline models, a level of another model is
    matched by height to the main model's level (the architect's "Level 1" and the engineer's
    "L1 SSL" a few cm lower are the same floor). Levels of one model are never merged."""
    if not any(e.get("model") for e in elements):
        return lambda e: e.get("level") or "(no level)"
    per_model = defaultdict(dict)
    for e in elements:
        if e.get("level") and e["level"] != "(no level)":
            per_model[e.get("model")][e["level"]] = float(e.get("level_elev") or 0.0)
    if not per_model:
        return lambda e: "(no level)"
    ref_model = max(per_model, key=lambda m: (not re.search(r"struct|mep|elec|plumb", m or "", re.I),
                                              len(per_model[m])))
    ref = per_model[ref_model]
    mapping = {}
    for m, levels in per_model.items():
        for name, z in levels.items():
            if m == ref_model:
                mapping[(m, name)] = name
                continue
            best = min(ref, key=lambda r: abs(ref[r] - z))
            mapping[(m, name)] = best if abs(ref[best] - z) <= 0.6 else name
    return lambda e: mapping.get((e.get("model"), e.get("level")), e.get("level") or "(no level)")


def roof_levels(elements, recipes):
    """Levels whose slabs are roofs: above every occupied floor and with nothing built on them
    (no rooms, doors or full-height walls), as with a Revit roof slab modelled as a floor on the
    "Roof" level. Foundation levels below the building are not roofs."""
    has_slab, used, elev = set(), set(), {}
    for e in elements:
        L = e.get("level")
        if not L or L == "(no level)":
            continue
        elev.setdefault(L, float(e.get("level_elev") or 0.0))
        if e["ifc_class"] == "IfcSlab" and recipes.get(e["guid"]) in FLOOR_RECIPES:
            has_slab.add(L)
        elif e["ifc_class"] in ("IfcSpace", "IfcDoor", "IfcStair", "IfcStairFlight") or (
                e["ifc_class"] in ("IfcWall", "IfcWallStandardCase", "IfcColumn") and (e["qty"].get("height") or 0) > 2.0):
            used.add(L)
    if not used:          # a model without rooms, doors or walls: cannot tell
        return set()
    top = max(elev[L] for L in used)
    return {L for L in has_slab - used if elev[L] > top}


def _roof_twins(elements, recipes):
    """With combined discipline models, the roof slab is often in both the architect's and the
    engineer's model. The roof build-up (insulation, waterproofing, tiles) goes on once: on the
    main model's slab; the other model's overlapping roof slab keeps only its concrete."""
    models = {e.get("model") for e in elements if e.get("model")}
    if len(models) < 2:
        return set()
    levels = roof_levels(elements, recipes)
    cand = [e for e in elements if e["ifc_class"] == "IfcSlab" and e.get("bbox")
            and recipes.get(e["guid"]) in FLOOR_RECIPES
            and (e.get("predefined") == "ROOF" or e.get("level") in levels)]
    main = [e for e in cand if not re.search(r"struct|tragwerk|إنشائ|انشائ", e.get("model") or "", re.I)]
    plan = lambda b: max((b[3] - b[0]) * (b[4] - b[1]), 1e-6)
    twins = set()
    for e in cand:
        if e in main:
            continue
        b = e["bbox"]
        for m in main:
            r = m["bbox"]
            ox, oy = min(b[3], r[3]) - max(b[0], r[0]), min(b[4], r[4]) - max(b[1], r[1])
            if ox <= 0 or oy <= 0:
                continue
            if ox * oy > 0.5 * plan(b):          # the main model's slab covers this one
                twins.add(e["guid"])
            elif ox * oy > 0.5 * plan(r):        # this slab covers the main model's piece
                twins.add(m["guid"])
    return twins


def _dig_depth(el, q, ground_tops):
    """Excavation depth for a footing or ground beam: from ground level (top of the ground slab
    above it, else level 0.00) down to its underside. A footing 2 m below ground is dug 2 m,
    not just its own 600 mm. At least the element's own height; at most 6 m (deeper digs are a
    basement excavation, priced separately)."""
    h = q.get("height") or 0.0
    b = el.get("bbox")
    if not b:
        return h
    top, bottom = b[5], b[2]
    above = [g for g in ground_tops if g >= top - 0.05]
    ground = min(above) if above else max(0.0, top)
    return min(max(h, ground - bottom), 6.0)


def _below_ground(el, q, ground_tops):
    """Height of a column or wall below the ground slab (neck columns, walls on tie beams): the part
    in contact with soil, which gets bitumen coating. Ground = top of the lowest ground slab."""
    b = el.get("bbox")
    if not b or not ground_tops:
        return 0.0
    ground = min(ground_tops)
    return max(0.0, min(q.get("height") or 0.0, ground - b[2]))


def _under_a_roof(el, roofs):
    """A slab with a modelled roof (pitched roof, roof deck) above it is a ceiling, not the roof."""
    b = el.get("bbox")
    if not b:
        return False
    area = max((b[3] - b[0]) * (b[4] - b[1]), 1e-6)
    for r in roofs:
        ox = min(b[3], r[3]) - max(b[0], r[0])
        oy = min(b[4], r[4]) - max(b[1], r[1])
        if ox > 0 and oy > 0 and ox * oy > 0.5 * area and r[5] > b[5] + 0.3:
            return True
    return False


def gross_floor_area(elements, per_element):
    """Gross floor area, level by level, like an estimator measures it.

    Each level counts once, using the most complete of: structural floor slabs, floor build-ups
    (architect's model without structure) and room areas. A level counts only when something
    stands on it (rooms, doors or full-height walls), so the roof slab is not taken as a floor.
    """
    lv = {}
    level_of = _level_clusters(elements)
    for e in elements:
        L = level_of(e)
        d = lv.setdefault(L, {"slab": 0.0, "finish": 0.0, "rooms": 0.0, "used": False})
        recipe = per_element.get(e["guid"], {}).get("recipe")
        q = e["qty"]
        if e["ifc_class"] == "IfcSpace":
            if e.get("is_room", True):
                d["rooms"] += q.get("floor_area") or q.get("footprint") or 0
                d["used"] = True
        elif recipe in FLOOR_RECIPES:
            d["slab"] += q.get("footprint") or 0
        elif recipe in FINISH_FLOOR_RECIPES:
            d["finish"] += q.get("footprint") or 0
        elif e["ifc_class"] in ("IfcDoor", "IfcStair", "IfcStairFlight") or (
                e["ifc_class"] in ("IfcWall", "IfcWallStandardCase", "IfcColumn") and (q.get("height") or 0) > 2.0):
            d["used"] = True
    any_used = any(d["used"] for d in lv.values())
    out = {}
    for L, d in lv.items():
        area = max(d["slab"], d["finish"], d["rooms"])
        if area and (d["used"] or not any_used):
            out[L] = round(area, 1)
    if len(out) > 1:
        out.pop("(no level)", None)   # unplaced items would count a floor twice
    return round(sum(out.values()), 1), out


def gfa_warning(levels):
    """A level much larger than the others usually includes paving, podium or site slabs."""
    if len(levels) < 3:
        return None
    vals = sorted(levels.values())
    median = vals[len(vals) // 2]
    big = [L for L, a in levels.items() if a > 2.5 * median]
    if big:
        return (f"{', '.join(big)} is much larger than the other floors: it may include external paving, "
                "podium or site slabs. Check the floor area by level and type the correct total if needed.")
    return None


def layers_of(el):
    """Material layers for t() and has(); an element with one material (no layer set) still
    answers has("marble")."""
    return el.get("layers") or [{"name": m, "t": 0.0} for m in el.get("materials") or []]


EXTERNAL_NAME = re.compile(r"\bext\b|\bext[ .:_-]|exterior|external|outer|fa[cç]ade|parapet|aussen|außen|attika|خارجي|خارجية|دروة|حاجز السطح", re.I)


def is_external(el):
    """External wall: Revit's IsExternal when exported, otherwise the type name says so."""
    if el.get("external") is not None:
        return bool(el["external"])
    return bool(EXTERNAL_NAME.search(f'{el.get("name", "")} {el.get("type", "")}'))


def match_text(el):
    p = el.get("props", {})
    return " ".join([el.get("name", ""), el.get("type", ""), el.get("predefined", ""),
                     *el.get("materials", []), *el.get("classification", []),
                     *(str(v) for k, v in p.items() if k not in NOT_MATCHED_PROPS)])


class Library:
    """All cost data, loaded from data/. Create a new one to pick up edits."""

    def __init__(self, root=None):
        self.root = root = Path(root or DATA)
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
        # Names in other languages (data/translations.csv: kind, code, then one column per language).
        self.translations = defaultdict(dict)
        if (root / "translations.csv").exists():
            for r in _csv(root / "translations.csv"):
                for lang, text in r.items():
                    if lang not in ("kind", "code") and text:
                        self.translations[lang][f'{r["kind"]}:{r["code"]}'] = text
        regions = json.loads((root / "regions.json").read_text(encoding="utf-8"))
        self.regions = {k: v for k, v in regions.items() if not k.startswith("_")}
        self.base_rates = {r["work_item"]: r for r in _csv(root / "rates" / "base_usd.csv")}
        self.local_rates = {}
        for code, reg in self.regions.items():
            f = root / "rates" / reg.get("rates_file", f"{code}.csv")
            self.local_rates[code] = {r["work_item"]: r for r in _csv(f)} if f.is_file() else {}
        # Rate build-up: resources (labour, materials, plant) and norms per work item.
        self.resources = ({r["code"]: r for r in _csv(root / "resources.csv")}
                          if (root / "resources.csv").is_file() else {})
        self.norms = defaultdict(list)
        if (root / "norms.csv").is_file():
            for r in _csv(root / "norms.csv"):
                self.norms[r["work_item"]].append(r)
        self.prices = {}
        for code in self.regions:
            f = root / "prices" / f"{code}.csv"
            self.prices[code] = ({r["resource"]: r for r in _csv(f) if str(r.get("price", "")).strip()}
                                 if f.is_file() else {})
        self._cache = {}

    # -- classification -------------------------------------------------
    @property
    def volume_recipes(self):
        """Recipes whose quantities depend on the element's volume."""
        if "_volr" not in self._cache:
            self._cache["_volr"] = {r for r, items in self.recipes.items()
                                    if any(re.search(r"\bvolume\b", i["qty"]) for i in items)}
        return self._cache["_volr"]

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
        if el["ifc_class"] != "IfcSpace" and is_existing(el):
            return None, "excluded"    # existing / demolished: not new work
        r = self.rule_for(el)
        if r is None:
            return None, "none"
        if r["recipe"] == "EXCLUDE":   # site context, people, trees...
            return None, "excluded"
        if el["ifc_class"] == "IfcSlab" and r["recipe"] in ("FLOOR_FINISH", "SCREED_LAYER", "INSULATION_LAYER"):
            # A floor type with its finishes ("RC 200 + screed + porcelain") is still a structural slab:
            # price the concrete, and the finish layers on top of it.
            structural = sum(l.get("t") or 0 for l in el.get("layers") or []
                             if STRUCTURAL_LAYER.search(l.get("name") or ""))
            if not el.get("layers") and any(STRUCTURAL_LAYER.search(m) for m in el.get("materials") or []):
                structural = (el.get("qty") or {}).get("height") or 0     # one material, no layer set
            if structural >= 0.1:
                ground = GROUND_SLAB.search(f'{el.get("name", "")} {el.get("type", "")}')
                return ("SLAB_ON_GRADE" if ground else "RC_SLAB"), "rule"
        if el["ifc_class"] == "IfcSpace" and not el.get("is_room", True):
            return None, "excluded"    # shafts, voids, roof spaces
        return r["recipe"], "rule"

    # -- rates ------------------------------------------------------------
    def factors(self, region):
        """Exchange rate and price factors used to convert USD base prices."""
        reg = self.regions[region]
        loc = float(reg.get("location_factor", 1.0))
        return {"fx": float(reg.get("fx_per_usd", 1.0)),
                "labour": float(reg.get("labour_factor", loc)),
                "material": float(reg.get("material_factor", loc)),
                "plant": float(reg.get("plant_factor", reg.get("material_factor", loc)))}

    def price_kind(self, region, code):
        """'yours' (confirmed by the user), 'assumed' (shipped indicative price) or 'estimated'."""
        p = self.prices.get(region, {}).get(code)
        if not p:
            return "estimated"
        return "assumed" if str(p.get("source", "")).upper().startswith("ASSUMED") else "yours"

    def resource_price(self, region, code):
        """(price in local currency, is it the user's own price?)."""
        p = self.prices.get(region, {}).get(code)
        if p:
            return float(p["price"]), self.price_kind(region, code) == "yours"
        r = self.resources.get(code)
        if not r:
            return 0.0, False
        f = self.factors(region)
        return float(r["price_usd"]) * f["fx"] * f.get(r["type"], f["material"]), False

    def rate_detail(self, region, work_item, ignore_fixed=False):
        """How a unit rate is made up. Order: your fixed rate > built up from
        resources x norms (your prices where given) > converted base rate."""
        key = (region, work_item, ignore_fixed)
        if key in self._cache:
            return self._cache[key]
        local = None if ignore_fixed else self.local_rates[region].get(work_item)
        if local:
            src = local.get("source") or "your rate"
            d = {"material": float(local["material"] or 0), "labour": float(local["labour"] or 0),
                 "equipment": float(local["equipment"] or 0), "source": src, "build": [],
                 "local_share": 0.0 if str(src).upper().startswith("SAMPLE") else 1.0, "method": "fixed"}
        elif self.norms.get(work_item):
            parts = {"material": 0.0, "labour": 0.0, "equipment": 0.0}
            build, own, assumed = [], 0.0, 0.0
            for n in self.norms[work_item]:
                res = self.resources.get(n["resource"], {})
                price, mine = self.resource_price(region, n["resource"])
                pk = self.price_kind(region, n["resource"])
                cost = float(n["qty"]) * price
                kind = {"labour": "labour", "plant": "equipment"}.get(res.get("type"), "material")
                parts[kind] += cost
                own += cost if pk == "yours" else 0.0
                assumed += cost if pk == "assumed" else 0.0
                build.append({"resource": n["resource"], "name": res.get("name", n["resource"]),
                              "unit": res.get("unit", ""), "qty": float(n["qty"]), "price": round(price, 4),
                              "cost": round(cost, 4), "yours": pk == "yours", "kind": pk})
            total = sum(parts.values()) or 1.0
            share, a_share = own / total, assumed / total
            src = ("built up from your prices" if share > 0.999 else
                   f"built up: {share:.0%} your prices, {a_share:.0%} assumed" if share > 0 else
                   f"built up from assumed {a_share:.0%} / estimated prices" if a_share > 0 else
                   "SAMPLE prices (built up)")
            d = {**parts, "source": src, "build": build, "local_share": share,
                 "assumed_share": a_share, "method": "built-up"}
        else:
            base = self.base_rates.get(work_item)
            f = self.factors(region)
            if not base:
                d = {"material": 0.0, "labour": 0.0, "equipment": 0.0, "source": "NO RATE",
                     "build": [], "local_share": 0.0, "method": "none"}
            else:
                d = {"material": float(base["material"]) * f["fx"] * f["material"],
                     "labour": float(base["labour"]) * f["fx"] * f["labour"],
                     "equipment": float(base["equipment"]) * f["fx"] * f["plant"],
                     "source": (base.get("source") or "base") + " (converted)", "build": [],
                     "local_share": 0.0, "method": "base"}
        self._cache[key] = d
        return d

    def rate(self, region, work_item):
        """Unit rate in the region's currency: (material, labour, equipment, source)."""
        d = self.rate_detail(region, work_item)
        return d["material"], d["labour"], d["equipment"], d["source"]


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
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("max", "min")
            and 1 < len(node.args) <= 4 and not node.keywords):
        vals = [evaluate(a, env, layers) for a in node.args]
        return max(vals) if node.func.id == "max" else min(vals)
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
FLOOR_RECIPES = {"RC_SLAB", "SLAB_ON_GRADE", "TIMBER_FLOOR", "RIBBED_SLAB"}

# Who keeps the shared volume when two elements overlap (lower number keeps it).
# Follows normal measurement practice: slabs measured through, columns stop at the
# slab soffit, beams measured below the slab, walls between frame members.
# Steel always keeps its weight; the concrete around it is reduced instead.
OVERLAP_PRIORITY = {
    "STEEL_MEMBER": -1, "STEEL_PLATE": -1,
    "RC_PILE": 0, "RC_FOOTING": 0,
    "SLAB_ON_GRADE": 1, "RC_SLAB": 1, "RIBBED_SLAB": 1, "ROOF_RC": 1, "TIMBER_FLOOR": 1, "ROOF_LIGHT": 1,
    "RC_COLUMN": 2, "RC_BEAM": 3, "RC_WALL": 4, "STAIR_RC": 4,
    "CAVITY_WALL": 5, "BLOCK_WALL": 5, "BRICK_WALL": 5, "THERMAL_BLOCK_WALL": 5, "STONE_WALL": 5, "DRYWALL": 6,
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


# Commonly forgotten items: (name, work item codes, allowance name, allowance %, note when it
# normally sits elsewhere). A trailing * matches a code prefix.
CHECKLIST = [
    ("Excavation and backfill", ["EARTH-EXC", "BACKFILL"], "Earthworks allowance", 2, None),
    ("Blinding under foundations", ["BLINDING"], "Blinding allowance", 0.3, None),
    ("Anti-termite treatment", ["TERMITE"], "Anti-termite treatment allowance", 0.2, None),
    ("Hardcore / sub-base and DPM", ["HARDCORE", "VAPOR"], "Sub-base and DPM allowance", 0.5, None),
    ("Reinforcement", ["RBR", "MESH"], None, None, None),
    ("Formwork (incl. slab edges)", ["FRM-*"], None, None, None),
    ("Lintels over openings", ["LINTEL"], "Lintels allowance", 0.5, None),
    ("Wall plaster", ["PLS", "EXT-RND"], "Plaster allowance", 3, None),
    ("Paint to walls", ["PNT", "EXT-PNT"], "Wall painting allowance", 2.5, None),
    ("Paint to ceilings", ["CLG-PNT"], "Ceiling painting allowance", 1, None),
    ("Floor finishes", ["FLR-TIL", "FLR-WOOD", "FLR-HRD", "FLR-MRB", "FLR-SOFT"], "Floor finishes allowance", 5, None),
    ("Skirting", ["FLR-SKRT"], "Skirting allowance", 0.5, None),
    ("Wall tiling in wet areas", ["WAL-TILE"], "Wall tiling allowance", 1.5, None),
    ("Waterproofing (roofs and wet areas)", ["ROF-WP", "WPF-WET"], "Waterproofing allowance", 1.5, None),
    ("Window sills and sealant", ["SILL", "SEALANT"], None, None, None),
    ("Doors with frames and ironmongery", ["DOR"], None, None, None),
    ("Handrails and balustrades", ["RAIL"], None, None, None),
    ("Protective paint to steelwork", ["STL-PNT"], None, None, None),
    ("Pipe and duct insulation", ["PIP-INS", "DUCT-INS"], None, None, None),
    ("Bitumen coating to foundations", ["BIT-COAT"], "Bitumen coating allowance", 0.3, None),
    ("Thermal insulation of external walls (energy code)", ["INS-WAL", "MAS-TBLK"], "Wall insulation allowance", 1, None),
    ("Water tanks (ground and roof)", ["TANK-UG", "TANK-ROOF"], "Water tanks allowance", 1, None),
    ("Sewer connection or septic tank", ["MANHOLE", "TANK-UG"], "Drainage connection allowance", 0.5, None),
    ("Boundary wall, gates and fencing", [], "Boundary wall allowance", 2, None),
    ("Testing and commissioning of services", [], "Testing and commissioning allowance", 1, None),
    ("Fire stopping of service penetrations", [], "Fire stopping allowance", 0.3, None),
    ("Scaffolding, temporary works, site facilities", [], None, None, "Normally in preliminaries"),
    ("Final cleaning and handover", [], None, None, "Normally in preliminaries"),
]


_STRUCTURAL = {"IfcColumn": "col", "IfcBeam": "beam", "IfcFooting": "ftg", "IfcSlab": "slab", "IfcWall": "wall",
               "IfcWallStandardCase": "wall", "IfcStair": "stair", "IfcStairFlight": "stair", "IfcPile": "pile"}


def _same_in_two_models(elements, cls):
    """An element drawn in two discipline models (structural columns kept in the architect's model)
    is counted once: the copy in the structure model wins. Returns the duplicate records."""
    if not any(e.get("model") for e in elements):
        return []
    seen, out = {}, []
    order = sorted(elements, key=lambda e: 0 if re.search(r"struct|tragwerk|إنشائ|انشائ", e.get("model") or "", re.I) else 1)
    for e in order:
        fam = _STRUCTURAL.get(e["ifc_class"])
        if not fam or not e.get("bbox") or not cls[e["guid"]][0]:
            continue
        k = (fam, *(round(x / 0.05) for x in e["bbox"]))
        first = seen.get(k)
        if first and first["model"] != e.get("model"):
            out.append({"a": first["guid"], "b": e["guid"], "volume": 0, "loser": e["guid"],
                        "kind": "in two models"})
            cls[e["guid"]] = (None, "excluded")
        elif not first:
            seen[k] = e
    return out


def _deductions(elements, recipes, deduct):
    """Overlap volume each element gives up, and the overlap records."""
    give = defaultdict(float)
    records, seen = [], set()
    if not deduct:
        return give, records
    vol_of = {e["guid"]: (e.get("qty") or {}).get("volume") or 0.0 for e in elements}
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
                # Same kind crossing at a junction (tie beams, walls at a corner) is normal; it is a
                # likely duplicate only when one element sits almost entirely inside the other.
                small = min(vol_of.get(pair[0]) or 0, vol_of.get(pair[1]) or 0)
                dup = ra == rb and small > 0 and vol >= 0.6 * small
                loser, kind = pair[1], "same type" if dup else "overlap"
            else:
                loser, kind = (pair[1] if pa < pb else pair[0]), "overlap"
            give[loser] += vol
            records.append({"a": pair[0], "b": pair[1], "volume": vol, "loser": loser, "kind": kind})
    return give, records


# Measurement standards: how openings are treated in masonry and finishes.
#   masonry_min   openings up to this size (m2) are not deducted from masonry
#   finish_min    openings up to this size are not deducted from plaster / paint
#   one_face_max  openings above finish_min and up to this size are deducted from one face only
STANDARDS = {
    "NRM2": {"label": "RICS NRM2 (UK, Gulf, international)", "masonry_min": 0.5, "finish_min": 0.5, "one_face_max": 0.0},
    "POMI": {"label": "POMI (Gulf / international contracts)", "masonry_min": 0.5, "finish_min": 0.5, "one_face_max": 0.0},
    "IS1200": {"label": "IS 1200 (India)", "masonry_min": 0.1, "finish_min": 0.5, "one_face_max": 3.0},
    "EXACT": {"label": "Exact net quantities (deduct every opening)", "masonry_min": 0.0, "finish_min": 0.0, "one_face_max": 0.0},
}
MASONRY = {"BLOCK_WALL", "BRICK_WALL", "CAVITY_WALL", "THERMAL_BLOCK_WALL", "STONE_WALL"}
INSULATED = re.compile(r"chilled|heating|hot water|hydronic|condens|refrig|supply air|return air|outside air|"
                       r"fresh air|zuluft|abluft|kälte|heiz|kaltwasser", re.I)


def _opening_areas(el):
    out = []
    for o in el.get("openings") or []:
        out.append(o[0] if isinstance(o, (list, tuple)) else float(o))
    return out


def _env(el, give, rule, ctx):
    """Quantities used by the formulas, after overlap and opening rules, plus
    context flags (external wall, rooms in use, host wall of a window...)."""
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
    areas = _opening_areas(el)
    small_m = sum(a for a in areas if a <= rule["masonry_min"])
    small_f = sum(a for a in areas if a <= rule["finish_min"])
    mid_f = sum(a for a in areas if rule["finish_min"] < a <= rule["one_face_max"])
    side = q.get("side", 0.0)
    q["openings_small"] = small_m
    q["side_m"] = side + small_m                       # masonry face measured to the rule
    q["footprint_m"] = q.get("footprint", 0.0) + small_m
    q["finish1"] = side + small_f                      # one finished face
    q["finish2"] = 2 * side + 2 * small_f + mid_f      # both faces (IS 1200: mid openings one face)
    # context flags
    q["ext"] = 1.0 if is_external(el) else 0.0
    q["is_beam"] = 1.0 if el["ifc_class"] == "IfcBeam" else 0.0
    if el["ifc_class"] == "IfcDoor":
        text = f'{el.get("name", "")} {el.get("type", "")} {" ".join(el.get("materials") or [])}'
        q["fire"] = 1.0 if FIRE_DOOR.search(text) else 0.0
        q["glass_door"] = 1.0 if GLASS_DOOR.search(text) else 0.0
    q["dig"] = _dig_depth(el, q, ctx.get("ground_tops", ()))
    q["below_ground"] = _below_ground(el, q, ctx.get("ground_tops", ()))
    q["is_roof"] = 1.0 if (el["ifc_class"] == "IfcSlab" and (el.get("predefined") == "ROOF"
                                                              or el.get("level") in ctx.get("roof_levels", ()))
                            and not _under_a_roof(el, ctx.get("roofs", ()))
                            and el["guid"] not in ctx.get("roof_twins", ())) else 0.0
    q["rooms_on"] = ctx["rooms_on"]
    q["lintels_modeled"] = ctx.get("lintels", 0.0)
    q["plates_modeled"] = ctx.get("plates", 0.0)
    q["cables_modeled"] = ctx.get("cables", 0.0)
    host = ctx["by_guid"].get(el.get("host") or "")
    if host is not None:
        q["host_masonry"] = 1.0 if ctx["recipes"].get(host["guid"]) in MASONRY else 0.0
        q["host_t"] = host["qty"].get("width", 0.2)
    else:
        q["host_masonry"], q["host_t"] = 0.0, 0.2
    text = " ".join(str(v) for v in (el.get("props") or {}).values()) + " " + el.get("name", "")
    q["insulated"] = 1.0 if INSULATED.search(text) else 0.0
    if el["ifc_class"] == "IfcSpace":
        mods = [ctx["recipes"].get(g) for g in el.get("room_modeled") or []]
        q["has_floor"] = 1.0 if FLOOR_COVER_RECIPES & set(mods) else 0.0
        q["has_ceiling"] = 1.0 if "CEILING" in mods else 0.0
        # wall tiles modelled as coverings in this room: the room adds only the rest
        q["wall_tiles_modeled"] = sum(ctx["by_guid"][g]["qty"].get("area") or 0 for g in el.get("room_wall_covers") or []
                                      if g in ctx["by_guid"] and ctx["recipes"].get(g) == "WALL_TILE")
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
    include_ffe = bool(settings.get("include_loose_ffe"))
    deduct = settings.get("deduct_overlaps", True) is not False
    std_code = settings.get("standard") or reg.get("standard") or "NRM2"
    rule = dict(STANDARDS.get(std_code, STANDARDS["NRM2"]))
    if settings.get("min_deduct_m2") is not None:      # user override of the threshold
        rule["masonry_min"] = rule["finish_min"] = float(settings["min_deduct_m2"])
    min_open = rule["masonry_min"]
    adjust = settings.get("adjustments") or {}

    # classify first (overlap rules depend on how each element is priced)
    cls = {e["guid"]: lib.classify(e, mappings) for e in elements}
    # Rooms with exactly the same shape (badly bounded rooms in Revit) would count finishes twice.
    seen_rooms, dup_rooms = {}, []
    for e in elements:
        if e["ifc_class"] == "IfcSpace" and cls[e["guid"]][0] and e.get("bbox"):
            k = tuple(round(x, 2) for x in e["bbox"])
            if k in seen_rooms:
                dup_rooms.append({"a": seen_rooms[k], "b": e["guid"], "volume": 0, "loser": e["guid"],
                                  "kind": "same room shape"})
                cls[e["guid"]] = (None, "excluded")
            else:
                seen_rooms[k] = e["guid"]
    # A container (curtain wall, roof, stair, assembly) whose parts are priced is not priced again.
    parents = {e.get("assembly") for e in elements if e.get("assembly") and cls[e["guid"]][0]}
    for e in elements:
        if e["guid"] in parents and cls[e["guid"]][0]:
            cls[e["guid"]] = (None, "excluded")
    dup_models = _same_in_two_models(elements, cls)
    recipes = {g: r for g, (r, _) in cls.items()}
    give, overlap_records = _deductions(elements, recipes, deduct)
    overlap_records += dup_rooms + dup_models
    n_rooms = sum(1 for e in elements if e["ifc_class"] == "IfcSpace" and recipes.get(e["guid"]))
    finishes_from = settings.get("finishes_from") or "auto"
    has_walls = any(e["ifc_class"] in ("IfcWall", "IfcWallStandardCase", "IfcCurtainWall") for e in elements)
    rooms_on = 1.0 if (finishes_from == "rooms" or (finishes_from == "auto" and n_rooms >= 3 and has_walls)) else 0.0
    if not rooms_on:   # rooms switched off: don't price room finishes either
        for e in elements:
            if e["ifc_class"] == "IfcSpace" and recipes.get(e["guid"]):
                cls[e["guid"]] = (None, "excluded")
                recipes[e["guid"]] = None
    ctx = {"rooms_on": rooms_on, "recipes": recipes, "by_guid": {e["guid"]: e for e in elements},
           "roof_levels": roof_levels(elements, recipes),
           "ground_tops": sorted(e["bbox"][5] for e in elements if e.get("bbox") and recipes.get(e["guid"]) == "SLAB_ON_GRADE"),
           "roofs": [e["bbox"] for e in elements if e.get("bbox") and recipes.get(e["guid"]) in ("ROOF_RC", "ROOF_LIGHT")],
           "roof_twins": _roof_twins(elements, recipes),
           "lintels": 1.0 if "LINTEL_ELEMENT" in set(recipes.values()) else 0.0,
           # connection plates in the model: no extra allowance on member weight
           "plates": 1.0 if "STEEL_PLATE" in set(recipes.values()) else 0.0,
           "cables": 1.0 if "CABLE" in set(recipes.values()) else 0.0}

    lines, per_element, groups = [], {}, {}
    unclassified, flagged, excluded = [], [], []
    modeled_rebar_kg = ratio_rebar_kg = 0.0
    ffe_outside, ffe_count = 0.0, 0
    recon = []

    for el in elements:
        recipe, source = cls[el["guid"]]
        q0 = el["qty"]
        # Flag only rough box estimates that the price depends on. A volume taken from the
        # authoring tool (check 3) is reliable; doors priced by count do not need a volume.
        if q0.get("check") == 1.0 and recipe in lib.volume_recipes:
            flagged.append(el["guid"])
        key = group_key(el)
        g = groups.setdefault(key, {"key": key, "kind": el.get("kind") or el["ifc_class"],
                                    "type": key.split("|", 1)[1], "count": 0, "total": 0.0,
                                    "recipe": recipe, "source": source, "guids": [],
                                    "sample": el["guid"], "materials": el.get("materials", [])[:4],
                                    "adjust": adjust.get(key)})
        g["count"] += 1
        g["guids"].append(el["guid"])
        au = el.get("authored") or {}
        av = au.get("volume")
        if not av and au.get("volume_qto") and q0.get("volume"):
            # IFC base quantities are often written in the wrong unit (x1000);
            # only use them when they are of the same order as the measured volume.
            ratio = q0["volume"] / au["volume_qto"]
            av = au["volume_qto"] if 0.2 < ratio < 5 else None
        if av and q0.get("volume") and recipe is not None and q0.get("check") == 0:
            recon.append((el["guid"], q0["volume"], av))
        if recipe is None:
            (excluded if source == "excluded" else unclassified).append(el["guid"])
            per_element[el["guid"]] = {"recipe": None, "source": source, "total": 0.0}
            continue
        env = _env(el, give, rule, ctx)
        adj = adjust.get(key) or {}
        factor = float(adj.get("factor") or 1.0)
        grp = lib.groups.get(recipe, {})
        el_total = 0.0
        for item in lib.recipes.get(recipe, []):
            qty = evaluate(item["_expr"], env, layers_of(el)) * factor
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
            if opt == "loose_ffe" and not include_ffe:
                rd0 = lib.rate_detail(region, item["work_item"])
                ffe_outside += qty * (rd0["material"] + rd0["labour"] + rd0["equipment"])
                ffe_count += 1
                continue
            waste = float(item["waste_pct"] or 0)
            qty_w = qty * (1 + waste / 100)
            rd = lib.rate_detail(region, item["work_item"])
            mat, lab, eqp, src = rd["material"], rd["labour"], rd["equipment"], rd["source"]
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
                "rate_source": src, "local_share": round(rd["local_share"], 3),
                "assumed_share": round(rd.get("assumed_share", 0.0), 3),
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

    # Items measured by hand ("virtual takeoff"): work that is not in the model.
    for i, m in enumerate(settings.get("manual_items") or []):
        qty = float(m.get("qty") or 0)
        if qty <= 0:
            continue
        code = (m.get("work_item") or "").strip()
        wi = lib.work_items.get(code, {})
        if wi and not m.get("rate"):
            mat, lab, eqp, src = lib.rate(region, code)
        else:
            mat, lab, eqp, src = float(m.get("rate") or 0), 0.0, 0.0, "your rate"
        unit_rate = mat + lab + eqp
        lines.append({
            "guid": f"manual-{i}", "element": m.get("description") or wi.get("description") or "Manual item",
            "ifc_class": "Manual", "level": m.get("level") or "(not in model)", "recipe": "MANUAL",
            "work_item": code or f"MAN-{i + 1}",
            "description": m.get("description") or wi.get("description") or "Manual item",
            "trade": wi.get("trade") or m.get("trade") or "Manual items",
            "unit": wi.get("unit") or m.get("unit") or "item", "formula": "measured by hand",
            "net_qty": round(qty, 4), "waste_pct": 0.0, "qty": round(qty, 4),
            "material": round(qty * mat, 2), "labour": round(qty * lab, 2), "equipment": round(qty * eqp, 2),
            "rate": round(unit_rate, 2), "amount": round(qty * unit_rate, 2), "rate_source": src,
            "local_share": 1.0 if src == "your rate" else lib.rate_detail(region, code)["local_share"] if wi else 1.0,
            "nrm1": m.get("nrm1") or "8 External works" if "extern" in (m.get("description") or "").lower() else (m.get("nrm1") or "Manual items"),
            "uniformat": "Manual items", "stage": "9 Other",
        })

    # Resource summary (bill of materials): totals of labour, materials and plant behind the
    # built-up rates, for procurement and to see which prices drive the cost.
    res_tot = {}
    for l in lines:
        if l.get("recipe") == "MANUAL" and l.get("rate_source") == "your rate":
            continue
        rd = lib.rate_detail(region, l["work_item"])
        for b in rd.get("build") or []:
            r = res_tot.setdefault(b["resource"], {"resource": b["resource"], "name": b["name"], "unit": b["unit"],
                                                  "qty": 0.0, "cost": 0.0, "price": b["price"], "kind": b.get("kind")})
            r["qty"] += l["qty"] * b["qty"]
            r["cost"] += l["qty"] * b["cost"]
    tot_direct = sum(l["amount"] for l in lines) or 1.0
    resources = sorted(({**r, "qty": round(r["qty"], 3), "cost": round(r["cost"], 2),
                         "share": round(r["cost"] / tot_direct, 4)} for r in res_tot.values()),
                       key=lambda r: -r["cost"])

    # Bill of quantities: one row per work item.
    boq = {}
    for l in lines:
        b = boq.setdefault(l["work_item"], {k: l[k] for k in
                                            ("work_item", "description", "trade", "unit", "rate", "rate_source")})
        b["qty"] = b.get("qty", 0) + l["qty"]
        b["amount"] = b.get("amount", 0) + l["amount"]
        b["elements"] = b.get("elements", 0) + 1
    ar = lib.translations.get("ar", {})
    for b in boq.values():
        b["qty"], b["amount"] = round(b["qty"], 3), round(b["amount"], 2)
        b["description_ar"] = ar.get(f'work_item:{b["work_item"]}', "")
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
    gfa, gfa_levels = gross_floor_area(elements, per_element)
    if settings.get("gfa_m2"):
        gfa = float(settings["gfa_m2"])

    # ---- scope coverage and allowances --------------------------------------
    scope = []
    for name, prefixes, allowance, pct in SCOPE:
        cost = sum(v for k, v in by_nrm1.items() if any(k.startswith(p) for p in prefixes))
        scope.append({"name": name, "cost": round(cost, 2), "present": cost > 0,
                      "suggest": None if cost > 0 or not allowance else
                      {"name": allowance, "kind": "pct", "value": pct}})
    # Items estimators often forget: is each one priced, covered by an allowance, or missing?
    priced_codes = {l["work_item"] for l in lines}
    allow_names = " ".join(a.get("name", "") for a in settings.get("allowances") or []).lower()
    checklist = []
    for name, codes, allowance, pct, note in CHECKLIST:
        hit = sorted(c for c in priced_codes if any(c == x or (x.endswith("*") and c.startswith(x[:-1])) for x in codes))
        cost = round(sum(l["amount"] for l in lines if l["work_item"] in hit), 2)
        status = ("priced" if cost > 0 else
                  "allowance" if allowance and allowance.split(" (")[0].lower() in allow_names else
                  "note" if note else "missing")
        checklist.append({"name": name, "status": status, "cost": cost, "codes": hit, "note": note,
                          "suggest": {"name": allowance, "kind": "pct", "value": pct} if allowance and status == "missing" else None})
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
    user_cost = sum(l["amount"] * l.get("local_share", 0.0) for l in lines)
    assumed_cost = sum(l["amount"] * l.get("assumed_share", 0.0) for l in lines)
    user_share = user_cost / direct if direct else 0.0
    assumed_share = assumed_cost / direct if direct else 0.0
    estimated_share = max(0.0, 1.0 - user_share - assumed_share)
    sample_share = 1.0 - user_share            # not confirmed by the user
    unpriced_share = len(unclassified) / max(len(elements), 1)
    flagged_cost = sum(per_element[g_]["total"] for g_ in flagged if g_ in per_element)
    missing = [s_["name"] for s_ in scope if not s_["present"] and s_["name"] in
               ("MEP services", "Internal finishes", "Substructure")]
    covered = {a.get("name", "").split(" ")[0] for a in allowances}
    missing_uncovered = [m for m in missing if m.split(" ")[0] not in covered and
                         not any(m.split(" ")[0].lower() in a.get("name", "").lower() for a in allowances)]
    # Placeholder types ("Generic - 200mm", "Default Floor"): the specification is not decided yet.
    gen = [g for g in groups.values() if g["recipe"] and GENERIC_TYPE.search(g["type"] or "")]
    generic_cost = sum(g["total"] for g in gen)
    generic = {"cost": round(generic_cost, 2), "share": round(generic_cost / direct, 3) if direct else 0,
               "count": sum(g["count"] for g in gen),
               "types": [g["type"] for g in sorted(gen, key=lambda g: -g["total"])[:6]]}
    generic_high = generic["share"] > 0.15

    reasons, reasons_t = [], []

    def why(template, **vals):
        """English text for Excel / report, plus the template so the app can translate it."""
        reasons.append(template.format(**vals))
        reasons_t.append([template, {k: str(v) for k, v in vals.items()}])

    pct = lambda x: f"{x:.0%}"
    if estimated_share > 0.5:
        cls_ = 5
        why("{p} of the cost uses prices converted from US levels. Open Prices & rates and enter local prices "
            "(start with the key ones).", p=pct(estimated_share))
    elif user_share < 0.5 or missing_uncovered or unpriced_share > 0.1 or generic_high:
        cls_ = 4
        if generic_high:
            why("{p} of the cost is on generic placeholder types ({types}). Confirm what they are built of in Mapping.",
                p=pct(generic["share"]), types=", ".join(generic["types"][:3]))
        if user_share < 0.5:
            why("{p} of the cost uses assumed indicative prices (prices change daily). "
                "Confirm the key prices in Prices & rates to reach Class 3.", p=pct(assumed_share))
        if missing_uncovered:
            why("Not in the model and no allowance yet: {items}.", items=", ".join(missing_uncovered))
        if unpriced_share > 0.1:
            why("{p} of elements are not priced. Use Mapping.", p=pct(unpriced_share))
    else:
        cls_ = 3
        if sample_share > 0:
            why("{p} of the cost still uses estimated prices.", p=pct(sample_share))
        if direct and flagged_cost / direct > 0.05:
            why("More than 5% of the cost is on shapes that could not be measured exactly.")
        if reconciliation["share"] is not None and reconciliation["share"] < 0.9:
            why("Less than 90% of quantities agree with the model's own values. Check the outliers.")
        if not reasons and settings.get("rates_verified"):
            cls_ = 2
    if cls_ > 2 and not reasons:
        why("Confirm your rates are current market prices (tick 'Rates checked') to reach Class 2.")
    label, lo_pct, hi_pct = ACCURACY[cls_]
    accuracy = {"class": cls_, "label": label, "low_pct": lo_pct, "high_pct": hi_pct,
                "low": round(total * (1 + lo_pct), -2), "high": round(total * (1 + hi_pct), -2),
                "reasons": reasons, "reasons_t": reasons_t, "sample_rate_share": round(sample_share, 3),
                "user_price_share": round(user_share, 3), "assumed_price_share": round(assumed_share, 3),
                "estimated_price_share": round(estimated_share, 3)}

    # ---- assumptions & exclusions -------------------------------------------------
    ov_total = sum(r["volume"] for r in overlap_records)
    rb = {"modeled_kg": round(modeled_rebar_kg), "ratio_kg": round(ratio_rebar_kg), "mode": rebar_mode}
    assumptions, assumptions_t = [], []

    def assume(tpl, **vals):
        """English text plus its template, so the app and the report can show it in any language."""
        vals = {k: str(v) for k, v in vals.items()}
        assumptions.append(tpl.format(**vals))
        assumptions_t.append([tpl, vals])

    assume("Quantities are measured from the 3D model. Work that is not modelled is excluded "
           "unless it is listed as an allowance.")
    assume("Reinforcement is taken from the modelled bars." if rebar_mode == "modeled" else
           "Reinforcement is an allowance by ratio (kg per m³ of concrete) until bar schedules are available.")
    assume("Openings up to {v} m² are not deducted from masonry and finishes (NRM2 practice).", v=f"{min_open:g}")
    if deduct:
        assume("Overlaps between elements are deducted once ({n} overlaps, {v} m³): slabs measured through, "
               "columns to slab soffit, beams below slab, walls between frame members.",
               n=len(overlap_records), v=f"{ov_total:.2f}")
    else:
        assume("Overlaps between elements are NOT deducted.")
    assume("Waste allowances are included in quantities as shown per item.")
    assume("Preliminaries {p}%, contingency {c}%, overhead {o}%, profit {r}%, escalation {e}%.",
           p=f"{reg['prelims_pct']:g}", c=f"{reg.get('contingency_pct', 0):g}", o=f"{reg['overhead_pct']:g}",
           r=f"{reg['profit_pct']:g}", e=f"{reg['escalation_pct']:g}")
    assume("{tax} at {v}% is included in the total.", tax=reg["tax_name"], v=f"{reg['tax_pct']:g}")
    assume("Prices in {cur} at the date of the rates used.", cur=reg["currency"])
    if sample_share > 0:
        assume("Prices: {a} confirmed by you, {b} assumed indicative market prices (late 2026, not quotations), "
               "{c} estimated from US price levels.",
               a=f"{user_share:.0%}", b=f"{assumed_share:.0%}", c=f"{estimated_share:.0%}")
    models = sorted({e["model"] for e in elements if e.get("model")})
    if len(models) > 1:
        n_two = len(dup_models) + sum(1 for e in elements if len(e.get("in_models") or []) > 1)
        if n_two:
            assume("Combined discipline models: {models}. {n} elements drawn in two models are counted once "
                   "(structure model kept). Overlaps are deducted within each model, not between models.",
                   models=", ".join(models), n=n_two)
        else:
            assume("Combined discipline models: {models}. Overlaps are deducted within each model, "
                   "not between models.", models=", ".join(models))
    if any(r == "STEEL_MEMBER" for r in recipes.values()):
        assume("Structural steel weight = member volume x 7,850 kg/m3 (connection plates as modelled)."
               if ctx.get("plates") else
               "Structural steel weight = member volume x 7,850 kg/m3 + 10% for connections (plates, bolts, "
               "cleats) not in the model.")
    n_points = sum(1 for r in recipes.values() if r in ("OUTLET", "LIGHT"))
    if n_points and not ctx.get("cables"):
        assume("Cables are not modelled: conduit and wiring are priced per point ({n} light, socket and switch "
               "points, about 10 m each).", n=n_points)
    n_split = sum(1 for r in recipes.values() if r == "AC_SPLIT")
    if n_split:
        assume("{n} split air conditioners priced complete with their outdoor unit, copper piping and drain; "
               "split outdoor units drawn in the model are not priced again.", n=n_split)
    flat = sum(1 for e in elements if e["ifc_class"] == "IfcSpace" and (e.get("qty") or {}).get("height_assumed"))
    if flat:
        assume("{n} rooms were exported as a 2D outline without a height: 3.0 m assumed for their wall finishes. "
               "Export rooms in 3D (Revit IFC options) or check these rooms.", n=flat)
    n_existing = sum(1 for e in elements if e["ifc_class"] != "IfcSpace" and is_existing(e)
                     and not (mappings and mappings.get(group_key(e))))
    if n_existing:
        assume("{n} elements are marked as existing or demolished in the model (Revit phase or 'Existing' in "
               "the type name) and are not priced as new work. Map them in Mapping if they are new.", n=n_existing)
    if ffe_count:
        assume("Loose furniture ({n} items, about {v} {cur}) is excluded: it is normally the client's separate "
               "FF&E budget. Built-in joinery is included.", n=ffe_count, v=f"{ffe_outside:,.0f}", cur=reg["currency"])
    for a_ in settings.get("assumptions") or []:
        if a_:
            assumptions.append(a_)
            assumptions_t.append([a_, {}])
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
                    "ffe_outside": round(ffe_outside, 2), "ffe_count": ffe_count,
                    "prelims_pct": reg["prelims_pct"], "escalation_pct": reg["escalation_pct"],
                    "contingency_pct": reg.get("contingency_pct", 0),
                    "overhead_pct": reg["overhead_pct"], "profit_pct": reg["profit_pct"],
                    "tax_pct": reg["tax_pct"], "gfa": round(gfa, 1), "gfa_by_level": gfa_levels,
                    "gfa_warning": None if settings.get("gfa_m2") else gfa_warning(gfa_levels),
                    "per_m2": round(total / gfa, 2) if gfa > 1 else None,
                    "benchmark": _benchmark(reg.get("benchmark"), settings.get("building_type")),
                    "building_type": settings.get("building_type") or "residential"},
        "accuracy": accuracy, "scope": scope, "allowances": allowances, "checklist": checklist,
        "standard": {"code": std_code, **rule}, "rooms_on": bool(rooms_on), "rooms": n_rooms,
        "assumptions": assumptions, "assumptions_t": assumptions_t, "exclusions": exclusions,
        "by_trade": group("trade"), "by_level": group("level"),
        "by_nrm1": by_nrm1, "by_uniformat": group_sorted("uniformat"),
        "by_stage": group_sorted("stage"),
        "translations_ar": {k: v for k, v in ar.items() if k.startswith(("trade:", "unit:"))},
        "boq": boq, "lines": lines, "per_element": per_element, "groups": group_list,
        "resources": resources,
        "settings": {"rebar_mode": rebar_mode, "deduct_overlaps": deduct, "min_deduct_m2": min_open},
        "checks": {"elements": len(elements),
                   "priced": len(elements) - len(unclassified) - len(excluded),
                   "unclassified": unclassified, "excluded": excluded,
                   "geometry_flagged": flagged, "rebar": rb,
                   "overlaps": overlap_records, "overlap_m3": round(ov_total, 3),
                   "duplicates": [r for r in overlap_records if r["kind"] in ("same type", "same room shape", "in two models")],
                   "generic": generic,
                   "reconciliation": reconciliation},
    }
