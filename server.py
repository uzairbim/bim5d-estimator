"""BIM 5D web app: upload an IFC model, see it in 3D, get a priced estimate.

Run:  uvicorn server:app --port 8000   then open http://localhost:8000
"""
import re
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from engine import ai, rates, storage
from engine.compare import compare
from engine.estimate import Library, check_formula, estimate, group_key
from engine.export import to_xlsx
from engine.schedule import build as build_schedule

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"
MAX_UPLOAD_MB = 500

app = FastAPI(title="BIM 5D Estimator")
app.add_middleware(GZipMiddleware, minimum_size=2000)


@app.on_event("startup")
def _startup():
    storage.recover()


# ---- helpers ----------------------------------------------------------------
def _project(pid):
    p = storage.get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


def _ready_version(p, vid=None):
    versions = [v for v in p["versions"] if v["status"] == "ready"]
    if vid:
        versions = [v for v in versions if v["id"] == vid]
    if not versions:
        raise HTTPException(409, "This model is not ready yet.")
    return versions[-1]


def _estimate(p, vid=None, region=None, lib=None):
    v = _ready_version(p, vid)
    s = p["settings"]
    lib = lib or Library()
    region = region or s.get("region") or "SA"
    if region not in lib.regions:
        raise HTTPException(400, "Unknown region")
    els = storage.elements(v["id"])
    return v, els, estimate(els, region, lib, s)


def _safe_name(name):
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)[:40] or "estimate"


# ---- library ----------------------------------------------------------------
@app.get("/api/library")
def library():
    lib = Library()
    recipes = {}
    for name, items in lib.recipes.items():
        g = lib.groups.get(name, {})
        recipes[name] = {"items": [{"work_item": i["work_item"], "qty": i["qty"],
                                    "waste_pct": i["waste_pct"], "option": i.get("option", "")}
                                   for i in items],
                         "label": g.get("label") or name, "nrm1": g.get("nrm1", ""),
                         "uniformat": g.get("uniformat", "")}
    return {"regions": {k: {"name": v["name"], "currency": v["currency"],
                            "tax_name": v["tax_name"], "tax_pct": v["tax_pct"],
                            "overhead_pct": v["overhead_pct"], "profit_pct": v["profit_pct"],
                            "contingency_pct": v.get("contingency_pct", 0)}
                        for k, v in lib.regions.items()},
            "recipes": recipes, "work_items": lib.work_items,
            "ai": ai.available()}


@app.get("/api/samples")
def samples():
    # "<name>_Rev2.ifc" files are loaded as the second revision of "<name>.ifc".
    return sorted(p.name for p in SAMPLES.glob("*.ifc") if not re.search(r"_Rev\d+$", p.stem))


# ---- projects -----------------------------------------------------------------
@app.get("/api/projects")
def projects():
    return storage.list_projects()


@app.post("/api/projects")
async def upload(file: UploadFile, project_id: Optional[str] = Form(None),
                 name: Optional[str] = Form(None), region: Optional[str] = Form(None)):
    if not (file.filename or "").lower().endswith(".ifc"):
        raise HTTPException(400, "Please upload an .ifc file (in Revit: File > Export > IFC).")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp:
        size = 0
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_MB << 20:
                raise HTTPException(413, f"File is larger than {MAX_UPLOAD_MB} MB.")
            tmp.write(chunk)
    if project_id:
        _project(project_id)
        pid = project_id
    else:
        pid = storage.create_project(name or Path(file.filename).stem,
                                     {"region": region} if region else None)
    vid = storage.add_version(pid, tmp.name, file.filename, move=True)
    return {"project_id": pid, "version_id": vid}


@app.post("/api/projects/sample/{name}")
def load_sample(name: str, region: Optional[str] = None):
    path = SAMPLES / Path(name).name
    if not path.is_file():
        raise HTTPException(404, "No such sample")
    pid = storage.create_project(path.stem.replace("_", " "), {"region": region} if region else None)
    vid = storage.add_version(pid, path, path.name)
    for rev in sorted(SAMPLES.glob(f"{path.stem}_Rev*.ifc")):
        if not re.fullmatch(re.escape(path.stem) + r"_Rev\d+", rev.stem):
            continue
        vid = storage.add_version(pid, rev, rev.name)
    return {"project_id": pid, "version_id": vid}


@app.get("/api/projects/{pid}")
def project(pid: str):
    return _project(pid)


@app.patch("/api/projects/{pid}")
def update_project(pid: str, changes: dict = Body(...)):
    _project(pid)
    allowed = {"name", "region", "rebar_mode", "mappings", "overhead_pct", "profit_pct",
               "contingency_pct", "tax_pct", "prelims_pct", "escalation_pct", "duration_months",
               "start", "deduct_overlaps", "min_deduct_m2", "rates_verified", "allowances",
               "adjustments", "assumptions", "exclusions", "gfa_m2"}
    bad = set(changes) - allowed
    if bad:
        raise HTTPException(400, f"Unknown settings: {', '.join(sorted(bad))}")
    if "name" in changes:
        storage.rename_project(pid, str(changes["name"])[:120])
    return storage.update_settings(pid, changes)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    storage.delete_project(pid)
    return {"ok": True}


@app.delete("/api/versions/{vid}")
def delete_version(vid: str):
    storage.delete_version(vid)
    return {"ok": True}


@app.patch("/api/versions/{vid}")
def rename_version(vid: str, body: dict = Body(...)):
    storage.rename_version(vid, str(body.get("label", ""))[:60])
    return {"ok": True}


@app.get("/api/versions/{vid}")
def version(vid: str):
    v = storage.get_version(vid)
    if not v:
        raise HTTPException(404, "Version not found")
    return v


@app.get("/api/versions/{vid}/geometry.json")
def geometry_index(vid: str):
    idx, _ = storage.geometry_paths(vid)
    if not idx.is_file():
        raise HTTPException(404, "Geometry not ready")
    return FileResponse(idx, media_type="application/json")


@app.get("/api/versions/{vid}/geometry.bin")
def geometry_bin(vid: str):
    _, bin_ = storage.geometry_paths(vid)
    if not bin_.is_file():
        raise HTTPException(404, "Geometry not ready")
    return FileResponse(bin_, media_type="application/octet-stream")


@app.get("/api/versions/{vid}/elements")
def version_elements(vid: str):
    els = storage.elements(vid)
    return {e["guid"]: {k: e.get(k) for k in ("name", "ifc_class", "kind", "level", "type",
                                               "materials", "qty", "classification", "props", "layers")}
            | {"group": group_key(e)} for e in els}


# ---- estimate, schedule, compare, export ----------------------------------------
@app.get("/api/projects/{pid}/estimate")
def get_estimate(pid: str, version: Optional[str] = None, region: Optional[str] = None):
    p = _project(pid)
    v, els, est = _estimate(p, version, region)
    est["project"] = p["name"]
    est["version"] = v["id"]
    sched = build_schedule(els, est, p["settings"].get("duration_months") or 12)
    est["schedule"] = sched
    return est


@app.get("/api/projects/{pid}/history")
def project_history(pid: str):
    _project(pid)
    return storage.history(pid)


@app.get("/api/projects/{pid}/compare")
def get_compare(pid: str, a: str, b: str, region: Optional[str] = None):
    p = _project(pid)
    lib = Library()
    va, els_a, est_a = _estimate(p, a, region, lib)
    vb, els_b, est_b = _estimate(p, b, region, lib)
    out = compare(els_a, els_b, est_a, est_b)
    out["currency"] = est_b["currency"]
    out["a"], out["b"] = va, vb
    return out


@app.get("/api/projects/{pid}/export.xlsx")
def export(pid: str, version: Optional[str] = None, region: Optional[str] = None):
    p = _project(pid)
    v, els, est = _estimate(p, version, region)
    sched = build_schedule(els, est, p["settings"].get("duration_months") or 12)
    data = to_xlsx(f"{p['name']} ({v['label']})", est, sched)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition":
                             f'attachment; filename="{_safe_name(p["name"])}_{est["region"]}_5D.xlsx"'})


# ---- AI suggestions --------------------------------------------------------------
@app.post("/api/projects/{pid}/suggest")
def suggest(pid: str, body: dict = Body(default={})):
    p = _project(pid)
    if not ai.available():
        raise HTTPException(400, "AI suggestions are off. Set ANTHROPIC_API_KEY on the server to turn them on.")
    v, els, est = _estimate(p)
    keys = set(body.get("keys") or [g["key"] for g in est["groups"] if g["recipe"] is None])
    groups = [g for g in est["groups"] if g["key"] in keys][:60]
    if not groups:
        return {"suggestions": []}
    by_guid = {e["guid"]: e for e in els}
    try:
        return {"suggestions": ai.suggest(groups, by_guid, Library())}
    except Exception as e:
        raise HTTPException(502, f"AI request failed: {e}")


# ---- rates -----------------------------------------------------------------------
@app.get("/api/rates/{region}")
def get_rates(region: str):
    lib = Library()
    if region not in lib.regions:
        raise HTTPException(404, "Unknown region")
    return rates.table(region, lib)


@app.put("/api/rates/{region}")
def put_rates(region: str, rows: list = Body(...)):
    lib = Library()
    if region not in lib.regions:
        raise HTTPException(404, "Unknown region")
    try:
        n = rates.save(region, rows, lib)
    except ValueError as e:
        raise HTTPException(400, str(e))
    storage.log("", "rates saved", f"{region}: {n} local rates")
    return {"saved": n}


@app.post("/api/rates/{region}/import")
async def import_rates(region: str, file: UploadFile):
    lib = Library()
    if region not in lib.regions:
        raise HTTPException(404, "Unknown region")
    try:
        rows = rates.parse_upload(file.filename or "", await file.read())
        n = rates.import_rows(region, rows, lib)
    except ValueError as e:
        raise HTTPException(400, str(e))
    storage.log("", "rates imported", f"{region}: {len(rows)} rows from {file.filename}")
    return {"imported": len(rows), "saved": n}


@app.get("/api/rates/{region}/template.xlsx")
def rates_template(region: str):
    data = rates.template_xlsx(region)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="rates_{region}.xlsx"'})


@app.post("/api/check-formula")
def api_check_formula(body: dict = Body(...)):
    try:
        check_formula(str(body.get("formula", "")))
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


# ---- static ------------------------------------------------------------------------
app.mount("/vendor/three", StaticFiles(directory=ROOT / "web" / "node_modules" / "three"), name="three")


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


app.mount("/", StaticFiles(directory=ROOT / "web"), name="web")
