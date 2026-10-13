"""Local API / job lifecycle tests, with CAD and model calls explicitly mocked."""
import copy
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main, runtime
from app.cases import get_case
from app.providers import unprotect
from app.store import Store


class NoCad:
    """Fail loudly if an API/job test accidentally requests real CAD mutation."""
    def __init__(self, folder):
        self.folder = folder

    def status(self):
        return {"available": False, "test_fixture": True, "message": "CAD intentionally disabled in API tests"}

    def close(self):
        pass

    def __getattr__(self, name):
        raise AssertionError(f"API fixture must not call real CAD operation {name}")


@pytest.fixture
def local_app(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CadBridge", NoCad)
    monkeypatch.setattr(main, "runtimes", lambda: [{"id": "mock", "ready": True, "test_fixture": True}])
    # A missing monkeypatch should never silently make a paid model request.
    def forbidden(*args, **kwargs):
        raise AssertionError("Real provider calls are forbidden in API tests")
    monkeypatch.setattr(main, "chat_response", forbidden)
    monkeypatch.setattr(runtime, "chat_response", forbidden)
    app = main.create_app(tmp_path, token="test-token")
    with TestClient(app) as client:
        yield app, client, tmp_path
    app.state.jobs.pool.shutdown(wait=True, cancel_futures=True)
    app.state.store.db.close()


def authenticate(client):
    response = client.get("/api/bootstrap", headers={"x-local-token": "test-token"})
    assert response.status_code == 200
    return response


def project(client, spec=None, case_id="regulatory-road-plan", synthetic=True):
    body = {"name": "API fixture", "case_id": case_id, "synthetic": synthetic}
    if spec is not None:
        body["spec"] = spec
    response = client.post("/api/projects", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def wait_job(client, job_id, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in ("succeeded", "failed", "canceled", "interrupted"):
            return job
        time.sleep(0.01)
    raise AssertionError(f"Local fixture job did not finish within {timeout}s")


def submit(client, p, **options):
    response = client.post("/api/jobs", json={"project_id": p["id"], **options})
    assert response.status_code == 200, response.text
    return response.json()


def simple_spec():
    return {"units": "m", "coordinate_reference": "local_cartesian", "left_width": 8,
            "right_width": 8, "junction_radius": 4, "roads": [{"id": "r", "name": "Fixture road",
                "segments": [{"type": "line", "start": [0, 0], "end": [100, 0]}]}],
            "constraints": [], "context_entities": []}


def test_bootstrap_health_and_local_token_cookie(local_app):
    app, client, _ = local_app
    assert client.get("/health").status_code == 200
    assert client.get("/api/bootstrap").status_code == 401
    assert client.get("/api/bootstrap", headers={"x-local-token": "wrong"}).status_code == 401
    response = authenticate(client)
    data = response.json()
    assert data["offline"] is True
    assert {c["id"] for c in data["cases"]} == {"regulatory-road-plan", "renewal-street-adjustment", "road-cross-section", "regulatory-parcels"}
    assert data["cad"]["test_fixture"] is True
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/projects").status_code == 200  # Cookie-established session.


def test_cross_origin_and_foreign_host_rejected_even_with_token(local_app):
    _, client, _ = local_app
    for origin in ("https://attacker.invalid", "http://localhost", "null"):
        response = client.get("/api/bootstrap", headers={"x-local-token": "test-token", "origin": origin})
        assert response.status_code == 403
    assert client.get("/api/bootstrap", headers={"x-local-token": "test-token", "host": "attacker.invalid"}).status_code == 403
    assert client.get("/api/bootstrap", headers={"x-local-token": "test-token", "origin": "http://testserver"}).status_code == 200


def test_request_size_gate(local_app):
    _, client, _ = local_app
    authenticate(client)
    response = client.post("/api/projects", content="{}", headers={"content-type": "application/json", "content-length": str(20 * 1024 * 1024 + 1)})
    assert response.status_code == 413


def test_malformed_content_length_returns_client_error(local_app):
    _, client, _ = local_app
    authenticate(client)
    response = client.post("/api/projects", content="{}", headers={"content-type": "application/json", "content-length": "not-a-number"})
    assert response.status_code == 400


def test_project_revision_history_and_stale_update(local_app):
    _, client, _ = local_app
    authenticate(client)
    p = project(client, simple_spec(), synthetic=False)
    changed = copy.deepcopy(p["spec"])
    changed["left_width"] = 10
    update = client.put(f"/api/projects/{p['id']}", json={"revision": 1, "spec": changed})
    assert update.status_code == 200
    body = update.json()
    assert body["revision"] == 2
    assert body["history"][0]["spec"]["left_width"] == 8
    assert body["synthetic"] is False
    assert client.put(f"/api/projects/{p['id']}", json={"revision": 1, "name": "stale"}).status_code == 409
    assert client.get(f"/api/projects/{p['id']}").json()["name"] == p["name"]


def test_geometry_job_download_report_and_event_cursor(local_app):
    _, client, folder = local_app
    authenticate(client)
    p = project(client)
    job = wait_job(client, submit(client, p)["id"])
    assert job["status"] == "succeeded", job.get("error")
    assert job["result"]["metrics"]["junction_count"] == 2
    assert not job["result"]["report"]["errors"]
    download = client.get(job["download_url"])
    assert download.status_code == 200
    assert b"AC1027" in download.content
    assert "attachment" in download.headers["content-disposition"]
    assert (folder / "artifacts" / job["id"] / "drawing.dxf").exists()
    report = client.get(f"/api/jobs/{job['id']}/report").json()
    assert report["status"] == "succeeded" and report["mock"] is False
    events = client.get(f"/api/jobs/{job['id']}/events?after=1")
    assert events.status_code == 200 and "event: complete" in events.text
    assert "id: 1\n" not in events.text
    assert f"id: {job['events'][-1]['seq']}\n" in events.text


def test_renewal_a_blocked_b_downloadable(local_app):
    _, client, _ = local_app
    authenticate(client)
    case = client.get("/api/cases/renewal-street-adjustment").json()
    assert case["synthetic"] is True
    p = project(client, case_id=case["id"])
    a = wait_job(client, submit(client, p, spec=case["variants"][0]["spec"])["id"])
    assert a["status"] == "failed"
    assert any(e["code"] == "constraint_conflict" for e in a["result"]["report"]["errors"])
    assert len(a["result"]["entities"]) > 0  # Invalid candidate remains reviewable.
    assert client.get(f"/api/jobs/{a['id']}/download.dxf").status_code == 409
    b = wait_job(client, submit(client, p, spec=case["variants"][1]["spec"])["id"])
    assert b["status"] == "succeeded"
    assert client.get(b["download_url"]).status_code == 200


def test_profile_crud_remains_secret_free_over_api(local_app):
    app, client, _ = local_app
    authenticate(client)
    fake_key = "api-fixture-only-not-real"
    result = client.post("/api/providers", json={"name": "Fixture", "base_url": "https://fixture.invalid/v1",
                        "model": "fixture", "protocol": "responses", "api_key": fake_key, "headers": {"X-Test": "secret-fixture"}})
    assert result.status_code == 200
    public = result.json()
    assert public["has_key"] is True and "secret" not in public
    assert fake_key not in result.text and "secret-fixture" not in result.text
    stored = app.state.store.get("providers", public["id"])
    assert unprotect(stored["secret"])["api_key"] == fake_key
    assert fake_key not in json.dumps(stored)
    assert fake_key not in client.get("/api/providers").text
    assert fake_key not in client.get("/api/bootstrap").text
    assert client.post("/api/providers", json={"id": public["id"], "name": "Renamed"}).status_code == 200
    assert client.delete(f"/api/providers/{public['id']}").status_code == 200
    assert client.get("/api/providers").json() == []


def test_mock_agent_width_change_is_explicit_and_preview_only(local_app):
    _, client, _ = local_app
    authenticate(client)
    p = project(client, simple_spec())
    job = wait_job(client, submit(client, p, kind="agent", runtime="mock", message="左宽 10，右宽 12，圆角 6")["id"])
    assert job["status"] == "succeeded"
    assert job["mock"] is True and job["provider"] is None
    assert job["result"]["spec"]["left_width"] == 10
    assert job["result"]["spec"]["right_width"] == 12
    assert job["result"]["metrics"]["road_area"] == 2200
    assert any("不是 AI" in str(e["data"]) for e in job["events"])
    assert client.get(f"/api/projects/{p['id']}").json()["spec"]["left_width"] == 8


def test_builtin_agent_real_tool_loop_contract_with_two_fixture_rounds(local_app, monkeypatch):
    _, client, _ = local_app
    authenticate(client)
    p = project(client, simple_spec(), synthetic=False)
    provider = client.post("/api/providers", json={"name": "Fixture", "model": "m", "base_url": "https://fixture.invalid/v1"}).json()
    rounds = []
    def fixture(profile, messages, tools, emit, cancel):
        rounds.append(copy.deepcopy(messages))
        if len(rounds) == 1:
            emit("token", "fixture progress")
            return {"text": "检查并更新预览", "calls": [
                {"id": "inspect-1", "name": "inspect_project", "arguments": "{}", "parsed": {}},
                {"id": "width-1", "name": "set_road_parameters", "arguments": '{"left_width":12,"right_width":9}',
                 "parsed": {"left_width": 12, "right_width": 9}}], "usage": {"total_tokens": 10}}
        tool_messages = [m for m in messages if m["role"] == "tool"]
        assert {m["tool_call_id"] for m in tool_messages} == {"inspect-1", "width-1"}
        inspection = json.loads(tool_messages[0]["content"])
        assert inspection["spec"]["units"] == "m"
        assert inspection["synthetic"] is False
        output = json.loads(tool_messages[1]["content"])
        assert output["metrics"]["road_area"] == 2100 and not output["report"]["errors"]
        return {"text": "预览通过，尚未写入 CAD。", "calls": [], "usage": {"total_tokens": 7}}
    monkeypatch.setattr(runtime, "chat_response", fixture)
    job = wait_job(client, submit(client, p, kind="agent", provider_id=provider["id"], message="左侧改为12，右侧9")["id"])
    assert job["status"] == "succeeded", job.get("error")
    assert len(rounds) == 2
    assert job["mock"] is False
    assert job["result"]["metrics"]["road_area"] == 2100
    assert job["usage"] == [{"total_tokens": 10}, {"total_tokens": 7}]
    assert len([e for e in job["events"] if e["type"] == "tool_result"]) == 2
    inspection_event = next(e for e in job["events"] if e["type"] == "tool_result" and "spec" in e["data"])
    assert inspection_event["data"]["spec"]["left_width"] == 8  # Earlier event must remain an immutable snapshot.
    assert client.get(f"/api/projects/{p['id']}").json()["spec"]["left_width"] == 8


def test_agent_unauthorized_tool_cannot_execute(local_app, monkeypatch):
    _, client, _ = local_app
    authenticate(client)
    p = project(client, simple_spec())
    provider = client.post("/api/providers", json={"name": "Fixture", "model": "m", "base_url": "https://fixture.invalid/v1"}).json()
    monkeypatch.setattr(runtime, "chat_response", lambda *args: {"text": "", "usage": None,
        "calls": [{"id": "bad", "name": "execute_shell", "arguments": "{}", "parsed": {}}]})
    job = wait_job(client, submit(client, p, kind="agent", provider_id=provider["id"])["id"])
    assert job["status"] == "failed" and "未授权工具" in job["error"]
    assert job["result"] is None


def test_precancelled_queued_job_never_generates_artifact(local_app):
    app, client, folder = local_app
    authenticate(client)
    class DeferredPool:
        def __init__(self): self.pending = []
        def submit(self, fn, *args): self.pending.append((fn, args))
        def shutdown(self, **kwargs): pass
    app.state.jobs.pool.shutdown(wait=True)
    deferred = DeferredPool()
    app.state.jobs.pool = deferred
    p = project(client, simple_spec())
    submitted = submit(client, p)
    assert submitted["status"] == "queued"
    assert client.post(f"/api/jobs/{submitted['id']}/cancel").json()["cancel_requested"] is True
    fn, args = deferred.pending.pop()
    fn(*args)
    job = client.get(f"/api/jobs/{submitted['id']}").json()
    assert job["status"] == "canceled"
    assert not (folder / "artifacts" / job["id"] / "drawing.dxf").exists()
    assert job["id"] not in app.state.jobs.cancel_flags


def test_restart_marks_unfinished_jobs_interrupted_without_replay(tmp_path):
    store = Store(tmp_path)
    for status in ("queued", "running", "waiting_for_input", "succeeded", "failed", "canceled"):
        store.put("jobs", {"id": status, "status": status})
    store.db.close()
    reopened = Store(tmp_path)
    for old in ("queued", "running", "waiting_for_input"):
        job = reopened.get("jobs", old)
        assert job["status"] == "interrupted"
        assert "未自动重放" in job["error"]
    for finished in ("succeeded", "failed", "canceled"):
        assert reopened.get("jobs", finished)["status"] == finished
    reopened.db.close()


def test_disabled_skill_and_missing_provider_are_rejected(local_app):
    _, client, _ = local_app
    authenticate(client)
    p = project(client, simple_spec())
    assert client.post("/api/jobs", json={"project_id": p["id"], "kind": "agent", "runtime": "builtin"}).status_code == 422
    assert client.post("/api/skills/road-plan/toggle", json={"enabled": False}).status_code == 200
    response = client.post("/api/jobs", json={"project_id": p["id"], "skill_id": "road-plan"})
    assert response.status_code == 422
    assert client.get("/api/jobs").json() == []


def test_failed_geometry_cannot_be_applied_to_cad_even_in_mock_boundary(local_app):
    _, client, _ = local_app
    authenticate(client)
    invalid = get_case("renewal-street-adjustment")["variants"][0]["spec"]
    p = project(client, invalid, case_id="renewal-street-adjustment")
    job = wait_job(client, submit(client, p)["id"])
    assert job["status"] == "failed"
    response = client.post("/api/cad/apply", json={"job_id": job["id"], "document_id": "fixture-no-real-cad"})
    assert response.status_code == 422
    assert "校核" in response.text


def test_missing_download_artifact_returns_known_error(local_app):
    _, client, folder = local_app
    authenticate(client)
    p = project(client, simple_spec())
    job = wait_job(client, submit(client, p)["id"])
    assert job["status"] == "succeeded"
    artifact = folder / "artifacts" / job["id"] / "drawing.dxf"
    artifact.unlink()  # Test-owned temporary artifact only.
    assert client.get(job["download_url"]).status_code in (404, 409)


def test_dxf_upload_roundtrip_preserves_declared_units_and_actual_geometry(local_app):
    _, client, _ = local_app
    authenticate(client)
    p = project(client, simple_spec())
    job = wait_job(client, submit(client, p)["id"])
    dxf = client.get(job["download_url"]).content
    response = client.post("/api/import/dxf", files={"file": ("source.dxf", dxf, "application/dxf")})
    assert response.status_code == 200
    data = response.json()
    assert data["synthetic"] is False  # Uploaded files are not silently labelled a synthetic case.
    assert data["spec"]["units"] == "m"
    assert data["spec"]["roads"][0]["segments"][0]["end"] == [100, 0]
    assert data["spec"]["_import"]["actual_geometry_reread"] is True


def test_section_job_routes_to_section_engine_and_assignment_keeps_source(local_app):
    import io
    import zipfile
    _, client, folder = local_app
    authenticate(client)
    p = project(client, case_id="road-cross-section")
    job = wait_job(client, submit(client, p)["id"])
    assert job["status"] == "succeeded", job.get("error")
    assert job["skill_id"] == "road-cross-section"
    assert job["result"]["metrics"]["total_width"] == 24
    assert job["result"]["metrics"]["endpoints"]["left"] == pytest.approx([-12, 99.8])
    assert client.get(job["download_url"]).status_code == 200
    response = client.get(f"/api/jobs/{job['id']}/assignment.zip")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as package:
        assert "drawing.dxf" in package.namelist()
        parameters = json.loads(package.read("parameters.json"))
        assert parameters["kind"] == "road_cross_section"
        assert parameters["source"] == "synthetic_teacher_assignment"
        assert not any(n.endswith(".dwg") for n in package.namelist())
    bad = copy.deepcopy(p["spec"])
    del bad["components"][0]["slope_percent"]
    before = len(client.get('/api/jobs').json())
    invalid = client.post('/api/jobs', json={'project_id':p['id'],'spec':bad})
    assert invalid.status_code == 422  # Schema now rejects before allocating a job or artifact.
    assert 'slope_percent' in invalid.text
    assert len(client.get('/api/jobs').json()) == before
