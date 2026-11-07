"""Compare two versions of a model (Revit keeps GlobalIds stable between exports)."""
from collections import defaultdict

KEYS = ("volume", "side", "footprint", "length", "area", "count")


def _changed(qa, qb, tol=0.01):
    for k in KEYS:
        a, b = qa.get(k, 0), qb.get(k, 0)
        if abs(a - b) > max(abs(a), abs(b)) * tol and abs(a - b) > 1e-4:
            return k
    return None


def compare(els_a, els_b, est_a, est_b):
    A = {e["guid"]: e for e in els_a}
    B = {e["guid"]: e for e in els_b}
    pa, pb = est_a["per_element"], est_b["per_element"]
    rows, status = [], {}
    for g in A.keys() | B.keys():
        a, b = A.get(g), B.get(g)
        ca = pa.get(g, {}).get("total", 0.0)
        cb = pb.get(g, {}).get("total", 0.0)
        if a and not b:
            st, why = "removed", ""
        elif b and not a:
            st, why = "added", ""
        else:
            k = _changed(a["qty"], b["qty"])
            ra, rb = pa.get(g, {}).get("recipe"), pb.get(g, {}).get("recipe")
            if k:
                st, why = "changed", f"{k} {a['qty'][k]:.3f} → {b['qty'][k]:.3f}"
            elif ra != rb:
                st, why = "changed", f"recipe {ra} → {rb}"
            elif abs(ca - cb) > 0.01:
                st, why = "changed", "rate or settings"
            else:
                st, why = "same", ""
        status[g] = st
        if st != "same":
            e = b or a
            rows.append({"guid": g, "status": st, "name": e["name"], "ifc_class": e["ifc_class"],
                         "level": e["level"], "before": round(ca, 2), "after": round(cb, 2),
                         "delta": round(cb - ca, 2), "why": why})
    rows.sort(key=lambda r: -abs(r["delta"]))

    def by_trade(est):
        d = defaultdict(float)
        for l in est["lines"]:
            d[l["trade"]] += l["amount"]
        return d
    ta, tb = by_trade(est_a), by_trade(est_b)
    trades = sorted(ta.keys() | tb.keys(), key=lambda t: -abs(tb.get(t, 0) - ta.get(t, 0)))
    counts = defaultdict(int)
    for s in status.values():
        counts[s] += 1
    return {
        "counts": dict(counts),
        "total_before": est_a["summary"]["total"], "total_after": est_b["summary"]["total"],
        "direct_before": est_a["summary"]["direct"], "direct_after": est_b["summary"]["direct"],
        "by_trade": [{"trade": t, "before": round(ta.get(t, 0), 2), "after": round(tb.get(t, 0), 2),
                      "delta": round(tb.get(t, 0) - ta.get(t, 0), 2)} for t in trades],
        "rows": rows, "status": status,
        # Removed elements only exist in the old geometry; the viewer loads both.
        "removed": [r["guid"] for r in rows if r["status"] == "removed"],
    }
