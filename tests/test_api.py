"""API checks: bad input gives a clear 4xx message, never a crash or a broken project."""
import io
import json
import time
import types
import zipfile

import pytest
from fastapi.testclient import TestClient

import server
from engine import ai, storage
from engine import rates as rates_mod
from engine import regions as regions_mod


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "ROOT", tmp_path / "projects")
    # Never write to the real price files from a test.
    monkeypatch.setattr(regions_mod, "_prices_path", lambda region: tmp_path / f"prices_{region}.csv")
    monkeypatch.setattr(rates_mod, "_region_file", lambda lib, region: tmp_path / f"rates_{region}.csv")
    return TestClient(server.app)


@pytest.fixture()
def project(client):
    r = client.post("/api/projects/sample/Ifc2x3_Duplex_Architecture.ifc?region=SA")
    assert r.status_code == 200, r.text
    pid = r.json()["project_id"]
    for _ in range(600):   # the model is measured in the background
        st = [v["status"] for v in client.get(f"/api/projects/{pid}").json()["versions"]]
        if st and all(x not in ("queued", "processing") for x in st):
            break
        time.sleep(0.2)
    assert "ready" in st, st
    return pid


@pytest.mark.parametrize("change", [
    {"contingency_pct": "abc"}, {"contingency_pct": float("inf")}, {"profit_pct": 500},
    {"duration_months": 0}, {"standard": "XYZ"}, {"finishes_from": "floors"},
    {"mappings": "not a dict"}, {"allowances": {"a": 1}}, {"unknown_setting": 1},
])
def test_bad_settings_are_refused(client, project, change):
    r = client.patch(f"/api/projects/{project}", content=json.dumps(change, allow_nan=True),
                     headers={"content-type": "application/json"})
    assert r.status_code in (400, 422), r.text
    assert client.get(f"/api/projects/{project}/estimate").status_code == 200


def test_good_settings_are_kept(client, project):
    r = client.patch(f"/api/projects/{project}", json={"contingency_pct": "7.5", "standard": "", "gfa_m2": ""})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["contingency_pct"] == 7.5 and s["standard"] is None and s["gfa_m2"] is None


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "abc"])
def test_bad_prices_are_refused(client, value):
    r = client.put("/api/prices/SA", json=[{"resource": "M-CEM", "price": value}])
    assert r.status_code == 400


def test_bad_fixed_rates_are_refused(client):
    r = client.put("/api/rates/SA", json=[{"work_item": "CON-FTG", "material": "nan"}])
    assert r.status_code == 400


def test_unknown_region(client):
    for url in ("/api/prices/XX9", "/api/rates/XX9", "/api/rates/XX9/template.xlsx", "/api/regions/XX9/pack.json"):
        assert client.get(url).status_code == 404, url


def test_region_code_cannot_be_a_path(client):
    r = client.post("/api/regions", json={"code": "../../etc"})
    assert r.status_code == 400


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


@pytest.mark.parametrize("data", [
    b"not a zip",
    _zip({"hello.txt": "x"}),
    _zip({"project.json": json.dumps({"format": "other"})}),
    _zip({"project.json": json.dumps({"format": "bim5d-project", "settings": {"profit_pct": "lots"}})}),
])
def test_bad_project_files_are_refused(client, data):
    r = client.post("/api/projects/import", files={"file": ("p.zip", data)})
    assert r.status_code == 400, r.text


def test_project_file_cannot_escape_its_folder(client):
    meta = {"format": "bim5d-project", "name": "x", "settings": {},
            "revisions": [{"file": "../../evil.ifc"}, {"file": "models/missing.ifc"}]}
    r = client.post("/api/projects/import", files={"file": ("p.zip", _zip({"project.json": json.dumps(meta)}))})
    assert r.status_code == 200
    assert client.get(f"/api/projects/{r.json()['project_id']}").json()["versions"] == []


def test_huge_project_file_is_refused(client, monkeypatch):
    monkeypatch.setattr(storage, "MAX_PACKAGE_BYTES", 1000)
    meta = {"format": "bim5d-project", "revisions": [{"file": "models/a.ifc"}]}
    data = _zip({"project.json": json.dumps(meta), "models/a.ifc": "0" * 5000})
    r = client.post("/api/projects/import", files={"file": ("p.zip", data)})
    assert r.status_code == 400 and "too large" in r.json()["detail"]


def test_not_ifc_upload(client):
    r = client.post("/api/projects", files={"file": ("model.rvt", b"x")})
    assert r.status_code == 400 and "IFC" in r.json()["detail"]


def test_bad_rate_pack(client):
    r = client.post("/api/regions/import", files={"file": ("p.json", b"{not json")})
    assert r.status_code == 400


def test_ai_suggestions_with_a_fake_client(client, project, monkeypatch):
    """The AI path end to end, with the Anthropic client replaced by a fake one."""
    calls = {}

    class FakeMessages:
        def parse(self, **kw):
            calls.update(kw)
            data = json.loads(kw["messages"][0]["content"].split("Items to classify:\n", 1)[1])
            out = kw["output_format"](suggestions=[
                {"key": data[0]["key"], "recipe": "EXCLUDE", "confidence": 1.7, "reason": "test"},
                {"key": "invented key", "recipe": "EXCLUDE", "confidence": 0.5, "reason": "x"},
                {"key": data[0]["key"], "recipe": "NOT_A_RECIPE", "confidence": 0.5, "reason": "x"},
            ])
            return types.SimpleNamespace(stop_reason="end_turn", parsed_output=out)

    fake = types.SimpleNamespace(Anthropic=lambda: types.SimpleNamespace(beta=types.SimpleNamespace(messages=FakeMessages())))
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    groups = client.get(f"/api/projects/{project}/estimate").json()["groups"]
    key = groups[0]["key"]
    r = client.post(f"/api/projects/{project}/suggest", json={"keys": [key]})
    assert r.status_code == 200, r.text
    s = r.json()["suggestions"]
    assert s == [{"key": key, "recipe": "EXCLUDE", "confidence": 1.0, "reason": "test"}]
    assert calls["model"] == ai.MODEL


def test_ai_off_without_key(client, project, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert client.post(f"/api/projects/{project}/suggest", json={}).status_code == 400


@pytest.mark.parametrize("text,value", [("12,5", 12.5), ("1.234,5", 1234.5), ("1,234.5", 1234.5),
                                        ("1 234,5", 1234.5), ("300", 300.0), ("", 0.0)])
def test_numbers_from_any_excel_locale(text, value):
    assert rates_mod._num(text) == value


def test_csv_from_european_excel():
    data = "code;rate\nCON-FTG;12,5\n".encode("cp1252")
    rows = rates_mod.parse_upload("rates.csv", data)
    assert rows[0]["work_item"] == "CON-FTG" and rates_mod._num(rows[0]["material"]) == 12.5


def test_discipline_models_are_combined(client):
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent / "samples"
    r = client.post("/api/projects/sample/Ifc4_Revit_ARC.ifc?region=SA")
    pid = r.json()["project_id"]

    def wait():
        for _ in range(900):
            st = [v["status"] for v in client.get(f"/api/projects/{pid}").json()["versions"]]
            if st and all(x not in ("queued", "processing") for x in st):
                return st
            time.sleep(0.2)
    wait()
    alone = client.get(f"/api/projects/{pid}/estimate").json()["summary"]
    with open(root / "Ifc4_Revit_STR.ifc", "rb") as fh:
        client.post("/api/projects", data={"project_id": pid, "discipline": "Structure"},
                    files={"file": ("Ifc4_Revit_STR.ifc", fh)})
    assert wait() == ["ready", "ready"]
    est = client.get(f"/api/projects/{pid}/estimate").json()
    assert {m["discipline"] for m in est["models"]} == {None, "Structure"}
    assert est["summary"]["total"] > alone["total"] and est["summary"]["gfa"] == alone["gfa"]
    # a project file keeps the disciplines
    pkg = client.get(f"/api/projects/{pid}/package.zip").content
    new = client.post("/api/projects/import", files={"file": ("p.zip", pkg)}).json()["project_id"]
    assert {v.get("discipline") for v in client.get(f"/api/projects/{new}").json()["versions"]} == {None, "Structure"}


def _wait(client, pid):
    for _ in range(900):
        st = [v["status"] for v in client.get(f"/api/projects/{pid}").json()["versions"]]
        if st and all(x not in ("queued", "processing") for x in st):
            return st
        time.sleep(0.2)


def test_ifczip_and_zipped_ifc_are_accepted(client):
    import pathlib
    villa = (pathlib.Path(__file__).resolve().parent.parent / "samples" / "Saudi_Villa_Example.ifc").read_bytes()
    for fname in ("villa.ifczip", "sent_by_email.zip"):
        data = _zip({"folder/Saudi_Villa_Example.ifc": villa, "readme.txt": "x"})
        r = client.post("/api/projects", files={"file": (fname, data)}, data={"region": "SA"})
        assert r.status_code == 200, r.text
        pid = r.json()["project_id"]
        assert _wait(client, pid) == ["ready"]
        assert client.get(f"/api/projects/{pid}/estimate").json()["summary"]["gfa"] > 280


def test_project_file_dropped_on_the_upload_opens_as_a_project(client):
    meta = {"format": "bim5d-project", "name": "Dropped", "settings": {}, "revisions": []}
    r = client.post("/api/projects", files={"file": ("p.zip", _zip({"project.json": json.dumps(meta)}))})
    assert r.status_code == 200 and r.json()["project_id"]


@pytest.mark.parametrize("data", [b"not a zip", _zip({"readme.txt": "no model here"})])
def test_bad_zip_uploads_give_a_clear_message(client, data):
    r = client.post("/api/projects", files={"file": ("m.ifczip", data)})
    assert r.status_code == 400 and r.json()["detail"]
