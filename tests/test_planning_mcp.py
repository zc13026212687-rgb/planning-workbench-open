"""Exercise the REAL stdio process; these tests never authorize/open AutoCAD."""
import json
import subprocess
import sys
from pathlib import Path

import ezdxf
import pytest

from app.cases import get_case

ROOT = Path(__file__).resolve().parents[1]


def request(request_id, method, params=None):
    result = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        result["params"] = params
    return result


def tool(request_id, name, **arguments):
    return request(request_id, "tools/call", {"name": name, "arguments": arguments})


def handshake(version="2025-11-25"):
    return [request("init", "initialize", {"protocolVersion": version, "capabilities": {},
                                            "clientInfo": {"name": "protocol-test", "version": "1"}}),
            {"jsonrpc": "2.0", "method": "notifications/initialized"}]


def run_messages(messages, initialized=True):
    if initialized:
        messages = handshake() + messages
    wire = "\n".join(m if isinstance(m, str) else json.dumps(m, ensure_ascii=False) for m in messages) + "\n"
    result = subprocess.run([sys.executable, "-u", str(ROOT / "planning_mcp.py")],
                            input=wire.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=ROOT, timeout=60, check=False)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    responses = [json.loads(line) for line in result.stdout.decode("utf-8").splitlines()]
    assert all(r.get("jsonrpc") == "2.0" for r in responses)
    return responses[1:] if initialized else responses


def payload(response):
    value = response["result"]
    assert json.loads(value["content"][0]["text"]) == value["structuredContent"]
    return value["structuredContent"]


def test_handshake_notifications_discovery_and_protocol_version():
    responses = run_messages(handshake("unrecognized-version") + [request(0, "ping"), request(2, "tools/list")], initialized=False)
    assert len(responses) == 3
    assert responses[0]["result"]["protocolVersion"] == "2025-11-25"
    assert responses[0]["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert responses[1] == {"jsonrpc": "2.0", "id": 0, "result": {}}
    definitions = responses[2]["result"]["tools"]
    assert {d["name"] for d in definitions} >= {"planning_cases", "planning_validate", "planning_export"}
    for definition in definitions:
        assert definition["inputSchema"]["type"] == "object"
        assert definition["inputSchema"]["additionalProperties"] is False
    from jsonschema import Draft202012Validator
    for definition in definitions:
        Draft202012Validator.check_schema(definition["inputSchema"])


def test_old_supported_protocol_and_initialization_required():
    responses = run_messages([request(1, "tools/list"), request(2, "ping")] + handshake("2025-06-18"), initialized=False)
    assert responses[0]["error"]["code"] == -32002
    assert responses[1]["result"] == {}
    assert responses[2]["result"]["protocolVersion"] == "2025-06-18"


def test_cases_and_case_spec_are_real():
    responses = run_messages([tool(1, "planning_cases"), tool("case", "planning_cases", case_id="regulatory-road-plan", variant="oblique-t60")])
    assert "regulatory-road-plan" in {c["id"] for c in payload(responses[0])["cases"]}
    value = payload(responses[1])
    assert value["selected_variant"] == "oblique-t60"
    assert len(value["spec"]["roads"]) == 2
    assert value["synthetic"] is True


@pytest.mark.parametrize("case_id,metric,expected", [("regulatory-road-plan", "total_centerline_length", 515),
                                                   ("road-cross-section", "total_width", 24)])
def test_validate_real_road_and_section(case_id, metric, expected):
    response = run_messages([tool(1, "planning_validate", spec=get_case(case_id)["spec"])])[0]
    value = payload(response)
    assert value["status"] == "validated"
    assert not value["report"]["errors"]
    assert value["metrics"][metric] == pytest.approx(expected)
    assert value["entity_count"] > 0
    assert "professional_review" in value["report"]


@pytest.mark.parametrize("case_id,layer", [("regulatory-road-plan", "ROAD_CENTER"), ("road-cross-section", "SECTION_SURFACE")])
def test_export_actual_editable_dxf_and_parameters(tmp_path, case_id, layer):
    spec = get_case(case_id)["spec"]
    out = tmp_path / case_id
    response = run_messages([tool(1, "planning_export", spec=spec, out=str(out))])[0]
    assert response["result"]["isError"] is False
    value = payload(response)
    assert value["status"] == "exported"
    assert value["cad"] is None
    assert json.loads((out / "parameters.json").read_text(encoding="utf-8")) == spec
    drawing = ezdxf.readfile(out / "drawing.dxf")
    assert drawing.units == 6
    assert any(e.dxf.layer == layer for e in drawing.modelspace())
    assert not drawing.audit().errors
    assert not (out / "drawing.dwg").exists()


def test_unapproved_cad_request_rejected_before_creating_any_output(tmp_path):
    out = tmp_path / "must-not-exist"
    responses = run_messages([tool(1, "planning_export", spec=get_case("regulatory-road-plan")["spec"], out=str(out), cad_new=True), request(2, "ping")])
    assert payload(responses[0])["code"] == "cad_authorization_required"
    assert responses[0]["result"]["isError"] is True
    assert not out.exists()
    assert responses[1]["result"] == {}


def test_existing_directory_rejected_and_content_unchanged(tmp_path):
    marker = tmp_path / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    response = run_messages([tool(1, "planning_export", spec=get_case("regulatory-road-plan")["spec"], out=str(tmp_path))])[0]
    assert payload(response)["code"] == "output_exists"
    assert list(tmp_path.iterdir()) == [marker]
    assert marker.read_text(encoding="utf-8") == "keep"


def test_invalid_geometry_cannot_export(tmp_path):
    spec = get_case("regulatory-road-plan")["spec"]
    spec["roads"][0]["segments"][0]["end"] = spec["roads"][0]["segments"][0]["start"]
    out = tmp_path / "invalid-geometry"
    responses = run_messages([tool(1, "planning_validate", spec=spec), tool(2, "planning_export", spec=spec, out=str(out))])
    assert payload(responses[0])["status"] == "invalid"
    assert payload(responses[1])["code"] == "validation_failed"
    assert not out.exists()


@pytest.mark.parametrize("arguments", [{"spec": []}, {"spec": {}}, {"spec": {"units": "m"}, "command": "whoami"}, {"spec": {"kind": "x"}, "unexpected": True}])
def test_invalid_tool_arguments_schema(arguments):
    response = run_messages([request(1, "tools/call", {"name": "planning_validate", "arguments": arguments})])[0]
    assert response["error"]["code"] == -32602


def test_unknown_tool_method_and_kind_keep_protocol_alive():
    responses = run_messages([tool(1, "arbitrary_shell", command="unused"), request(2, "execute"),
                              tool(3, "planning_validate", spec={"kind": "road_longitudinal_section"}), request(4, "ping")])
    assert responses[0]["error"]["code"] == -32602
    assert responses[1]["error"]["code"] == -32601
    assert payload(responses[2])["code"] == "unsupported_kind"
    assert responses[3]["result"] == {}


@pytest.mark.parametrize("bad", ['{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"planning_validate","arguments":{"spec":{"units":NaN}}}}',
                                  '{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":Infinity}}',
                                  '{"jsonrpc":"2.0","id":1,"id":2,"method":"ping"}', "{broken"])
def test_parse_errors_recover(bad):
    responses = run_messages([bad, request("after", "ping")])
    assert responses[0]["error"]["code"] == -32700
    assert responses[0]["id"] is None
    assert responses[1]["id"] == "after"


@pytest.mark.parametrize("bad_id", [None, True, 1.5, {}, []])
def test_invalid_mcp_request_ids(bad_id):
    response = run_messages([request(bad_id, "ping")])[0]
    assert response["error"]["code"] == -32600
    assert response["id"] is None


def test_batch_rejected_without_executing_tool_notifications(tmp_path):
    out = tmp_path / "notification-must-not-export"
    notification = tool(1, "planning_export", spec=get_case("regulatory-road-plan")["spec"], out=str(out))
    del notification["id"]
    responses = run_messages([[request(7, "ping")], [], notification, request(8, "ping")])
    assert len(responses) == 3
    assert all(r["error"]["code"] == -32600 for r in responses[:2])
    assert responses[2]["id"] == 8
    assert not out.exists()


def test_overflow_number_and_oversized_line_are_rejected():
    overflow = '{"jsonrpc":"2.0","id":1,"method":"ping","params":{"value":1e10000}}'
    responses = run_messages([overflow, '"' + "x" * (2 * 1024 * 1024) + '"', request(3, "ping")])
    assert responses[0]["error"]["code"] == -32602
    assert responses[1]["error"]["code"] == -32700
    assert responses[2]["result"] == {}


def test_missing_parent_relative_path_and_boolean_schema_rejected(tmp_path):
    spec = get_case("road-cross-section")["spec"]
    missing = tmp_path / "parent" / "child"
    responses = run_messages([tool(1, "planning_export", spec=spec, out=str(missing)),
                              tool(2, "planning_export", spec=spec, out="relative"),
                              tool(3, "planning_export", spec=spec, out=str(tmp_path / "bad"), cad_new="false")])
    assert payload(responses[0])["code"] == "output_parent_missing"
    assert payload(responses[1])["code"] == "invalid_output_path"
    assert responses[2]["error"]["code"] == -32602
    assert not missing.parent.exists()


def test_real_parcel_validation_and_total_plan_export(tmp_path):
    from app.parcels import get_example
    spec = get_example()
    out = tmp_path / "parcel-plan"
    responses = run_messages([tool(1, "planning_validate", spec=spec), tool(2, "planning_export", spec=spec, out=str(out))])
    assert payload(responses[0])["status"] == "validated"
    assert payload(responses[1])["status"] == "exported"
    drawing = ezdxf.readfile(out / "drawing.dxf")
    assert drawing.units == 6
    assert any(e.dxf.layer == "PARCEL_BOUNDARY" for e in drawing.modelspace())
    data = json.loads((out / "parcels.json").read_text(encoding="utf-8"))
    assert len(data["parcels"]) == 4
    assert (out / "parcels.csv").is_file()


def test_real_control_sheet_export_and_unknown_parcel_rejection(tmp_path):
    from app.parcels import get_example
    spec = get_example()
    out, invalid = tmp_path / "sheet", tmp_path / "missing-parcel"
    responses = run_messages([tool(1, "planning_export_control_sheet", spec=spec, parcel_id="P001", out=str(out)),
                              tool(2, "planning_export_control_sheet", spec=spec, parcel_id="not-in-spec", out=str(invalid))])
    assert payload(responses[0])["status"] == "exported"
    drawing = ezdxf.readfile(out / "drawing.dxf")
    assert any(e.dxf.layer == "CONTROL_FRAME" for e in drawing.modelspace())
    texts = [e.dxf.text for e in drawing.modelspace() if e.dxftype() == "TEXT"]
    assert any("P001" in text for text in texts)
    assert payload(responses[1])["code"] == "control_sheet_failed"
    assert not invalid.exists()


def test_export_write_failure_is_reported_with_preserved_partial_evidence(tmp_path, monkeypatch):
    # Target the exceptional I/O branch independently of the end-to-end protocol
    # tests; do not induce a real disk failure or launch AutoCAD for this branch.
    import planning_mcp
    from app.geometry import generate

    def failed_writer(result, path):
        raise OSError("controlled test write failure")

    monkeypatch.setattr(planning_mcp, "_engine", lambda spec: (generate, failed_writer))
    out = tmp_path / "partial"
    result = planning_mcp.call_tool("planning_export", {"spec": get_case("regulatory-road-plan")["spec"], "out": str(out)})
    assert result["isError"] is True
    data = result["structuredContent"]
    assert data["code"] == "export_failed"
    failure = json.loads((out / "failure.json").read_text(encoding="utf-8"))
    assert failure["status"] == "partial_failure"
    assert len(failure["files"]) == 3
    assert (out / "parameters.json").is_file()
    assert not (out / "drawing.dxf").exists()
