"""A simple automatic 4D sequence and cash flow from a priced model.

Work is split into activities = (stage, level). Stages follow the usual order of a
building: substructure -> frame & floors (level by level) -> roof -> envelope ->
services -> finishes -> fit-out. A stage on a level starts when the previous stage
on that level is done and the same crew has finished the level below.
Durations are proportional to cost, then scaled to the project duration.
This is a planning aid, not a replacement for a real programme.
"""
from collections import defaultdict

STAGES = ["1 Substructure", "2 Frame & floors", "3 Roof", "4 Envelope & walls",
          "5 Services", "6 Finishes", "7 Fit-out", "9 Other"]
PREV = {"2 Frame & floors": "1 Substructure", "4 Envelope & walls": "2 Frame & floors",
        "5 Services": "4 Envelope & walls", "6 Finishes": "5 Services",
        "7 Fit-out": "6 Finishes", "9 Other": "7 Fit-out"}
WEEKS_PER_MONTH = 52 / 12


def build(elements, est, months=12):
    months = max(float(months or 12), 1)
    weeks_total = months * WEEKS_PER_MONTH
    pe = est["per_element"]
    elev = {}
    acts = defaultdict(lambda: {"cost": 0.0, "guids": []})
    for e in elements:
        p = pe.get(e["guid"])
        if not p or not p.get("recipe"):
            continue
        stage = p.get("stage", "9 Other")
        level = "All levels" if stage in ("1 Substructure", "3 Roof") else e["level"]
        elev[e["level"]] = e.get("level_elev", 0.0)
        a = acts[(stage, level)]
        a["cost"] += p["total"]
        a["guids"].append(e["guid"])
    if not acts:
        return {"activities": [], "months": [], "elements": {}, "weeks": weeks_total}

    levels = sorted({lv for (_, lv) in acts if lv != "All levels"}, key=lambda l: (elev.get(l, 0), l))
    total = sum(a["cost"] for a in acts.values()) or 1.0
    dur = {k: max(a["cost"] / total, 0.01) for k, a in acts.items()}  # relative durations

    finish = {}
    order = []

    def place(key, earliest):
        start = earliest
        finish[key] = start + dur[key]
        order.append((key, start))

    # substructure
    if ("1 Substructure", "All levels") in acts:
        place(("1 Substructure", "All levels"), 0.0)
    sub_end = finish.get(("1 Substructure", "All levels"), 0.0)

    def stage_finish(stage, level):
        """Finish of `stage` on `level`, falling back to earlier stages."""
        s = stage
        while s:
            if (s, level) in finish:
                return finish[(s, level)]
            s = PREV.get(s)
        return sub_end

    for stage in ["2 Frame & floors", "4 Envelope & walls", "5 Services", "6 Finishes", "7 Fit-out", "9 Other"]:
        crew_free = 0.0
        for lv in levels:
            key = (stage, lv)
            if key not in acts:
                continue
            prev = PREV.get(stage)
            ready = max(stage_finish(prev, lv) if prev else sub_end, crew_free)
            if stage == "4 Envelope & walls" or stage == "5 Services":
                pass
            place(key, ready)
            crew_free = finish[key]
        if stage == "2 Frame & floors" and ("3 Roof", "All levels") in acts:
            frame_end = max([finish[k] for k in finish if k[0] == "2 Frame & floors"] or [sub_end])
            place(("3 Roof", "All levels"), frame_end)

    makespan = max(finish.values()) or 1.0
    scale = weeks_total / makespan
    activities, el_time = [], {}
    for (stage, level), start in sorted(order, key=lambda o: o[1]):
        a = acts[(stage, level)]
        s, f = start * scale, finish[(stage, level)] * scale
        activities.append({"stage": stage, "level": level, "start": round(s, 2), "end": round(f, 2),
                           "cost": round(a["cost"], 2), "elements": len(a["guids"])})
        for g in a["guids"]:
            el_time[g] = [round(s, 2), round(f, 2)]

    # Monthly cash flow: each activity's cost spread evenly over its duration.
    n = int(-(-weeks_total // WEEKS_PER_MONTH))
    monthly = [0.0] * n
    for a in activities:
        span = max(a["end"] - a["start"], 1e-6)
        for m in range(n):
            lo, hi = m * WEEKS_PER_MONTH, (m + 1) * WEEKS_PER_MONTH
            overlap = max(0.0, min(hi, a["end"]) - max(lo, a["start"]))
            monthly[m] += a["cost"] * overlap / span
    # Add the mark-ups (contingency, overhead, profit, tax) pro rata.
    s = est["summary"]
    k = s["total"] / s["direct"] if s["direct"] else 1.0
    cum, rows = 0.0, []
    for m, v in enumerate(monthly):
        cum += v * k
        rows.append({"month": m + 1, "amount": round(v * k, 2), "cumulative": round(cum, 2)})
    return {"activities": activities, "months": rows, "elements": el_time,
            "weeks": round(weeks_total, 2), "levels": levels}
