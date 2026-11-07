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
import ifcopenshell.util.shape as ushape
import ifcopenshell.util.unit as uunit

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


def _storey(el):
    c = uel.get_container(el)
    if c is None and uel.get_aggregate(el) is not None:
        c = uel.get_container(uel.get_aggregate(el))
    while c is not None and not c.is_a("IfcBuildingStorey"):
        c = uel.get_aggregate(c)
    return c.Name if c is not None else "(no level)"


def _volume(verts, faces):
    """Mesh volume, measured around the centroid so open meshes stay sane."""
    v = np.asarray(verts, dtype=float).reshape(-1, 3)
    f = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    if not len(f):
        return 0.0
    v = v - v.mean(axis=0)
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    return float(abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0))


def _measure(geom, ifc_class):
    """Quantities in m / m2 / m3, measured in the element's local axes."""
    x, y, z = ushape.get_x(geom), ushape.get_y(geom), ushape.get_z(geom)
    q = {
        "count": 1.0,
        "volume": _volume(geom.verts, geom.faces),
        "area": ushape.get_area(geom) / 2.0,           # one face of a thin element
        "footprint": ushape.get_footprint_area(geom),  # plan area
        "height": z,
        "length": max(x, y, z) if ifc_class in ("IfcColumn", "IfcPile", "IfcMember") else max(x, y),
        "width": min(x, y),
        "perimeter": 2 * (x + y),
    }
    try:
        q["side"] = ushape.get_max_side_area(geom)     # largest elevation (wall face)
    except Exception:
        q["side"] = 0.0
    # Sanity check: a solid can never be bigger than its bounding box.
    box = x * y * z
    q["check"] = 0.0
    if q["volume"] > box * 1.02 or q["volume"] <= 0:
        q["check"] = 1.0
        q["volume"] = box * 0.9 if box > 0 else 0.0   # flagged estimate
    return {k: round(float(v), 4) for k, v in q.items()}


def extract(path, with_mesh=True):
    model = ifcopenshell.open(path)
    scale = uunit.calculate_unit_scale(model)  # model length unit -> metres
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", False)    # measure in local axes

    elements, meshes = {}, {}
    it = ifcopenshell.geom.iterator(settings, model, multiprocessing.cpu_count())
    if it.initialize():
        while True:
            shape = it.get()
            el = model.by_id(shape.id)
            # Skip non-elements, and assemblies whose parts are measured instead
            # (e.g. an IfcStair made of IfcStairFlights) to avoid double counting.
            if (el.is_a() not in SKIP and el.is_a("IfcElement")
                    and not uel.get_parts(el)):
                g = shape.geometry
                typ = uel.get_type(el)
                names, layers = _materials(el, scale)
                q = _measure(g, el.is_a())
                if el.is_a() in ("IfcDoor", "IfcWindow") and el.OverallWidth and el.OverallHeight:
                    q["area"] = round(el.OverallWidth * el.OverallHeight * scale ** 2, 4)
                elements[el.GlobalId] = {
                    "guid": el.GlobalId,
                    "ifc_class": el.is_a(),
                    "name": el.Name or "",
                    "type": (typ.Name if typ else "") or "",
                    "level": _storey(el),
                    "materials": [n for n in names if n],
                    "layers": layers,
                    "qty": q,
                }
                if with_mesh:
                    m = np.array(shape.transformation.matrix).reshape(4, 4).T
                    v = np.asarray(g.verts).reshape(-1, 3)
                    w = v @ m[:3, :3].T + m[:3, 3]
                    w = np.stack([w[:, 0], w[:, 2], -w[:, 1]], axis=1)  # Z-up -> Y-up
                    meshes[el.GlobalId] = {"v": np.round(w, 3).ravel().tolist(),
                                           "f": list(g.faces)}
            if not it.next():
                break

    project = model.by_type("IfcProject")[0]
    return {"project": project.Name or "Project", "schema": model.schema,
            "elements": list(elements.values()), "meshes": meshes}
