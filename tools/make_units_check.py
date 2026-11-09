"""Build the same small model in feet or inches, as Revit writes imperial projects: a 20 x 30 ft
slab 1 ft thick and a wall 20 ft long, 10 ft high, 8 in thick, placed away from the origin, with
Revit's own volume written in the file's unit (ft3 / in3). Used by the tests: quantities must come
out in metres either way. (ifcopenshell.api takes metres and writes the file's unit.)

Run:  python tools/make_units_check.py out.ifc FOOT|INCH
"""
import sys

import numpy as np
from ifcopenshell.api import run

out, unit = (sys.argv[1] if len(sys.argv) > 1 else "units.ifc"), (sys.argv[2] if len(sys.argv) > 2 else "FOOT")
names = {"FOOT": ("foot", "square foot", "cubic foot"), "INCH": ("inch", "square inch", "cubic inch")}[unit]
FT = 0.3048                            # the api works in metres
per_ft3 = 1 if unit == "FOOT" else 1728  # file volume units per ft3
f = run("project.create_file", version="IFC4")
proj = run("root.create_entity", f, ifc_class="IfcProject", name="Imperial units check")
run("unit.assign_unit", f, units=[run("unit.add_conversion_based_unit", f, name=n) for n in names])
ctx = run("context.add_context", f, context_type="Model")
body = run("context.add_context", f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)
site = run("root.create_entity", f, ifc_class="IfcSite", name="S"); b = run("root.create_entity", f, ifc_class="IfcBuilding", name="B")
st = run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="Level 1")
run("aggregate.assign_object", f, relating_object=proj, products=[site]); run("aggregate.assign_object", f, relating_object=site, products=[b]); run("aggregate.assign_object", f, relating_object=b, products=[st])
at = np.eye(4); at[:3, 3] = [50 * FT, 40 * FT, 0]        # 50 ft, 40 ft from the origin
sl = run("root.create_entity", f, ifc_class="IfcSlab", name="Floor:RC 1ft")
run("geometry.edit_object_placement", f, product=sl, matrix=at); run("spatial.assign_container", f, relating_structure=st, products=[sl])
run("geometry.assign_representation", f, product=sl, representation=run(
    "geometry.add_slab_representation", f, context=body, depth=1.0 * FT, polyline=[(0, 0), (20 * FT, 0), (20 * FT, 30 * FT), (0, 30 * FT)]))
pset = run("pset.add_pset", f, product=sl, name="Dimensions")
run("pset.edit_pset", f, pset=pset, properties={"Volume": 600.0 * per_ft3})   # 20 x 30 x 1 ft, in file units
w = run("root.create_entity", f, ifc_class="IfcWall", name="Basic Wall:Block 8in")
run("geometry.edit_object_placement", f, product=w, matrix=at); run("spatial.assign_container", f, relating_structure=st, products=[w])
run("geometry.assign_representation", f, product=w, representation=run(
    "geometry.add_wall_representation", f, context=body, length=20.0 * FT, height=10.0 * FT, thickness=(8 / 12) * FT))
f.write(out)
