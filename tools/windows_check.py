"""Upload check against a running BIM 5D app, the way a user does it in the browser.

Used by the Windows test on GitHub (.github/workflows/windows.yml) after start-windows.bat has
started the app. Uploads every sample model plus a Revit .rvt, a broken file and a zipped IFC, waits
for each, and checks that every answer is a clear one (never a dropped connection).

Run:  python tools/windows_check.py [port]
"""
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
for _stream in (sys.stdout, sys.stderr):     # a Windows console cannot show every character (Arabic names)
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
SAMPLES = os.path.join(HERE, "..", "samples")


def port_of_app():
    if len(sys.argv) > 1:
        return int(sys.argv[1])
    path = os.path.join(os.path.expanduser("~"), "BIM5D", "app.json")
    for _ in range(600):                      # first start installs the Python parts
        try:
            with open(path, encoding="utf-8") as f:
                port = json.load(f)["port"]
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/library", timeout=3).read()
            return port
        except Exception:  # noqa: BLE001 - not up yet
            time.sleep(1)
    raise SystemExit("The app did not start within 10 minutes.")


def call(method, url, body=None, headers=None):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def upload(base, name, data, region="SA"):
    b = uuid.uuid4().hex
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="region"\r\n\r\n{region}\r\n'.encode(),
             f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
             f'Content-Type: application/octet-stream\r\n\r\n'.encode("utf-8"), data, f"\r\n--{b}--\r\n".encode()]
    return call("POST", base + "/api/projects", b"".join(parts),
                {"Content-Type": f"multipart/form-data; boundary={b}"})


def main():
    base = f"http://127.0.0.1:{port_of_app()}"
    failures = []
    files = [(n, open(os.path.join(SAMPLES, n), "rb").read()) for n in sorted(os.listdir(SAMPLES)) if n.endswith(".ifc")]
    villa = dict(files)["Saudi_Villa_Example.ifc"]
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("villa.ifc", villa)
    files += [("فيلا الرياض.ifc", villa), ("Villa.ifczip", zbuf.getvalue())]
    for name, data in files:
        t = time.time()
        code, body = upload(base, name, data)
        if code != 200:
            failures.append(f"{name}: upload answered {code} {body[:200]!r}")
            continue
        r = json.loads(body)
        status = "processing"
        while status == "processing" and time.time() - t < 900:
            time.sleep(1)
            status = json.loads(call("GET", f"{base}/api/versions/{r['version_id']}")[1])["status"]
        code, est = call("GET", f"{base}/api/projects/{r['project_id']}/estimate")
        xcode, xls = call("GET", f"{base}/api/projects/{r['project_id']}/export.xlsx?lang=ar")
        gcode, _ = call("GET", f"{base}/api/versions/{r['version_id']}/geometry.bin", headers={"Accept-Encoding": "gzip"})
        total = json.loads(est)["summary"]["total"] if code == 200 else None
        ok = status == "ready" and code == 200 and xcode == 200 and xls[:2] == b"PK" and gcode == 200 and total
        print(f"{'OK ' if ok else 'BAD'} {name:42} {time.time() - t:6.1f}s  {status:10} total {total}")
        if not ok:
            failures.append(f"{name}: status {status}, estimate {code}, excel {xcode}, geometry {gcode}")
    for name, data, want in [("House.rvt", b"revit", 400), ("broken.ifc", b"not an ifc at all", 200),
                             ("notes.txt", b"x", 400)]:
        code, body = upload(base, name, data)
        print(f"{'OK ' if code == want else 'BAD'} {name:42} answered {code} {body[:120]!r}")
        if code != want:
            failures.append(f"{name}: answered {code}, expected {want}")
        if name == "broken.ifc" and code == 200:     # accepted, then a clear error on the revision
            vid = json.loads(body)["version_id"]
            for _ in range(60):
                v = json.loads(call("GET", f"{base}/api/versions/{vid}")[1])
                if v["status"] != "processing":
                    break
                time.sleep(1)
            print(f"    broken.ifc -> {v['status']}: {v.get('error')}")
            if v["status"] != "error" or not v.get("error"):
                failures.append("broken.ifc: no clear error")
    if failures:
        print("\nFAILURES:\n  " + "\n  ".join(failures))
        sys.exit(1)
    print("\nAll uploads answered clearly.")


if __name__ == "__main__":
    main()
