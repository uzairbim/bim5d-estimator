"""Read an IFC file and measure every building element.

Quantities come from each element's own 3D geometry, measured in its local
axes and always in metres. The result does not depend on whether the
exporter (Revit, ArchiCAD, Tekla...) wrote quantity sets or which units the
model was drawn in.
"""
import multiprocessing

import numpy as np

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as uel
import ifcopenshell.util.unit as uunit

# Elements whose main dimension may be vertical or along any axis.
LINEAR = {"IfcColumn", "IfcPile", "IfcMember", "IfcReinforcingBar", "IfcPipeSegment",
          "IfcDuctSegment", "IfcCableCarrierSegment", "IfcCableSegment", "IfcFlowSegment"}

# Things that are not built work (or are measured through their host).
SKIP = {"IfcOpeningElement", "IfcVirtualElement", "IfcSpace", "IfcAnnotation",
        "IfcGrid", "IfcSite", "IfcBuilding", "IfcBuildingStorey"}


def _materials(el, scale):
    """Material names, plus layer thicknesses (m) when the element has layers."""
    mat = uel.get_material(el, should_inherit=True)
    if mat is None:
        return [], []
    kind = mat.is_a()
    if kind == "IfcMaterial":
        return [mat.Name], []
    if kind == "IfcMaterialLayerSetUsage":
        mat, kind = mat.ForLayerSet, "IfcMaterialLayerSet"
    if kind == "IfcMaterialLayerSet":
        layers = [{"name": l.Material.Name if l.Material else "",
                   "t": round((l.LayerThickness or 0) * scale, 4)}
                  for l in mat.MaterialLayers]
        return [l["name"] for l in layers], layers
    if kind == "IfcMaterialList":
        return [m.Name for m in mat.Materials], []
    if kind == "IfcMaterialConstituentSet":
        return [c.Material.Name for c in (mat.MaterialConstituents or []) if c.Material], []
    if kind == "IfcMaterialProfileSetUsage":
        mat = mat.ForProfileSet
    if mat.is_a("IfcMaterialProfileSet"):
        return [p.Material.Name for p in mat.MaterialProfiles if p.Material], []
    return [], []


def _storey(el, scale):
    """(level name, level elevation in m)."""
    c = uel.get_container(el)
    if c is None:
        a = uel.get_aggregate(el)   # rooms are parts of a level; wall parts are parts of a wall
        if a is not None:
            c = a if a.is_a("IfcSpatialStructureElement") else uel.get_container(a)
    while c is not None and not c.is_a("IfcBuildingStorey"):
        c = uel.get_aggregate(c)
    if c is None:
        return "(no level)", 0.0
    return c.Name or "(unnamed level)", round((c.Elevation or 0.0) * scale, 3)


def _components(f, nverts):
    """Label each face with the connected solid piece it belongs to."""
    lab = np.arange(nverts)
    for _ in range(500):
        m = np.minimum(np.minimum(lab[f[:, 0]], lab[f[:, 1]]), lab[f[:, 2]])
        new = lab.copy()
        for k in range(3):
            np.minimum.at(new, f[:, k], m)
        new = new[new]                      # pointer jumping
        if np.array_equal(new, lab):
            break
        lab = new
    return lab[f[:, 0]]


def _orient(f):
    """Make triangle winding consistent inside each piece (flip faces that
    disagree with their neighbours). Needed for exporters that write closed
    shells with mixed winding, which otherwise give wrong volumes."""
    from collections import defaultdict, deque
    f = f.copy()
    edge_faces = defaultdict(list)
    for i, (a, b, c) in enumerate(f.tolist()):
        for u, w in ((a, b), (b, c), (c, a)):
            edge_faces[(min(u, w), max(u, w))].append(i)
    seen = np.zeros(len(f), bool)
    for start in range(len(f)):
        if seen[start]:
            continue
        seen[start] = True
        queue = deque([start])
        while queue:
            i = queue.popleft()
            a, b, c = f[i]
            for u, w in ((a, b), (b, c), (c, a)):
                for j in edge_faces[(min(u, w), max(u, w))]:
                    if seen[j]:
                        continue
                    fj = f[j].tolist()
                    # a consistent neighbour walks this edge the other way (w -> u)
                    if any(fj[k] == u and fj[(k + 1) % 3] == w for k in range(3)):
                        f[j] = f[j][::-1]
                    seen[j] = True
                    queue.append(j)
    return f


def _measure(geom, ifc_class, thickness=0.0, authored=None):
    """Quantities in m / m2 / m3, measured in the element's local axes.

    Robust to the way exporters write meshes:
      * vertices are merged, and each separate solid piece (e.g. each wall layer)
        is measured on its own, so pieces wound in opposite directions don't cancel;
      * areas use |normal| so faces wound inwards still count.
      volume     sum of |signed volume| of each piece (measured around its centroid)
      footprint  plan area = half the |z|-projected surface
      side       largest elevation = half the |x| or |y|-projected surface
      area       half the surface area (one face of a thin element)
    """
    v = np.asarray(geom.verts, dtype=float).reshape(-1, 3)
    f = np.asarray(geom.faces, dtype=np.int64).reshape(-1, 3)
    if not len(f):
        return {k: 0.0 for k in ("count", "volume", "area", "footprint", "height",
                                 "length", "width", "perimeter", "side", "check",
                                 "surface", "section")} | {"count": 1.0}
    # merge duplicate vertices so pieces are connected properly
    key = np.round(v, 5)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.ravel()
    f = inv[f]
    v = uniq
    lo, hi = v.min(axis=0), v.max(axis=0)
    x, y, z = (hi - lo).tolist()
    directed = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    if len(np.unique(directed, axis=0)) < len(directed):   # mixed winding
        f = _orient(f)
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    n = np.cross(b - a, c - a) / 2.0           # area-weighted normals
    surface = float(np.linalg.norm(n, axis=1).sum())
    footprint = float(np.abs(n[:, 2]).sum()) / 2.0
    side = max(float(np.abs(n[:, 0]).sum()), float(np.abs(n[:, 1]).sum())) / 2.0
    # volume per connected piece
    comp = _components(f, len(v))
    volume = 0.0
    for cid in np.unique(comp):
        sel = f[comp == cid]
        ctr = v[np.unique(sel)].mean(axis=0)
        pa, pb, pc = v[sel[:, 0]] - ctr, v[sel[:, 1]] - ctr, v[sel[:, 2]] - ctr
        volume += abs(float(np.einsum("ij,ij->i", pa, np.cross(pb, pc)).sum()) / 6.0)
    # Bodies exported as several stacked pieces count shared faces more than
    # once; a projected area can never exceed its bounding face.
    footprint = min(footprint, x * y)
    side = min(side, max(x, y) * z)
    q = {
        "count": 1.0,
        "volume": volume,
        "area": surface / 2.0,
        "footprint": footprint,
        "side": side,
        "height": z,
        "length": max(x, y, z) if ifc_class in LINEAR else max(x, y),
        "width": min(x, y),
        "perimeter": 2 * (x + y),
        "surface": surface,                       # full outer surface (ducts, cladding)
        "section": sorted((x, y, z))[1],          # middle dimension ~ pipe/duct size
    }
    # Is it a closed solid? Every edge must be shared by exactly two faces.
    edges = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    closed = bool(np.all(counts == 2))
    box = x * y * z
    # How the volume was obtained:
    #   0 measured from a closed solid      2 face x material layer thickness
    #   3 the authoring tool's own volume   1 rough estimate from the bounding box
    q["check"] = 0.0
    av = authored.get("volume") if authored else None
    av = av if av and 0 < av <= box * 1.05 else None
    bad = q["volume"] > box * 1.02 or q["volume"] <= 0
    if not closed and thickness > 0:
        base = q["side"] if q["side"] >= q["footprint"] else q["footprint"]
        q["volume"] = base * thickness
        q["check"] = 2.0
    elif (not closed or bad) and av:
        q["volume"] = av
        q["check"] = 3.0
    elif bad:
        q["volume"] = box * 0.5 if box > 0 else 0.0
        q["check"] = 1.0
    return {k: round(float(v), 6) for k, v in q.items()}


# IFC2x3 uses generic classes (IfcFlowSegment...) and puts the real kind on the
# type object (IfcPipeSegmentType). We expose the specific kind so one set of
# rules works for IFC2x3 and IFC4.
GENERIC = {"IfcFlowSegment", "IfcFlowFitting", "IfcFlowTerminal", "IfcFlowController",
           "IfcFlowMovingDevice", "IfcEnergyConversionDevice", "IfcFlowStorageDevice",
           "IfcFlowTreatmentDevice", "IfcDistributionControlElement", "IfcDistributionFlowElement",
           "IfcBuildingElementProxy"}

# Properties worth keeping (from any property set) to help classification.
KEEP_PROPS = {"Assembly Code": "assembly_code", "Keynote": "keynote", "System Type": "system",
              "System Classification": "system", "System Name": "system_name",
              "OmniClass Number": "omniclass", "Description": "description",
              "Type Comments": "type_comments", "Structural Material": "structural_material",
              "Phase Created": "phase", "Phase Demolished": "demolished"}


def _kind(el, typ):
    k = el.is_a()
    if k in GENERIC and typ is not None:
        t = typ.is_a()
        if t.endswith("Type") and t not in ("IfcBuildingElementProxyType",
                                            "IfcDistributionElementType", "IfcFlowTerminalType"):
            return t[:-4]
    return k


def _classification(el, typ):
    refs = []
    for src in (el, typ):
        if src is None:
            continue
        for rel in getattr(src, "HasAssociations", []) or []:
            if rel.is_a("IfcRelAssociatesClassification"):
                r = rel.RelatingClassification
                code = getattr(r, "Identification", None) or getattr(r, "ItemReference", None) or ""
                refs.append(f"{code} {r.Name or ''}".strip())
        if refs:
            break
    return refs


def _authored(el, psets):
    """Volume and area written by the authoring tool (Revit 'Dimensions'
    parameters first; IFC base quantities are often wrong, so only used last)."""
    out = {}
    for pn in ("PSet_Revit_Dimensions", "Dimensions"):
        ps = psets.get(pn) or {}
        for k in ("Volume", "Area"):
            v = ps.get(k)
            if isinstance(v, (int, float)) and v > 0 and k.lower() not in out:
                out[k.lower()] = float(v)
    for pn, ps in psets.items():
        if pn.startswith("Qto_") or pn == "BaseQuantities":
            v = ps.get("NetVolume") or ps.get("GrossVolume")
            if "volume" not in out and isinstance(v, (int, float)) and v > 0:
                out["volume_qto"] = float(v)
    return out


def _props(el, psets):
    out = {}
    for ps in psets.values():
        for k, v in ps.items():
            key = KEEP_PROPS.get(k)
            if key and isinstance(v, str) and v.strip() and key not in out:
                out[key] = v.strip()[:120]
    return out


def _openings(el, scale, settings):
    """Openings cut into a wall, slab or roof: [area m2, width m, height m, kind]."""
    out = []
    for rel in getattr(el, "HasOpenings", []) or []:
        op = rel.RelatedOpeningElement
        w = h = 0.0
        kind = "void"
        for fill in getattr(op, "HasFillings", []) or []:
            e = fill.RelatedBuildingElement
            fw, fh = getattr(e, "OverallWidth", None), getattr(e, "OverallHeight", None)
            kind = "door" if e.is_a("IfcDoor") else "window" if e.is_a("IfcWindow") else "void"
            if fw and fh:
                w, h = fw * scale, fh * scale
                break
        if not w:
            try:
                g = ifcopenshell.geom.create_shape(settings, op).geometry
                v = np.asarray(g.verts).reshape(-1, 3)
                d = sorted((v.max(axis=0) - v.min(axis=0)).tolist())
                w, h = d[1], d[2]          # width x height (depth is the wall)
            except Exception:
                continue
        out.append([round(w * h, 4), round(w, 4), round(h, 4), kind])
    return out


def extract(path, with_mesh=True, progress=None):
    """Read and measure every element.

    Returns {"project", "schema", "elements": [...], "meshes": {guid: (verts, faces)}}
    where verts is float32 (x, y, z in a Y-up frame) and faces is uint32.
    """
    model = ifcopenshell.open(path)
    scale = uunit.calculate_unit_scale(model)  # model length unit -> metres
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", False)    # measure in local axes

    total = max(len(model.by_type("IfcProduct")), 1)
    elements, meshes = {}, {}
    origin = None
    it = ifcopenshell.geom.iterator(settings, model, multiprocessing.cpu_count())
    done = 0
    if it.initialize():
        while True:
            shape = it.get()
            el = model.by_id(shape.id)
            done += 1
            if progress and done % 50 == 0:
                progress(min(done / total, 0.99))
            # Skip non-elements, and assemblies whose parts are measured instead
            # (e.g. an IfcStair made of IfcStairFlights) to avoid double counting.
            if (el.is_a() not in SKIP and el.is_a("IfcElement")
                    and not uel.get_parts(el)):
                g = shape.geometry
                typ = uel.get_type(el)
                names, layers = _materials(el, scale)
                try:
                    psets = uel.get_psets(el)
                except Exception:
                    psets = {}
                authored = _authored(el, psets)
                q = _measure(g, el.is_a(), sum(l["t"] for l in layers), authored)
                level, elev = _storey(el, scale)
                if el.is_a() in ("IfcDoor", "IfcWindow") and el.OverallWidth and el.OverallHeight:
                    q["area"] = round(el.OverallWidth * el.OverallHeight * scale ** 2, 4)
                if el.is_a() in ("IfcWall", "IfcSlab", "IfcRoof"):
                    ops = _openings(el, scale, settings)
                else:
                    ops = []
                kind = _kind(el, typ)
                part_of = None
                if el.is_a("IfcBuildingElementPart"):
                    host = uel.get_aggregate(el)
                    if host is None:
                        for rel in getattr(el, "Decomposes", []) or []:
                            host = rel.RelatingObject
                    if host is not None and host.is_a("IfcElement"):
                        part_of = host
                        kind = host.is_a()
                        htyp = uel.get_type(host)
                        typ = htyp or typ
                elements[el.GlobalId] = {
                    "guid": el.GlobalId,
                    "ifc_class": el.is_a(),
                    "kind": kind,
                    "part_of": part_of.GlobalId if part_of is not None else None,
                    "predefined": str(getattr(el, "PredefinedType", "") or ""),
                    "name": ((part_of.Name or "") + " / " if part_of is not None else "") + (el.Name or ""),
                    "type": (typ.Name if typ else "") or "",
                    "level": level,
                    "level_elev": elev,
                    "materials": [n for n in names if n],
                    "layers": layers,
                    "classification": _classification(el, typ),
                    "props": _props(el, psets),
                    "authored": authored,
                    "qty": q,
                    "openings": ops,
                }
                e = elements[el.GlobalId]
                if el.is_a() in ("IfcDoor", "IfcWindow"):
                    if el.OverallWidth and el.OverallHeight:
                        q["ow"] = round(el.OverallWidth * scale, 4)
                        q["oh"] = round(el.OverallHeight * scale, 4)
                    else:
                        q["ow"], q["oh"] = round(q["length"], 4), round(q["height"], 4)
                    e["host"] = _host(el)
                if el.is_a("IfcWall"):
                    ext = (psets.get("Pset_WallCommon") or {}).get("IsExternal")
                    e["external"] = bool(ext) if ext is not None else None
                m = np.array(shape.transformation.matrix).reshape(4, 4).T
                v = np.asarray(g.verts).reshape(-1, 3)
                w = v @ m[:3, :3].T + m[:3, 3]                     # world, Z-up, metres
                if len(w):
                    e["bbox"] = [round(float(x), 3) for x in (*w.min(axis=0), *w.max(axis=0))]
                if with_mesh and len(w):
                    # Survey (UTM) coordinates lose precision in float32: shift near the origin first,
                    # by whole kilometres so separate discipline models keep lining up.
                    if origin is None:
                        origin = np.floor(w[0] / 1000.0) * 1000.0
                    wl = w - origin
                    wy = np.stack([wl[:, 0], wl[:, 2], -wl[:, 1]], axis=1)  # Z-up -> Y-up
                    meshes[el.GlobalId] = (wy.astype(np.float32),
                                           np.asarray(g.faces, dtype=np.uint32))
            if not it.next():
                break

    rooms = _spaces(model, scale)
    _link_rooms(rooms, elements)
    project = model.by_type("IfcProject")[0]
    o = origin if origin is not None else np.zeros(3)
    return {"project": project.LongName or project.Name or "Project", "schema": model.schema,
            "elements": list(elements.values()) + rooms, "meshes": meshes,
            # where the meshes' (0, 0, 0) is, in the viewer's Y-up axes
            "origin": [float(o[0]), float(o[2]), float(-o[1])]}


def _host(el):
    """GlobalId of the wall (or slab) a door/window sits in."""
    for rel in getattr(el, "FillsVoids", []) or []:
        op = rel.RelatingOpeningElement
        for v in getattr(op, "VoidsElements", []) or []:
            return v.RelatingBuildingElement.GlobalId
    return None


# Room-like spaces that should not get finishes (shafts, voids, area schemes).
NOT_A_ROOM = ("shaft", "void", "riser", "duct", "gross", "gfa", "area scheme", "schacht", "luftraum",
              "roof", "dach", "attic space", "open to below")


def _spaces(model, scale):
    """Rooms (IfcSpace) measured from their 3D shape: floor area, perimeter, height."""
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    out = []
    for sp in model.by_type("IfcSpace"):
        if not sp.Representation:
            continue
        try:
            g = ifcopenshell.geom.create_shape(settings, sp).geometry
        except Exception:
            continue
        v = np.asarray(g.verts, dtype=float).reshape(-1, 3)
        f = np.asarray(g.faces, dtype=np.int64).reshape(-1, 3)
        if not len(f):
            continue
        key = np.round(v, 4)
        uniq, inv = np.unique(key, axis=0, return_inverse=True)
        f = inv.ravel()[f]
        v = uniq
        a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
        n = np.cross(b - a, c - a) / 2.0
        zmin, zmax = float(v[:, 2].min()), float(v[:, 2].max())
        area = float(np.abs(n[:, 2]).sum()) / 2.0
        # perimeter = free edges of the floor faces
        floor = f[(np.abs(n[:, 2]) > 1e-9) & (np.abs(n[:, 2]) / (np.linalg.norm(n, axis=1) + 1e-12) > 0.9)
                  & (np.abs(v[f[:, 0], 2] - zmin) < 0.02)]
        perim = 0.0
        if len(floor):
            edges = np.sort(np.concatenate([floor[:, [0, 1]], floor[:, [1, 2]], floor[:, [2, 0]]]), axis=1)
            uniq_e, counts = np.unique(edges, axis=0, return_counts=True)
            free = uniq_e[counts == 1]
            perim = float(np.linalg.norm(v[free[:, 0]] - v[free[:, 1]], axis=1).sum())
        x0, y0 = v[:, 0].min(), v[:, 1].min()
        x1, y1 = v[:, 0].max(), v[:, 1].max()
        check = 0.0
        if perim < 2 * np.sqrt(np.pi * area) * 0.98:      # shorter than a circle: impossible
            perim = 2 * ((x1 - x0) + (y1 - y0))          # fall back to the outline
            check = 1.0
        level, elev = _storey(sp, scale)
        name = " ".join(x for x in (sp.Name, sp.LongName) if x)
        try:
            psets = uel.get_psets(sp)
        except Exception:
            psets = {}
        finishes = {}
        for ps in psets.values():
            for k in ("Floor Finish", "Wall Finish", "Ceiling Finish", "Base Finish",
                      "FloorCovering", "WallCovering", "CeilingCovering", "SkirtingBoard"):
                if isinstance(ps.get(k), str) and ps.get(k).strip():
                    finishes[k] = ps[k].strip()[:80]
        out.append({
            "guid": sp.GlobalId, "ifc_class": "IfcSpace", "kind": "IfcSpace",
            "predefined": str(getattr(sp, "PredefinedType", "") or ""),
            "name": name or "Room", "type": sp.LongName or sp.Name or "Room",
            "level": level, "level_elev": elev, "materials": [], "layers": [],
            "classification": [], "props": finishes, "authored": {},
            "is_room": not any(w in name.lower() for w in NOT_A_ROOM),
            "bbox": [round(x, 3) for x in (*v.min(axis=0), *v.max(axis=0))],
            "qty": {"count": 1.0, "floor_area": round(area, 4), "perimeter": round(perim, 4),
                    "height": round(zmax - zmin, 4), "volume": round(area * (zmax - zmin), 4),
                    "footprint": round(area, 4), "check": check},
        })
    return out


def _link_rooms(rooms, elements):
    """For each room: doors and windows in its walls, and finishes already modelled in it."""
    pad = 0.3
    for r in rooms:
        x0, y0, z0, x1, y1, z1 = r["bbox"]
        doors, wins, modeled = [], [], []
        area = max((x1 - x0) * (y1 - y0), 1e-6)
        for e in elements.values():
            b = e.get("bbox")
            if not b:
                continue
            if e["ifc_class"] in ("IfcDoor", "IfcWindow"):
                if (b[0] < x1 + pad and b[3] > x0 - pad and b[1] < y1 + pad and b[4] > y0 - pad
                        and b[2] < z1 and b[5] > z0):
                    (doors if e["ifc_class"] == "IfcDoor" else wins).append(
                        [e["qty"].get("ow", 0.9), e["qty"].get("oh", 2.1)])
            elif e["ifc_class"] in ("IfcCovering", "IfcSlab"):
                ox = min(b[3], x1) - max(b[0], x0)
                oy = min(b[4], y1) - max(b[1], y0)
                if ox > 0 and oy > 0 and ox * oy / area > 0.3 and b[2] < z1 + 0.3 and b[5] > z0 - 0.3:
                    modeled.append(e["guid"])
        r["room_doors"], r["room_windows"], r["room_modeled"] = doors, wins, modeled
        q = r["qty"]
        q["door_width"] = round(sum(d[0] for d in doors), 4)
        q["openings_area"] = round(sum(d[0] * d[1] for d in doors + wins), 4)
        q["wall_area"] = round(max(q["perimeter"] * q["height"] - q["openings_area"], 0.0), 4)
        q["skirting"] = round(max(q["perimeter"] - q["door_width"], 0.0), 4)
