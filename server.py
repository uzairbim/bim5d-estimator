"""BIM 5D web app: upload an IFC model, see it in 3D, get a priced estimate.

Run:  uvicorn server:app --port 8000   then open http://localhost:8000
"""
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from engine import ai, rates, storage
from engine import regions as regions_mod
from engine.compare import compare
from engine.estimate import BUILDING_TYPES, STANDARDS, Library, check_formula, estimate, group_key
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
    region = region or s.get("region") or "GLOBAL"
    if region not in lib.regions:
        # The project's region was removed or renamed: keep working in the global region.
        region = "GLOBAL" if "GLOBAL" in lib.regions else next(iter(lib.regions))
    els = combined_elements(p, v)
    est = estimate(els, region, lib, s)
    est["models"] = [{k: m.get(k) for k in ("id", "label", "file_name", "discipline")}
                     for m in storage.combined_versions(p, v)]
    return v, els, est


def combined_elements(p, v):
    """Elements of the revision `v` plus the latest revision of each other discipline model."""
    parts = storage.combined_versions(p, v)
    if len(parts) == 1:
        return storage.elements(v["id"])
    out, seen = [], {}
    for m in parts:
        disc = storage.discipline_of(m)
        for e in storage.elements(m["id"]):
            i = seen.get(e["guid"])
            if i is None:                       # copies: the cached elements are shared
                seen[e["guid"]] = len(out)
                out.append({**e, "model": disc, "in_models": [disc]})
                continue
            # The same Revit element exported in two models: count it once, keep the copy with a level.
            kept = out[i]
            models = kept["in_models"] + [disc]
            if kept.get("level") in (None, "", "(no level)") and e.get("level") not in (None, "", "(no level)"):
                out[i] = {**e, "model": disc}
            out[i]["in_models"] = models
    return out


def _safe_name(name):
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)[:40] or "estimate"


def _download(filename):
    """Content-Disposition that keeps Arabic (any Unicode) file names: an ASCII fallback plus the
    UTF-8 name (RFC 6266 / 5987), which every current browser uses."""
    from urllib.parse import quote
    clean = re.sub(r'[\\/:*?"<>|\r\n]+', "_", filename).strip() or "estimate"
    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", clean)
    ascii_name = re.sub(r"_+", "_", ascii_name).strip("_.") or "estimate"
    if "." in clean and "." not in ascii_name:
        ascii_name += "." + clean.rsplit(".", 1)[1]
    return {"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(clean)}"}


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
                            "tax_name": v.get("tax_name", "Tax"), "tax_pct": v.get("tax_pct", 0),
                            "overhead_pct": v.get("overhead_pct", 10), "profit_pct": v.get("profit_pct", 10),
                            "contingency_pct": v.get("contingency_pct", 0),
                            "prelims_pct": v.get("prelims_pct", 10), "escalation_pct": v.get("escalation_pct", 0),
                            "escalation_note": v.get("escalation_note", ""), "standard": v.get("standard", "NRM2"),
                            "fx_per_usd": v.get("fx_per_usd", 1), "fx_source": v.get("fx_source", ""),
                            "labour_factor": v.get("labour_factor", v.get("location_factor", 1)),
                            "material_factor": v.get("material_factor", v.get("location_factor", 1)),
                            "notes": v.get("notes", ""),
                            "prices": len(lib.prices.get(k, {}))}
                        for k, v in lib.regions.items()},
            "standards": {k: v["label"] for k, v in STANDARDS.items()},
            "building_types": {k: v[0] for k, v in BUILDING_TYPES.items()},
            "recipes": recipes, "work_items": lib.work_items,
            "translations": lib.translations,
            "ai": ai.available()}


@app.get("/api/countries")
def get_countries():
    return regions_mod.countries()


@app.post("/api/regions")
def post_region(body: dict = Body(...)):
    try:
        code, reg = regions_mod.create_region(body.get("code", ""), body.get("values") or {})
    except ValueError as e:
        raise HTTPException(400, str(e))
    storage.log("", "region saved", f"{code}: {reg.get('name')} ({reg.get('currency')})")
    return {"code": code, "region": reg}


@app.post("/api/regions/{code}/worldbank")
def region_worldbank(code: str):
    if code not in Library().regions:
        raise HTTPException(404, "Unknown region")
    try:
        values = regions_mod.worldbank(code)
    except Exception as e:
        raise HTTPException(502, f"Could not reach the World Bank from this computer ({e}). "
                                 "Enter the exchange rate by hand instead.")
    storage.log("", "World Bank update", f"{code}: {values}")
    return values


@app.get("/api/prices/{region}")
def get_prices(region: str):
    lib = Library()
    if region not in lib.regions:
        raise HTTPException(404, "Unknown region")
    return regions_mod.price_table(region, lib)


@app.put("/api/prices/{region}")
def put_prices(region: str, rows: list = Body(...)):
    if region not in Library().regions:
        raise HTTPException(404, "Unknown region")
    try:
        n = regions_mod.save_prices(region, rows)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    storage.log("", "prices saved", f"{region}: {n} local prices")
    return {"saved": n}


@app.get("/api/regions/{code}/pack.json")
def get_pack(code: str, author: str = ""):
    if code not in Library().regions:
        raise HTTPException(404, "Unknown region")
    pack = regions_mod.export_pack(code, author)
    return Response(json.dumps(pack, indent=1, ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="ratepack_{code}.json"'})


@app.post("/api/regions/import")
async def post_pack(file: UploadFile, as_code: Optional[str] = Form(None)):
    try:
        raw = await file.read((20 << 20) + 1)
        if len(raw) > 20 << 20:
            raise ValueError("A rate pack must be smaller than 20 MB.")
        pack = json.loads(raw.decode("utf-8"))
        res = regions_mod.import_pack(pack, as_code)
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(400, str(e))
    storage.log("", "rate pack imported", json.dumps(res))
    return res


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
                 name: Optional[str] = Form(None), region: Optional[str] = Form(None),
                 discipline: Optional[str] = Form(None)):
    fname = (file.filename or "").lower()
    if not fname.endswith((".ifc", ".ifczip", ".zip")):
        raise HTTPException(400, "Please upload an .ifc file (in Revit: File > Export > IFC).")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp:
        size = 0
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_MB << 20:
                raise HTTPException(413, f"File is larger than {MAX_UPLOAD_MB} MB.")
            tmp.write(chunk)
    if fname.endswith((".ifczip", ".zip")):
        # .ifcZIP from Revit, or an IFC zipped to send it by e-mail; a project file opens as a project.
        try:
            kind, payload = _unzip_upload(tmp.name)
        finally:
            Path(tmp.name).unlink(missing_ok=True)
        if kind == "project":
            if project_id:
                raise HTTPException(400, "This is a project file. Open it from the start page (Open a project file).")
            try:
                return {"project_id": storage.import_package(payload), "version_id": None}
            except ValueError as e:
                raise HTTPException(400, str(e))
        tmp = type("T", (), {"name": payload})
    if project_id:
        _project(project_id)
        pid = project_id
    else:
        pid = storage.create_project(name or Path(file.filename).stem,
                                     {"region": region} if region else None)
    vid = storage.add_version(pid, tmp.name, file.filename, move=True, discipline=discipline)
    return {"project_id": pid, "version_id": vid}


def _unzip_upload(path):
    """('project', bytes) for a project file, else ('ifc', path of the largest .ifc inside)."""
    import zipfile
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise HTTPException(400, "This zip file could not be opened. Export the model again as .ifc or .ifcZIP.")
    with z:
        names = z.namelist()
        if "project.json" in names:
            return "project", Path(path).read_bytes()
        ifcs = [i for i in z.infolist() if i.filename.lower().endswith(".ifc") and not i.is_dir()]
        if not ifcs:
            raise HTTPException(400, "There is no .ifc file inside this zip.")
        best = max(ifcs, key=lambda i: i.file_size)
        if best.file_size > storage.MAX_PACKAGE_BYTES:
            raise HTTPException(413, "The model inside this zip is too large.")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as out, z.open(best) as src:
            shutil.copyfileobj(src, out, 1 << 20)
        return "ifc", out.name


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
               "adjustments", "assumptions", "exclusions", "gfa_m2", "standard", "finishes_from", "building_type",
               "manual_items", "include_loose_ffe"}
    bad = set(changes) - allowed
    if bad:
        raise HTTPException(400, f"Unknown settings: {', '.join(sorted(bad))}")
    try:
        settings = storage.update_settings(pid, dict(changes))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if "name" in changes:
        storage.rename_project(pid, str(changes["name"])[:120])
    return settings


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    storage.delete_project(pid)
    return {"ok": True}


@app.get("/api/projects/{pid}/package.zip")
def project_package(pid: str):
    _project(pid)
    name, data = storage.export_package(pid)
    return Response(data, media_type="application/zip",
                    headers=_download(f"{name[:80]}.bim5d.zip"))


@app.post("/api/projects/import")
async def project_import(file: UploadFile):
    try:
        data = await file.read((MAX_UPLOAD_MB << 20) + 1)
        if len(data) > MAX_UPLOAD_MB << 20:
            raise ValueError(f"The project file is larger than {MAX_UPLOAD_MB} MB.")
        pid = storage.import_package(data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"project_id": pid}


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


@app.get("/api/projects/{pid}/models")
def project_models(pid: str, version: Optional[str] = None):
    """The revisions combined in the estimate when `version` is open (one per discipline)."""
    p = _project(pid)
    v = _ready_version(p, version)
    return [{k: m.get(k) for k in ("id", "label", "file_name", "discipline")}
            for m in storage.combined_versions(p, v)]


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
def export(pid: str, version: Optional[str] = None, region: Optional[str] = None, lang: Optional[str] = None):
    p = _project(pid)
    v, els, est = _estimate(p, version, region)
    sched = build_schedule(els, est, p["settings"].get("duration_months") or 12)
    data = to_xlsx(f"{p['name']} ({v['label']})", est, sched, lang=lang)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers=_download(f'{p["name"][:80]} {est["region"]} 5D.xlsx'))


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
    if region not in Library().regions:
        raise HTTPException(404, "Unknown region")
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
# three.js (MIT) is bundled in web/vendor so no Node.js is needed to run the app.


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


app.mount("/", StaticFiles(directory=ROOT / "web"), name="web")
