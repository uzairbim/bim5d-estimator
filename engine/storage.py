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
                    "gfa_m2": None}


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


def add_version(pid, src_path, file_name, label=None, move=False):
    """Store a model file and process it in the background. Returns the version id."""
    vid = _new_id()
    folder = ROOT / vid
    folder.mkdir(parents=True)
    (shutil.move if move else shutil.copy)(str(src_path), folder / "model.ifc")
    p = get_project(pid)
    n = len(p["versions"]) + 1 if p else 1
    with _lock, _db() as con:
        con.execute("INSERT INTO versions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (vid, pid, label or f"Rev {n}", file_name, time.time(),
                     "processing", 0.0, None, 0, None, None))
    log(pid, "model uploaded", file_name)
    threading.Thread(target=_process, args=(vid,), daemon=True).start()
    return vid


def _process(vid):
    folder = ROOT / vid
    try:
        data = extract(str(folder / "model.ifc"),
                       progress=lambda f: _set_version(vid, progress=round(f * 0.9, 2)))
        found, _ = overlaps.find(data["elements"], data["meshes"])
        for e in data["elements"]:
            e["overlaps"] = found.get(e["guid"], [])
        with gzip.open(folder / "elements.json.gz", "wt", encoding="utf-8") as f:
            json.dump(data["elements"], f)
        _write_geometry(folder, data["meshes"])
        _set_version(vid, status="ready", progress=1.0, elements=len(data["elements"]),
                     schema=data["schema"], model_name=data["project"])
    except Exception as e:  # keep the error so the user can see it
        _set_version(vid, status="error", error=str(e)[:500])


def _write_geometry(folder, meshes):
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
        {"vertex_floats": int(pos.size), "index_count": int(idx.size), "items": index}))


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
