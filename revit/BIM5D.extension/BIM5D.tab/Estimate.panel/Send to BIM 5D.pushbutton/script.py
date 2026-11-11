# -*- coding: utf-8 -*-
"""Send the open Revit model to BIM 5D Estimator: export IFC with the settings the estimator needs
(whole model, IFC 2x3 Coordination View 2.0, base quantities, Revit property sets, rooms in 3D),
start the app if it is not running, and open the model in it.

pyRevit button (works with IronPython 2.7 and CPython engines).
"""
import io
import json
import os
import time

from Autodesk.Revit.DB import IFCExportOptions, IFCVersion, Transaction
from System.Diagnostics import Process, ProcessStartInfo

try:
    from urllib.request import urlopen          # CPython
except ImportError:
    from urllib2 import urlopen                 # IronPython 2.7

try:
    from pyrevit import forms, revit
    doc = revit.doc

    def say(msg):
        forms.alert(msg, title="BIM 5D")
except ImportError:                             # plain RevitPythonShell / macro
    from Autodesk.Revit.UI import TaskDialog
    doc = __revit__.ActiveUIDocument.Document   # noqa: F821

    def say(msg):
        TaskDialog.Show("BIM 5D", msg)

HOME = os.path.join(os.path.expanduser("~"), "BIM5D")
INBOX = os.path.join(HOME, "inbox")


def app_info():
    try:
        with io.open(os.path.join(HOME, "app.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def running(port):
    try:
        urlopen("http://127.0.0.1:%d/api/library" % port, timeout=2).read()
        return True
    except Exception:
        return False


def find_app():
    """Port of the running app, starting it with its start file if needed; None if not found."""
    info = app_info()
    ports = [info.get("port")] if info.get("port") else []
    ports += [p for p in range(8000, 8011) if p not in ports]
    for p in ports:
        if running(p):
            return p
    start = info.get("start")
    if not start or not os.path.exists(start):
        return None
    psi = ProcessStartInfo(start)
    psi.WorkingDirectory = info.get("folder") or os.path.dirname(start)
    psi.UseShellExecute = True
    Process.Start(psi)
    for _ in range(300):                        # the very first start installs Python parts (minutes)
        time.sleep(1)
        info = app_info()
        if info.get("port") and running(info["port"]):
            return info["port"]
    return None


def safe(name):
    keep = [c if (c.isalnum() or c in " -_()") else "_" for c in name]
    return ("".join(keep).strip() or "model")[:80]


def export_ifc():
    if not os.path.isdir(INBOX):
        os.makedirs(INBOX)
    title = doc.Title[:-4] if doc.Title.lower().endswith(".rvt") else doc.Title
    name = "%s__%s" % (safe(title), time.strftime("%Y%m%d-%H%M%S"))
    opts = IFCExportOptions()
    opts.FileVersion = IFCVersion.IFC2x3CV2
    opts.ExportBaseQuantities = True
    for key, value in (("ExportInternalRevitPropertySets", "true"), ("ExportIFCCommonPropertySets", "true"),
                       ("VisibleElementsOfCurrentView", "false"), ("Export2DElements", "false"),
                       ("Use2DRoomBoundaryForVolume", "false"), ("ExportPartsAsBuildingElements", "false"),
                       ("ExportLinkedFiles", "false"), ("SpaceBoundaries", "0"), ("ExportSchedulesAsPsets", "false")):
        opts.AddOption(key, value)
    t = Transaction(doc, "Export IFC for BIM 5D")
    t.Start()
    try:
        ok = doc.Export(INBOX, name + ".ifc", opts)
    finally:
        t.RollBack()                            # the export changes nothing in the model
    path = os.path.join(INBOX, name + ".ifc")
    if not ok or not os.path.exists(path):
        return None
    return name + ".ifc"


def main():
    if doc is None or doc.IsFamilyDocument:
        say("Open a Revit project (not a family), then click Send to BIM 5D again.")
        return
    port = find_app()
    if port is None:
        say("BIM 5D Estimator is not running and its folder was not found.\n\n"
            "Start it once with start-windows.bat (in the folder you unzipped), "
            "then click Send to BIM 5D again.")
        return
    fname = export_ifc()
    if not fname:
        say("Revit could not export the model to IFC. Try File > Export > IFC by hand and upload the .ifc file in BIM 5D.")
        return
    url = "http://localhost:%d/#inbox=%s" % (port, fname.replace(" ", "%20"))
    psi = ProcessStartInfo(url)
    psi.UseShellExecute = True
    Process.Start(psi)


main()
