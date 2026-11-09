"""Build a small external-works check model: Saudi site items of known size modelled as Revit
families usually are (generic models / proxies). Used by the tests.

Run:  python tools/make_external_check.py out.ifc
"""
import sys

import numpy as np
from ifcopenshell.api import run

f = run("project.create_file", version="IFC4")
proj = run("root.create_entity", f, ifc_class="IfcProject", name="External works check")
run("unit.assign_unit", f)   # millimetres
ctx = run("context.add_context", f, context_type="Model")
body = run("context.add_context", f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)
site = run("root.create_entity", f, ifc_class="IfcSite", name="S"); b = run("root.create_entity", f, ifc_class="IfcBuilding", name="B")
st = run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="Ground Floor")
run("aggregate.assign_object", f, relating_object=proj, products=[site]); run("aggregate.assign_object", f, relating_object=site, products=[b]); run("aggregate.assign_object", f, relating_object=b, products=[st])


def box(cls, name, x, y, z, dx, dy, dz):
    """A box dx x dy x dz metres with its corner at (x, y, z)."""
    e = run("root.create_entity", f, ifc_class=cls, name=name)
    if hasattr(e, "ObjectType"):
        e.ObjectType = name
    run("geometry.edit_object_placement", f, product=e, matrix=np.eye(4))
    run("spatial.assign_container", f, relating_structure=st, products=[e])
    prof = f.createIfcRectangleProfileDef("AREA", None, f.createIfcAxis2Placement2D(
        f.createIfcCartesianPoint([dx * 500.0, dy * 500.0])), dx * 1000.0, dy * 1000.0)
    pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([x * 1000.0, y * 1000.0, z * 1000.0]))
    solid = f.createIfcExtrudedAreaSolid(prof, pos, f.createIfcDirection([0.0, 0.0, 1.0]), dz * 1000.0)
    e.Representation = f.createIfcProductDefinitionShape(None, None, [
        f.createIfcShapeRepresentation(body, "Body", "SweptSolid", [solid])])
    return e


P = "IfcBuildingElementProxy"
box(P, "خزان أرضي 30 م3", 0, 0, -2.5, 4, 3, 2.5)             # 30 m3 gross
box(P, "بيارة", 6, 0, -3, 2, 2, 3)                            # 12 m3
box(P, "خزان علوي", 0, 6, 7, 1.4, 1.4, 1.6)                   # one roof tank
box(P, "مظلة سيارات", 10, 0, 2.5, 6, 5, 0.1)                  # 30 m2
box(P, "Pergola", 10, 8, 2.8, 4, 3, 0.2)                     # 12 m2
box(P, "Swimming pool", 20, 0, -1.6, 8, 4, 1.6)              # 32 m2 water area
box(P, "Kerb", 0, 12, 0, 10, 0.15, 0.3)                      # 10 m
box(P, "كاسرات شمس", 20, 8, 3, 3, 0.1, 2)                     # 3 x 2 m = 6 m2 of facade
box(P, "Main gate", 30, 0, 0, 4, 0.1, 2.2)                   # 4 x 2.2 = 8.8 m2
box(P, "Grass", 30, 5, 0, 10, 5, 0.05)                       # 50 m2
f.write(sys.argv[1] if len(sys.argv) > 1 else "external_check.ifc")
