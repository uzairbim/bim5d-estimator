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


def _measure(geom, ifc_class):
    """Quantities in m / m2 / m3, measured in the element's local axes.

    Pure numpy, so it stays fast on big models:
      volume     signed-tetrahedron sum around the centroid
      footprint  plan area = projected area of upward-facing triangles
      side       largest elevation = projected area of triangles facing +X or +Y
      area       half the surface area (one face of a thin element)
    """
    v = np.asarray(geom.verts, dtype=float).reshape(-1, 3)
    f = np.asarray(geom.faces, dtype=np.int64).reshape(-1, 3)
    if not len(f):
        return {k: 0.0 for k in ("count", "volume", "area", "footprint", "height",
                                 "length", "width", "perimeter", "side", "check",
                                 "surface", "section")} | {"count": 1.0}
    lo, hi = v.min(axis=0), v.max(axis=0)
    x, y, z = (hi - lo).tolist()
    c = v - v.mean(axis=0)
    a, b, cc = c[f[:, 0]], c[f[:, 1]], c[f[:, 2]]
    n = np.cross(b - a, cc - a) / 2.0           # area-weighted normals
    volume = abs(float(np.einsum("ij,ij->i", a, np.cross(b, cc)).sum()) / 6.0)
    surface = float(np.linalg.norm(n, axis=1).sum())
    footprint = float(n[:, 2][n[:, 2] > 0].sum())
    side = max(float(n[:, 0][n[:, 0] > 0].sum()), float(n[:, 1][n[:, 1] > 0].sum()))
    # Elements exported as several stacked bodies (e.g. wall layers) count each
    # face more than once; a projected area can never exceed its bounding face.
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
    # Sanity check: a solid can never be bigger than its bounding box.
    box = x * y * z
    q["check"] = 0.0
    if q["volume"] > box * 1.02 or q["volume"] <= 0:
        q["check"] = 1.0
        q["volume"] = box * 0.9 if box > 0 else 0.0   # flagged estimate
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


def _props(el):
    out = {}
    try:
        psets = uel.get_psets(el)
    except Exception:
        return out
    for ps in psets.values():
        for k, v in ps.items():
            key = KEEP_PROPS.get(k)
            if key and isinstance(v, str) and v.strip() and key not in out:
                out[key] = v.strip()[:120]
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
                q = _measure(g, el.is_a())
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
                    "props": _props(el),
                    "qty": q,
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
