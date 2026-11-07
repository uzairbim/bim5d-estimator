"""BIM 5D web app: upload an IFC model, see it in 3D, get a priced estimate.

Run:  uvicorn server:app --port 8000   then open http://localhost:8000
"""
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from engine.estimate import Library, estimate
from engine.export import to_xlsx
from engine.extract import extract

ROOT = Path(__file__).resolve().parent
UPLOADS = ROOT / "uploads"
SAMPLES = ROOT / "samples"
UPLOADS.mkdir(exist_ok=True)

app = FastAPI(title="BIM 5D")
MODELS = {}  # model id -> extracted data (kept in memory)


def _model(mid):
    if mid not in MODELS:
        raise HTTPException(404, "Model not found - upload it again.")
    return MODELS[mid]


def _load(path, name):
    mid = uuid.uuid4().hex[:12]
    try:
        data = extract(str(path))
    except Exception as e:  # bad or unsupported file
        raise HTTPException(400, f"Could not read IFC file: {e}")
    data["file"] = name
    MODELS[mid] = data
    return {"id": mid, "project": data["project"], "file": name,
            "schema": data["schema"], "elements": len(data["elements"])}


@app.get("/api/regions")
def regions():
    lib = Library()
    return {k: {"name": v["name"], "currency": v["currency"]} for k, v in lib.regions.items()}


@app.get("/api/samples")
def samples():
    return sorted(p.name for p in SAMPLES.glob("*.ifc"))


@app.post("/api/models/sample/{name}")
def load_sample(name: str):
    path = SAMPLES / Path(name).name
    if not path.is_file():
        raise HTTPException(404, "No such sample")
    return _load(path, path.name)


@app.post("/api/models")
async def upload(file: UploadFile):
    if not file.filename.lower().endswith(".ifc"):
        raise HTTPException(400, "Please upload an .ifc file (export it from Revit: File > Export > IFC).")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(file.filename).name)
    path = UPLOADS / f"{uuid.uuid4().hex[:8]}_{safe}"
    path.write_bytes(await file.read())
    return _load(path, file.filename)


@app.get("/api/models/{mid}/geometry")
def geometry(mid: str):
    m = _model(mid)
    els = {e["guid"]: {k: e[k] for k in ("name", "ifc_class", "level", "type", "materials", "qty")}
           for e in m["elements"]}
    return {"meshes": m["meshes"], "elements": els}


@app.get("/api/models/{mid}/estimate")
def get_estimate(mid: str, region: str = "SA"):
    m = _model(mid)
    lib = Library()  # reload so edits to data/ show up straight away
    if region not in lib.regions:
        raise HTTPException(400, "Unknown region")
    est = estimate(m["elements"], region, lib)
    est["project"] = m["project"]
    return est


@app.get("/api/models/{mid}/export.xlsx")
def export(mid: str, region: str = "SA"):
    m = _model(mid)
    est = estimate(m["elements"], region, Library())
    name = re.sub(r"[^A-Za-z0-9_-]", "_", m["project"])[:40] or "estimate"
    return Response(to_xlsx(m["project"], est),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}_{region}_5D.xlsx"'})


app.mount("/vendor/three", StaticFiles(directory=ROOT / "web" / "node_modules" / "three"), name="three")


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


app.mount("/", StaticFiles(directory=ROOT / "web"), name="web")
