"""Build a small MEP check model: pipes and ducts of known size and length running straight,
diagonally (45 degrees in plan), sloped (drainage) and vertical (riser). Used by the tests.

Run:  python tools/make_mep_check.py out.ifc
"""
import sys

import numpy as np
from ifcopenshell.api import run
f = run("project.create_file", version="IFC4")
proj = run("root.create_entity", f, ifc_class="IfcProject", name="MEP check")
run("unit.assign_unit", f)   # millimetres
ctx = run("context.add_context", f, context_type="Model")
body = run("context.add_context", f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)
site = run("root.create_entity", f, ifc_class="IfcSite", name="S"); b = run("root.create_entity", f, ifc_class="IfcBuilding", name="B")
st = run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="Level 1")
run("aggregate.assign_object", f, relating_object=proj, products=[site]); run("aggregate.assign_object", f, relating_object=site, products=[b]); run("aggregate.assign_object", f, relating_object=b, products=[st])
def pt(*c): return f.createIfcCartesianPoint([float(x) for x in c])
def d(*c): return f.createIfcDirection([float(x) for x in c])
def seg(cls, name, profile, start, direction, length_m, system=None):
    e = run("root.create_entity", f, ifc_class=cls, name=name)
    run("geometry.edit_object_placement", f, product=e, matrix=np.eye(4))   # building axes, like many exports
    run("spatial.assign_container", f, relating_structure=st, products=[e])
    dirv = np.array(direction, float); dirv /= np.linalg.norm(dirv)
    ref = np.array([0, 0, 1.0]) if abs(dirv[2]) < 0.9 else np.array([1.0, 0, 0])
    xdir = np.cross(ref, dirv); xdir /= np.linalg.norm(xdir)
    pos = f.createIfcAxis2Placement3D(pt(*[s * 1000 for s in start]), d(*dirv), d(*xdir))
    solid = f.createIfcExtrudedAreaSolid(profile, pos, d(0, 0, 1), length_m * 1000)
    rep = f.createIfcShapeRepresentation(body, "Body", "SweptSolid", [solid])
    e.Representation = f.createIfcProductDefinitionShape(None, None, [rep])
    if system:
        pset = run("pset.add_pset", f, product=e, name="Pset_Revit")
        run("pset.edit_pset", f, pset=pset, properties={"System Type": system})
    return e
circ = lambda r_mm: f.createIfcCircleProfileDef("AREA", None, None, r_mm)
rect = lambda w, h: f.createIfcRectangleProfileDef("AREA", None, None, w, h)
seg("IfcPipeSegment", "Pipe DN50 straight", circ(30), (0, 0, 3), (1, 0, 0), 10, "Domestic Cold Water")
seg("IfcPipeSegment", "Pipe DN50 diagonal 45", circ(30), (0, 2, 3), (1, 1, 0), 10, "Domestic Cold Water")
seg("IfcPipeSegment", "Pipe DN100 sloped drain", circ(57), (0, 4, 3), (1, 0, -0.02), 12, "Sanitary")
seg("IfcPipeSegment", "Pipe DN200 chilled riser", circ(110), (5, 8, 0), (0, 0, 1), 9, "Chilled Water Supply")
seg("IfcDuctSegment", "Duct 600x400 straight", rect(600, 400), (0, 12, 3), (0, 1, 0), 8, "Supply Air")
seg("IfcDuctSegment", "Duct 600x400 diagonal", rect(600, 400), (4, 12, 3), (1, 1, 0), 8, "Exhaust Air")
f.write(sys.argv[1] if len(sys.argv) > 1 else "mep_check.ifc")
