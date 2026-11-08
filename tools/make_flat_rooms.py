"""Build a test model with rooms exported as a 2D outline only (FootPrint): one with IFC quantities
(height), one without. Used by the tests.  python tools/make_flat_rooms.py out.ifc
"""
import sys

import numpy as np
from ifcopenshell.api import run
f = run("project.create_file", version="IFC4")
proj = run("root.create_entity", f, ifc_class="IfcProject", name="Flat rooms")
run("unit.assign_unit", f)
ctx = run("context.add_context", f, context_type="Model")
plan = run("context.add_context", f, context_type="Plan")
fp = run("context.add_context", f, context_type="Model", context_identifier="FootPrint", target_view="SKETCH_VIEW", parent=ctx)
body = run("context.add_context", f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)
site = run("root.create_entity", f, ifc_class="IfcSite", name="S"); b = run("root.create_entity", f, ifc_class="IfcBuilding", name="B")
st = run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="Level 1")
run("aggregate.assign_object", f, relating_object=proj, products=[site]); run("aggregate.assign_object", f, relating_object=site, products=[b]); run("aggregate.assign_object", f, relating_object=b, products=[st])
def room(name, x, y, a, bb, qto, h=3.0):
    sp = run("root.create_entity", f, ifc_class="IfcSpace", name=name); sp.LongName = name
    run("aggregate.assign_object", f, relating_object=st, products=[sp])
    m = np.eye(4); m[:3, 3] = [x, y, 0]; run("geometry.edit_object_placement", f, product=sp, matrix=m)
    pts = [f.createIfcCartesianPoint((float(px), float(py))) for px, py in [(0, 0), (a * 1000, 0), (a * 1000, bb * 1000), (0, bb * 1000), (0, 0)]]
    curve = f.createIfcPolyline(pts)
    rep = f.createIfcShapeRepresentation(fp, "FootPrint", "Curve2D", [curve])
    sp.Representation = f.createIfcProductDefinitionShape(None, None, [rep])
    if qto:
        q = run("pset.add_qto", f, product=sp, name="Qto_SpaceBaseQuantities")
        run("pset.edit_qto", f, qto=q, properties={"NetFloorArea": a * bb, "NetPerimeter": 2 * (a + bb) * 1000, "Height": h * 1000})
    # walls around so rooms are "in use"
    return sp
room("Bedroom", 0, 0, 5, 4, True)
room("Bathroom", 6, 0, 3, 2, False)
for i, (x, y, rot, L) in enumerate([(0, 0, 0, 12), (12, 0, 90, 6), (12, 6, 180, 12), (0, 6, 270, 6)]):
    w = run("root.create_entity", f, ifc_class="IfcWall", name="Basic Wall:Block 200")
    m = np.eye(4); c, s = np.cos(np.radians(rot)), np.sin(np.radians(rot)); m[:2, :2] = [[c, -s], [s, c]]; m[:3, 3] = [x, y, 0]
    run("geometry.edit_object_placement", f, product=w, matrix=m); run("spatial.assign_container", f, relating_structure=st, products=[w])
    run("geometry.assign_representation", f, product=w, representation=run("geometry.add_wall_representation", f, context=body, length=L, height=3, thickness=0.2))
f.write(sys.argv[1])
