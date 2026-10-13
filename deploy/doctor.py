"""Read-only local CLI and stdio MCP checks. Never opens CAD or calls a model."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess


def doctor(engine, interpreter):
    engine, interpreter = Path(engine).resolve(), Path(interpreter).resolve()
    result = {"status": "failed", "engine": str(engine), "python": str(interpreter),
              "cad_started": False, "model_api_called": False, "checks": {}}
    cases = subprocess.run([str(interpreter), "-B", str(engine / "planning_cli.py"), "cases"],
                           cwd=engine, capture_output=True, text=True, encoding="utf-8", timeout=60)
    if cases.returncode:
        raise RuntimeError("CLI cases failed; run planning_cli.py cases locally for diagnostics")
    data = json.loads(cases.stdout)
    if not isinstance(data, (dict, list)) or not data:
        raise ValueError("CLI cases returned no usable synthetic cases")
    result["checks"]["cli_cases"] = "passed"
    imports = subprocess.run([str(interpreter), "-B", "-c",
                              "import json, shapely, ezdxf; print(json.dumps({'shapely':shapely.__version__,'ezdxf':ezdxf.__version__}))"],
                             cwd=engine, capture_output=True, text=True, encoding="utf-8", timeout=60)
    if imports.returncode:
        raise RuntimeError("Required geometry and editable-DXF dependencies did not import")
    result["dependency_versions"] = json.loads(imports.stdout)
    result["checks"]["geometry_dependencies"] = "passed"
    validate = subprocess.run([str(interpreter), "-B", str(engine / "planning_cli.py"), "validate",
                               "--spec", str(engine / "examples" / "regulatory-parcels.json")],
                              cwd=engine, capture_output=True, text=True, encoding="utf-8", timeout=60)
    if validate.returncode:
        raise RuntimeError("Synthetic parcel geometry validation failed")
    validation = json.loads(validate.stdout)
    if validation.get("report", {}).get("errors") != []:
        raise ValueError("Synthetic parcel validation returned errors or no validation report")
    result["checks"]["cli_validate_synthetic"] = "passed"
    result["synthetic_validation"] = {"errors": [], "warning_count": len(validation["report"].get("warnings", [])),
                                      "planning_compliance": "not_evaluated"}
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "qinggui-local-doctor", "version": "0.3.1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "planning_cases", "arguments": {}}},
    ]
    process = subprocess.run([str(interpreter), "-B", "-u", str(engine / "planning_mcp.py")],
                             input="".join(json.dumps(row) + "\n" for row in requests),
                             cwd=engine, capture_output=True, text=True, encoding="utf-8", timeout=60)
    if process.returncode:
        raise RuntimeError("Local stdio MCP process failed")
    replies = {row["id"]: row for line in process.stdout.splitlines()
               if line.strip() for row in [json.loads(line)] if "id" in row}
    for identity in (1, 2, 3):
        if identity not in replies or "error" in replies[identity] or "result" not in replies[identity]:
            raise ValueError(f"MCP response {identity} failed")
    names = {item["name"] for item in replies[2]["result"].get("tools", [])}
    expected = {"planning_cases", "planning_validate", "planning_export", "planning_export_control_sheet"}
    if not expected.issubset(names):
        raise ValueError("Expected planning MCP tools were not exposed")
    call = replies[3]["result"]
    if call.get("isError") or not call.get("content"):
        raise ValueError("MCP planning_cases returned an error or empty result")
    result["checks"].update(mcp_initialize="passed", mcp_tools_list="passed", mcp_planning_cases="passed")
    result.update(status="passed", tool_names=sorted(names),
                  limitation="Local protocol checks do not certify CAD UI operation or an AI-client conversation.")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    result = doctor(args.engine, args.python)
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
