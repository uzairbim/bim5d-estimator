"""Optional AI suggestions: which recipe fits an element type the rules missed.

Turned on when ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) is set on the server.
Suggestions are never applied automatically: the user reviews and accepts them.
"""
import json
import os
from typing import List

from pydantic import BaseModel

MODEL = os.environ.get("BIM5D_AI_MODEL", "claude-opus-5-5")


class Suggestion(BaseModel):
    key: str
    recipe: str          # a recipe name, or "EXCLUDE" when it should not be priced
    confidence: float    # 0..1
    reason: str


class Suggestions(BaseModel):
    suggestions: List[Suggestion]


def available():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _describe(group, el):
    q = el["qty"]
    return {
        "key": group["key"],
        "ifc_class": el["ifc_class"], "kind": el.get("kind"),
        "predefined_type": el.get("predefined"),
        "name": el["name"], "type": el.get("type"),
        "materials": el.get("materials", [])[:6],
        "classification": el.get("classification", [])[:3],
        "properties": el.get("props", {}),
        "count_in_model": group["count"],
        "size_m": {"length": q.get("length"), "width": q.get("width"), "height": q.get("height"),
                   "volume_m3": q.get("volume")},
    }


def suggest(groups, by_guid, lib):
    """groups: estimate groups (with 'key' and 'sample' guid). Returns list of dicts."""
    import anthropic  # imported here so the app runs without the package

    recipes = {}
    for name, items in lib.recipes.items():
        recipes[name] = [f"{lib.work_items.get(i['work_item'], {}).get('description', i['work_item'])}"
                         f" ({i['qty']})" for i in items]
    items = [_describe(g, by_guid[g["sample"]]) for g in groups if g["sample"] in by_guid]

    system = (
        "You help a quantity surveyor price a BIM model. Each item is a group of model elements "
        "of the same type, exported from Revit or another BIM tool as IFC. Names can be in any "
        "language (for example German or Arabic). For each item choose the single recipe from the "
        "list that best describes how it is built and priced. If the element is not built work "
        "(annotation, placeholder, existing to remain, site context) or nothing fits, answer "
        "EXCLUDE. Give a confidence from 0 to 1 and a short reason a surveyor can check. "
        "Use each item's key exactly as given."
    )
    user = ("Recipes (name: work items it produces):\n" + json.dumps(recipes, indent=1)
            + "\n\nItems to classify:\n" + json.dumps(items, indent=1, ensure_ascii=False))

    client = anthropic.Anthropic()
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low"},
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=Suggestions,
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise RuntimeError("The AI did not return suggestions for these items.")

    valid = set(recipes) | {"EXCLUDE"}
    keys = {g["key"] for g in groups}
    out = []
    for s in response.parsed_output.suggestions:
        if s.key in keys and s.recipe in valid:
            out.append({"key": s.key, "recipe": s.recipe,
                        "confidence": max(0.0, min(1.0, s.confidence)), "reason": s.reason[:300]})
    return out
