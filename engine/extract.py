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
    if c is None and uel.get_aggregate(el) is not None:
        c = uel.get_container(uel.get_aggregate(el))
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
              "Type Comments": "type_comments", "Structural Material": "structural_material"}


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
    """Areas (m2) of the openings cut into a wall, slab or roof."""
    out = []
    for rel in getattr(el, "HasOpenings", []) or []:
        op = rel.RelatedOpeningElement
        area = 0.0
        for fill in getattr(op, "HasFillings", []) or []:
            e = fill.RelatedBuildingElement
            w, h = getattr(e, "OverallWidth", None), getattr(e, "OverallHeight", None)
            if w and h:
                area = w * h * scale ** 2
                break
        if not area:
            try:
                g = ifcopenshell.geom.create_shape(settings, op).geometry
                v = np.asarray(g.verts).reshape(-1, 3)
                d = sorted((v.max(axis=0) - v.min(axis=0)).tolist())
                area = d[1] * d[2]          # width x height (depth is the wall)
            except Exception:
                continue
        out.append(round(area, 4))
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
                elements[el.GlobalId] = {
                    "guid": el.GlobalId,
                    "ifc_class": el.is_a(),
                    "kind": _kind(el, typ),
                    "predefined": str(getattr(el, "PredefinedType", "") or ""),
                    "name": el.Name or "",
                    "type": (typ.Name if typ else "") or "",
                    "level": level,
                    "level_elev": elev,
                    "materials": [n for n in names if n],
                    "layers": layers,
                    "classification": _classification(el, typ),
                    "props": _props(el, psets),
                    "authored": authored,
                    "qty": q,
                    "openings": _openings(el, scale, settings) if el.is_a("IfcWall") or el.is_a("IfcSlab") or el.is_a("IfcRoof") else [],
                }
                if with_mesh:
                    m = np.array(shape.transformation.matrix).reshape(4, 4).T
                    v = np.asarray(g.verts).reshape(-1, 3)
                    w = v @ m[:3, :3].T + m[:3, 3]
                    w = np.stack([w[:, 0], w[:, 2], -w[:, 1]], axis=1)  # Z-up -> Y-up
                    meshes[el.GlobalId] = (w.astype(np.float32),
                                           np.asarray(g.faces, dtype=np.uint32))
            if not it.next():
                break

    project = model.by_type("IfcProject")[0]
    return {"project": project.LongName or project.Name or "Project", "schema": model.schema,
            "elements": list(elements.values()), "meshes": meshes}
