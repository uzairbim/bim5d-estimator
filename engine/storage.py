"""Projects, model versions and their processed data, kept on disk.

projects/
  bim5d.sqlite                     project + version records
  <version id>/model.ifc           the uploaded file
  <version id>/elements.json.gz    measured elements
  <version id>/geometry.bin        all meshes: float32 positions then uint32 indices
  <version id>/geometry.json       {guid: [vertex offset, vertex count, index offset, index count]}
"""
import gzip
import json
import math
import shutil
import sqlite3
import threading
import time
import uuid
from functools import lru_cache
from pathlib import Path

import numpy as np

from .extract import extract
from . import overlaps

ROOT = Path(__file__).resolve().parent.parent / "projects"
_lock = threading.Lock()

DEFAULT_SETTINGS = {"region": "SA", "rebar_mode": "ratio", "mappings": {},
                    "overhead_pct": None, "profit_pct": None, "contingency_pct": None,
                    "tax_pct": None, "prelims_pct": None, "escalation_pct": None,
                    "duration_months": 12, "start": None,
                    "deduct_overlaps": True, "min_deduct_m2": 0.5, "rates_verified": False,
                    "allowances": [], "adjustments": {}, "assumptions": [], "exclusions": None,
                    "gfa_m2": None, "standard": None, "building_type": "residential", "finishes_from": "auto", "manual_items": [],
                    "include_loose_ffe": False}


_PCT = ("overhead_pct", "profit_pct", "contingency_pct", "tax_pct", "prelims_pct", "escalation_pct")
_CHOICES = {"rebar_mode": ("ratio", "modeled"), "finishes_from": ("auto", "rooms", "walls"),
            "building_type": ("residential", "apartments", "office", "retail", "school", "mosque", "hotel",
                              "hospital", "warehouse"),
            "standard": (None, "NRM2", "POMI", "IS1200", "EXACT")}
_TYPES = {"mappings": dict, "adjustments": dict, "allowances": list, "assumptions": list,
          "manual_items": list, "deduct_overlaps": bool, "rates_verified": bool, "include_loose_ffe": bool}


def _number(k, v, lo, hi, allow_none=True):
    if v is None or v == "":
        if allow_none:
            return None
        raise ValueError(f"{k} needs a value")
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{k} must be a number")
    if not math.isfinite(v) or v < lo or v > hi:
        raise ValueError(f"{k} must be between {lo:g} and {hi:g}")
    return v


def clean_settings(changes):
    """Check setting values so a typo gives a clear message instead of a broken estimate."""
    out = {}
    for k, v in changes.items():
        if k in _PCT:
            v = _number(k, v, -50 if k == "escalation_pct" else 0, 100)
        elif k == "duration_months":
            v = int(_number(k, v, 1, 240, allow_none=False))
        elif k == "min_deduct_m2":
            v = _number(k, v, 0, 50)
            v = 0.5 if v is None else v
        elif k == "gfa_m2":
            v = _number(k, v, 0, 1e8)
            v = v or None
        elif k in _CHOICES:
            v = v or None if k == "standard" else v
            if v not in _CHOICES[k]:
                raise ValueError(f"{k} must be one of: {', '.join(x for x in _CHOICES[k] if x)}")
        elif k in _TYPES:
            if k in ("mappings", "adjustments") and v is None:
                v = {}
            if not isinstance(v, _TYPES[k]):
                raise ValueError(f"{k} has the wrong format")
        elif k in ("region", "name", "start") and v is not None:
            v = str(v)[:120]
        elif k == "exclusions" and v is not None and not isinstance(v, list):
            raise ValueError("exclusions has the wrong format")
        out[k] = v
    return out


def log(project_id, what, detail=""):
    """Record a change so the estimate has an audit trail."""
    with _lock, _db() as con:
        con.execute("INSERT INTO history VALUES (?,?,?,?)",
                    (time.time(), project_id or "", what, str(detail)[:500]))


def history(project_id=None, limit=200):
    with _lock, _db() as con:
        if project_id:
            rows = con.execute("SELECT * FROM history WHERE project_id IN (?, '') ORDER BY time DESC LIMIT ?",
                               (project_id, limit))
        else:
            rows = con.execute("SELECT * FROM history ORDER BY time DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]


def _db():
    ROOT.mkdir(exist_ok=True)
    con = sqlite3.connect(ROOT / "bim5d.sqlite", check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY, name TEXT, created REAL, settings TEXT);
        CREATE TABLE IF NOT EXISTS history (
            time REAL, project_id TEXT, what TEXT, detail TEXT);
        CREATE TABLE IF NOT EXISTS versions (
            id TEXT PRIMARY KEY, project_id TEXT, label TEXT, file_name TEXT, created REAL,
            status TEXT, progress REAL, error TEXT, elements INTEGER, schema TEXT, model_name TEXT);
    """)
    try:   # projects made before discipline models existed
        con.execute("ALTER TABLE versions ADD COLUMN discipline TEXT")
    except sqlite3.OperationalError:
        pass
    return con


def _new_id():
    return uuid.uuid4().hex[:12]


# ---- projects ---------------------------------------------------------------
def list_projects():
    with _lock, _db() as con:
        projects = [dict(r) for r in con.execute("SELECT * FROM projects ORDER BY created DESC")]
        for p in projects:
            p["settings"] = {**DEFAULT_SETTINGS, **json.loads(p["settings"] or "{}")}
            p["versions"] = [dict(v) for v in con.execute(
                "SELECT * FROM versions WHERE project_id=? ORDER BY created", (p["id"],))]
    return projects


def get_project(pid):
    for p in list_projects():
        if p["id"] == pid:
            return p
    return None


def create_project(name, settings=None):
    pid = _new_id()
    with _lock, _db() as con:
        con.execute("INSERT INTO projects VALUES (?,?,?,?)",
                    (pid, name, time.time(), json.dumps({**DEFAULT_SETTINGS, **(settings or {})})))
    return pid


def update_settings(pid, changes):
    p = get_project(pid)
    if not p:
        raise KeyError(pid)
    s = p["settings"]
    changes = clean_settings(changes)
    for field in ("mappings", "adjustments"):   # merge; a value of None removes an entry
        if field in changes:
            m = dict(s.get(field) or {})
            for k, v in (changes.pop(field) or {}).items():
                if v:
                    m[k] = v
                    log(pid, f"{field[:-1]} set", f"{k.split('|', 1)[-1]} -> {v if isinstance(v, str) else json.dumps(v)}")
                else:
                    m.pop(k, None)
                    log(pid, f"{field[:-1]} removed", k.split("|", 1)[-1])
            s[field] = m
    for k, v in changes.items():
        if s.get(k) != v and k not in ("name",):
            log(pid, "setting changed", f"{k}: {json.dumps(s.get(k))} -> {json.dumps(v)}"[:500])
    s.update(changes)
    with _lock, _db() as con:
        con.execute("UPDATE projects SET settings=? WHERE id=?", (json.dumps(s), pid))
        if "name" in changes and changes["name"]:
            con.execute("UPDATE projects SET name=? WHERE id=?", (changes["name"], pid))
    return s


def rename_project(pid, name):
    with _lock, _db() as con:
        con.execute("UPDATE projects SET name=? WHERE id=?", (name, pid))


def delete_project(pid):
    p = get_project(pid)
    if not p:
        return
    for v in p["versions"]:
        shutil.rmtree(ROOT / v["id"], ignore_errors=True)
    with _lock, _db() as con:
        con.execute("DELETE FROM versions WHERE project_id=?", (pid,))
        con.execute("DELETE FROM projects WHERE id=?", (pid,))


# ---- versions -----------------------------------------------------------------
def get_version(vid):
    with _lock, _db() as con:
        r = con.execute("SELECT * FROM versions WHERE id=?", (vid,)).fetchone()
    return dict(r) if r else None


def _set_version(vid, **fields):
    keys = ", ".join(f"{k}=?" for k in fields)
    with _lock, _db() as con:
        con.execute(f"UPDATE versions SET {keys} WHERE id=?", (*fields.values(), vid))


def discipline_of(v):
    return (v.get("discipline") or "").strip() or "Main model"


def add_version(pid, src_path, file_name, label=None, move=False, discipline=None):
    """Store a model file and process it in the background. Returns the version id.

    `discipline` (Architecture, Structure, MEP...) keeps separate Revit models of one project apart:
    the estimate adds up the latest revision of each discipline.
    """
    vid = _new_id()
    folder = ROOT / vid
    folder.mkdir(parents=True)
    (shutil.move if move else shutil.copy)(str(src_path), folder / "model.ifc")
    p = get_project(pid)
    disc = str(discipline or "").strip()[:40] or None
    same = [v for v in (p["versions"] if p else []) if discipline_of(v) == (disc or "Main model")]
    n = len(same) + 1
    default = f"{disc} Rev {n}" if disc and disc != "Main model" else f"Rev {n}"
    with _lock, _db() as con:
        con.execute("INSERT INTO versions (id, project_id, label, file_name, created, status, progress, error, "
                    "elements, schema, model_name, discipline) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (vid, pid, label or default, file_name, time.time(),
                     "processing", 0.0, None, 0, None, None, disc))
    log(pid, "model uploaded", file_name)
    threading.Thread(target=_process, args=(vid,), daemon=True).start()
    return vid


def _process(vid):
    folder = ROOT / vid
    try:
        data = extract(str(folder / "model.ifc"),
                       progress=lambda f: _set_version(vid, progress=round(f * 0.9, 2)))
        if not any(e["ifc_class"] != "IfcSpace" for e in data["elements"]):
            raise ValueError("NO_ELEMENTS")
        found, _ = overlaps.find(data["elements"], data["meshes"])
        for e in data["elements"]:
            e["overlaps"] = found.get(e["guid"], [])
        with gzip.open(folder / "elements.json.gz", "wt", encoding="utf-8") as f:
            json.dump(data["elements"], f)
        _write_geometry(folder, data["meshes"], data.get("origin"))
        _set_version(vid, status="ready", progress=1.0, elements=len(data["elements"]),
                     schema=data["schema"], model_name=data["project"])
    except Exception as e:  # keep a clear message so the user knows what to do
        _set_version(vid, status="error", error=friendly_error(e))


def friendly_error(e):
    msg = str(e)
    if msg == "NO_ELEMENTS":
        return ("The file has no 3D building elements. In Revit, export IFC from a 3D view and untick "
                "'Export only elements visible in view', then upload again.")
    low = msg.lower()
    if "unable to parse" in low or "parse" in low or "token" in low or "not a valid" in low or "schema" in low:
        return ("This file could not be read as IFC. Export it again from Revit (File > Export > IFC, "
                f"IFC 2x3 Coordination View 2.0 or IFC4 Reference View) and upload the new file. Details: {msg[:200]}")
    if "memory" in low:
        return ("The model is too large for this computer's memory. Export a smaller part (one building "
                f"or one discipline) or use a computer with more memory. Details: {msg[:200]}")
    return f"Something went wrong while reading the model: {msg[:300]}"


# ---- project files (to send a whole project to a colleague) ---------------------------
def export_package(pid):
    """A zip with the project's settings and every model revision."""
    import io
    import zipfile
    p = get_project(pid)
    if not p:
        raise KeyError(pid)
    buf = io.BytesIO()
    meta = {"format": "bim5d-project", "version": 1, "name": p["name"], "settings": p["settings"],
            "revisions": []}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, v in enumerate(p["versions"]):
            src = ROOT / v["id"] / "model.ifc"
            if not src.is_file():
                continue
            arc = f"models/{i + 1:02d}_{(v.get('file_name') or 'model.ifc').replace('/', '_')}"
            z.write(src, arc)
            meta["revisions"].append({"label": v["label"], "file": arc, "file_name": v.get("file_name"),
                                      "discipline": v.get("discipline")})
        z.writestr("project.json", json.dumps(meta, indent=1, ensure_ascii=False))
    return p["name"], buf.getvalue()


MAX_PACKAGE_BYTES = 2 << 30   # 2 GB of models once unpacked


def import_package(data):
    import io
    import tempfile
    import zipfile
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        meta = json.loads(z.read("project.json").decode("utf-8"))
    except Exception:
        raise ValueError("This is not a BIM 5D project file (.zip exported from the app).")
    if meta.get("format") != "bim5d-project":
        raise ValueError("This is not a BIM 5D project file.")
    names = [r.get("file", "") for r in meta.get("revisions") or [] if isinstance(r, dict)]
    if sum(z.getinfo(n).file_size for n in z.namelist() if n in names) > MAX_PACKAGE_BYTES:
        raise ValueError("The models in this project file are too large to open.")
    settings = {k: v for k, v in (meta.get("settings") or {}).items() if k in DEFAULT_SETTINGS}
    try:
        settings = clean_settings(settings)
    except ValueError as e:
        raise ValueError(f"This project file has an invalid setting ({e}).")
    pid = create_project(meta.get("name") or "Imported project", settings)
    for rev in meta.get("revisions") or []:
        name = rev.get("file", "")
        if not name.startswith("models/") or ".." in name:
            continue
        if name not in z.namelist():
            continue
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp:
            with z.open(name) as src:
                shutil.copyfileobj(src, tmp, 1 << 20)
        add_version(pid, tmp.name, rev.get("file_name") or name.split("/")[-1], label=rev.get("label"), move=True,
                    discipline=rev.get("discipline"))
    log(pid, "project imported", meta.get("name", ""))
    return pid


def _write_geometry(folder, meshes, origin=None):
    index, verts, faces = {}, [], []
    vo = io = 0
    for guid, (v, f) in meshes.items():
        if not len(f):
            continue
        index[guid] = [vo, len(v), io, len(f)]
        verts.append(v.astype(np.float32).ravel())
        faces.append(f.astype(np.uint32))
        vo += len(v)
        io += len(f)
    pos = np.concatenate(verts) if verts else np.zeros(0, np.float32)
    idx = np.concatenate(faces) if faces else np.zeros(0, np.uint32)
    with open(folder / "geometry.bin", "wb") as fh:
        fh.write(pos.astype("<f4").tobytes())
        fh.write(idx.astype("<u4").tobytes())
    (folder / "geometry.json").write_text(json.dumps(
        {"vertex_floats": int(pos.size), "index_count": int(idx.size), "items": index,
         "origin": origin or [0.0, 0.0, 0.0]}))


def geometry_paths(vid):
    folder = ROOT / vid
    return folder / "geometry.json", folder / "geometry.bin"


@lru_cache(maxsize=8)
def _load_elements(vid, mtime):
    with gzip.open(ROOT / vid / "elements.json.gz", "rt", encoding="utf-8") as f:
        return json.load(f)


def elements(vid):
    path = ROOT / vid / "elements.json.gz"
    return _load_elements(vid, path.stat().st_mtime)


def combined_versions(p, v):
    """The revisions that make up the estimate: `v` plus the latest ready revision of every other
    discipline model in the project (architecture + structure + MEP...)."""
    out = [v]
    seen = {discipline_of(v)}
    for o in sorted(p["versions"], key=lambda x: -x["created"]):
        d = discipline_of(o)
        if o["status"] == "ready" and d not in seen:
            seen.add(d)
            out.append(o)
    return out


def delete_version(vid):
    shutil.rmtree(ROOT / vid, ignore_errors=True)
    with _lock, _db() as con:
        con.execute("DELETE FROM versions WHERE id=?", (vid,))


def rename_version(vid, label):
    _set_version(vid, label=label)


def recover():
    """Re-run versions that were interrupted by a restart."""
    with _lock, _db() as con:
        stuck = [r["id"] for r in con.execute("SELECT id FROM versions WHERE status='processing'")]
    for vid in stuck:
        threading.Thread(target=_process, args=(vid,), daemon=True).start()
