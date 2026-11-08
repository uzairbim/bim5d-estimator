"""Build samples/Saudi_Villa_Example.ifc: a small two-storey Saudi villa modelled the way a typical
Revit export looks (isolated footings, tie beams, columns, ground slab, solid slab, hordi roof slab,
thermal block external walls, hollow block internal walls, parapets, doors, windows, marble and
porcelain floors, rooms with Arabic names). Used as a demo and by the tests.

Run:  python tools/make_saudi_villa.py [output.ifc]
"""
import sys

import numpy as np
from ifcopenshell.api import run
import ifcopenshell.util.placement as up
from ifcopenshell.api import run
f = run("project.create_file", version="IFC4")
proj = run("root.create_entity", f, ifc_class="IfcProject", name="Saudi Villa Test")
run("unit.assign_unit", f)
ctx = run("context.add_context", f, context_type="Model")
body = run("context.add_context", f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)
site = run("root.create_entity", f, ifc_class="IfcSite", name="Site")
bld = run("root.create_entity", f, ifc_class="IfcBuilding", name="Villa")
run("aggregate.assign_object", f, relating_object=proj, products=[site]); run("aggregate.assign_object", f, relating_object=site, products=[bld])
levels = {}
for name, z in [("Foundation", -1.5), ("Ground Floor", 0.0), ("First Floor", 3.5), ("Roof", 7.0)]:
    st = run("root.create_entity", f, ifc_class="IfcBuildingStorey", name=name); st.Elevation = z * 1000
    run("aggregate.assign_object", f, relating_object=bld, products=[st]); levels[name] = (st, z)
mats = {n: run("material.add_material", f, name=n) for n in ["Concrete C30", "Thermal Block", "Hollow Block", "Marble", "Porcelain"]}
def place(el, lvl, x=0, y=0, dz=0, rot=0):
    st, z = levels[lvl]
    m = np.eye(4); c, s = np.cos(np.radians(rot)), np.sin(np.radians(rot)); m[:2, :2] = [[c, -s], [s, c]]; m[:3, 3] = [x, y, z + dz]
    run("geometry.edit_object_placement", f, product=el, matrix=m)
    run("spatial.assign_container", f, relating_structure=st, products=[el])
def ent(cls, name, mat=None, **kw):
    e = run("root.create_entity", f, ifc_class=cls, name=name, **kw)
    if mat: run("material.assign_material", f, products=[e], material=mats[mat])
    return e
def box(e, L, W, H):
    rep = run("geometry.add_wall_representation", f, context=body, length=L, height=H, thickness=W)
    run("geometry.assign_representation", f, product=e, representation=rep)
def slab(e, pts, d):
    rep = run("geometry.add_slab_representation", f, context=body, depth=d, polyline=pts)
    run("geometry.assign_representation", f, product=e, representation=rep)
grid = [0.0, 6.0, 12.0]
# footings, neck/columns, tie beams
for x in grid:
    for y in grid:
        e = ent("IfcFooting", "Isolated Footing F1 2000x2000x600", "Concrete C30", predefined_type="PAD_FOOTING"); place(e, "Foundation", x - 1, y - 1, -0.6 + 0.0); box(e, 2, 2, 0.6)
        for lvl, h in [("Foundation", 1.5), ("Ground Floor", 3.5), ("First Floor", 3.5)]:
            c = ent("IfcColumn", "Concrete Column 300x500", "Concrete C30"); place(c, lvl, x - 0.15, y - 0.25); box(c, 0.3, 0.5, h)
for y in grid:
    b = ent("IfcBeam", "Concrete-Rectangular Beam:Tie Beam 300x600", "Concrete C30"); place(b, "Foundation", 0, y - 0.15, 0.9); box(b, 12, 0.3, 0.6)
for x in grid:
    b = ent("IfcBeam", "Concrete-Rectangular Beam:Tie Beam 300x600", "Concrete C30"); place(b, "Foundation", x + 0.15, 0, 0.9, rot=90); box(b, 12, 0.3, 0.6)
sq = [(0, 0), (12, 0), (12, 12), (0, 12)]
e = ent("IfcSlab", "Floor:Ground Slab 150mm", "Concrete C30", predefined_type="FLOOR"); place(e, "Ground Floor", 0, 0, -0.15); slab(e, sq, 0.15)
e = ent("IfcSlab", "Floor:Solid Slab 200mm", "Concrete C30", predefined_type="FLOOR"); place(e, "First Floor", 0, 0, -0.2); slab(e, sq, 0.2)
e = ent("IfcSlab", "Floor:Hordi Slab 320mm", "Concrete C30", predefined_type="ROOF"); place(e, "Roof", 0, 0, -0.32); slab(e, sq, 0.32)
for lvl in ("Ground Floor", "First Floor"):
    e = ent("IfcSlab", "Floor:Marble flooring 30mm", "Marble", predefined_type="FLOOR"); place(e, lvl, 0.2, 0.2, 0); slab(e, [(0, 0), (11.6, 0), (11.6, 5.6), (0, 5.6)], 0.03)
    e = ent("IfcSlab", "Floor:Porcelain tiles 20mm", "Porcelain", predefined_type="FLOOR"); place(e, lvl, 0.2, 6.2, 0); slab(e, [(0, 0), (11.6, 0), (11.6, 5.6), (0, 5.6)], 0.02)
walls = []
for lvl, h in [("Ground Floor", 3.3), ("First Floor", 3.3)]:
    for (x, y, rot) in [(0, 0, 0), (12, 0, 90), (12, 12, 180), (0, 12, 270)]:
        w = ent("IfcWall", "Basic Wall:Ext - Thermal Block 200", "Thermal Block"); place(w, lvl, x, y, 0, rot); box(w, 12, 0.2, h); walls.append((w, lvl))
    w = ent("IfcWall", "Basic Wall:Int - Hollow Block 150", "Hollow Block"); place(w, lvl, 0, 6, 0); box(w, 12, 0.15, h)
    w = ent("IfcWall", "Basic Wall:Int - Hollow Block 150", "Hollow Block"); place(w, lvl, 6, 0, 0, 90); box(w, 6, 0.15, h)
for (x, y, rot) in [(0, 0, 0), (12, 0, 90), (12, 12, 180), (0, 12, 270)]:
    w = ent("IfcWall", "Basic Wall:Parapet Thermal Block 200", "Thermal Block"); place(w, "Roof", x, y, 0, rot); box(w, 12, 0.2, 1.2)
def opening(wall, lvl, off, w, h, sill, kind):
    o = ent("IfcOpeningElement", "Opening"); st, z = levels[lvl]
    run("geometry.edit_object_placement", f, product=o, matrix=np.eye(4))
    rep = run("geometry.add_wall_representation", f, context=body, length=w, height=h, thickness=0.6)
    run("geometry.assign_representation", f, product=o, representation=rep)
    # place opening in the wall's local axes
    M = up.get_local_placement(wall.ObjectPlacement).copy(); M[:3, 3] /= 1000.0
    loc = M @ np.array([off, -0.2, sill, 1.0])
    M2 = M.copy(); M2[:3, 3] = loc[:3]
    run("geometry.edit_object_placement", f, product=o, matrix=M2)
    run("feature.add_feature", f, feature=o, element=wall)
    d = ent("IfcDoor" if kind == "door" else "IfcWindow", "Single Flush Door 900x2100" if kind == "door" else "Aluminium Window 1500x1500")
    d.OverallWidth, d.OverallHeight = w * 1000, h * 1000
    M3 = M2.copy(); loc2 = M @ np.array([off, 0.05, sill, 1.0]); M3[:3, 3] = loc2[:3]
    run("geometry.edit_object_placement", f, product=d, matrix=M3)
    run("spatial.assign_container", f, relating_structure=levels[lvl][0], products=[d])
    rep = run("geometry.add_wall_representation", f, context=body, length=w, height=h, thickness=0.1)
    run("geometry.assign_representation", f, product=d, representation=rep)
    run("feature.add_filling", f, opening=o, element=d)
for w, lvl in walls:
    opening(w, lvl, 2.0, 1.5, 1.5, 1.0, "window"); opening(w, lvl, 7.0, 1.5, 1.5, 1.0, "window")
    if lvl == "Ground Floor" and w is walls[0][0]:
        opening(w, lvl, 4.5, 0.9, 2.1, 0.0, "door")
st = ent("IfcStair", "Cast-In-Place Stair", "Concrete C30"); place(st, "Ground Floor", 9, 6.5, 0); box(st, 3, 1.2, 3.5)
rooms = {"Ground Floor": [("مجلس رجال", 0.1, 0.1, 5.8, 5.8), ("مطبخ", 6.1, 0.1, 5.8, 5.8), ("صالة", 0.1, 6.1, 8.8, 5.8), ("حمام", 9.1, 6.1, 2.8, 2.8)],
         "First Floor": [("غرفة نوم رئيسية", 0.1, 0.1, 5.8, 5.8), ("غرفة نوم 2", 6.1, 0.1, 5.8, 5.8), ("صالة علوية", 0.1, 6.1, 8.8, 5.8), ("حمام 2", 9.1, 6.1, 2.8, 2.8)]}
for lvl, rs in rooms.items():
    for i, (nm, x, y, a, b) in enumerate(rs):
        sp = run("root.create_entity", f, ifc_class="IfcSpace", name=str(i + 1)); sp.LongName = nm
        run("aggregate.assign_object", f, relating_object=levels[lvl][0], products=[sp])
        m = np.eye(4); m[:3, 3] = [x, y, levels[lvl][1]]; run("geometry.edit_object_placement", f, product=sp, matrix=m)
        slab(sp, [(0, 0), (a, 0), (a, b), (0, b)], 3.0)
out = sys.argv[1] if len(sys.argv) > 1 else "samples/Saudi_Villa_Example.ifc"
f.write(out)
print("written", out)
