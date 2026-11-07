"""Find where building elements overlap in 3D, so overlapping volume is not
counted twice (e.g. a column running through a slab, a beam inside a slab,
a wall built through a column). Studies of BIM take-off report errors of about
-23% to +31% from overlaps and double counting when this is ignored.

This module only measures the overlaps. Which element gives up the shared
volume is decided in estimate.py, because it depends on how each element is
priced (concrete vs steel, etc.).
"""
import numpy as np

try:
    import manifold3d as m3
except ImportError:  # optional dependency
    m3 = None

# Element kinds that can take part in overlap checks (solid construction).
SOLID = {"IfcFooting", "IfcPile", "IfcSlab", "IfcColumn", "IfcBeam", "IfcWall",
         "IfcWallStandardCase", "IfcStairFlight", "IfcRoof", "IfcMember", "IfcPlate"}


def _manifold(v, f):
    key = np.round(v.astype(np.float64), 4)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    faces = inv.ravel()[f.reshape(-1, 3)]
    faces = faces[(faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])]
    mesh = m3.Mesh(vert_properties=uniq.astype(np.float32), tri_verts=faces.astype(np.uint32))
    mf = m3.Manifold(mesh)
    if mf.status() != m3.Error.NoError or mf.volume() <= 0:
        # try the other winding
        mesh = m3.Mesh(vert_properties=uniq.astype(np.float32), tri_verts=faces[:, ::-1].astype(np.uint32))
        mf = m3.Manifold(mesh)
        if mf.status() != m3.Error.NoError or mf.volume() <= 0:
            return None
    return mf


def find(elements, meshes, min_volume=1e-4):
    """Return {guid: [[other_guid, overlap m3], ...]} and the number of shapes checked.

    elements: extracted elements; meshes: {guid: (world verts float32, faces uint32)}.
    """
    if m3 is None:
        return {}, 0
    cand = [e for e in elements if e["ifc_class"] in SOLID and e["guid"] in meshes
            and len(meshes[e["guid"]][1])]
    if len(cand) < 2:
        return {}, 0
    lo = np.array([meshes[e["guid"]][0].min(axis=0) for e in cand])
    hi = np.array([meshes[e["guid"]][0].max(axis=0) for e in cand])
    shrink = 0.002  # ignore elements that only touch
    out, cache = {}, {}

    def man(i):
        if i not in cache:
            v, f = meshes[cand[i]["guid"]]
            cache[i] = _manifold(v, f)
        return cache[i]

    for i in range(len(cand)):
        ov = np.minimum(hi[i], hi[i + 1:]) - np.maximum(lo[i], lo[i + 1:]) - shrink
        js = np.nonzero(np.all(ov > 0, axis=1))[0] + i + 1
        for j in js:
            box = float(np.prod(np.minimum(hi[i], hi[j]) - np.maximum(lo[i], lo[j])))
            if box < min_volume:
                continue
            a, b = man(i), man(j)
            if a is None or b is None:
                continue
            vol = (a ^ b).volume()
            if vol >= min_volume:
                gi, gj = cand[i]["guid"], cand[j]["guid"]
                out.setdefault(gi, []).append([gj, round(vol, 5)])
                out.setdefault(gj, []).append([gi, round(vol, 5)])
    return out, len(cand)
