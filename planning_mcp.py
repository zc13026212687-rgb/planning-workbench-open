"""Small real stdio MCP adapter for the independently written planning engine.

No shell commands, arbitrary Python, URLs, active drawing edits or binary plugin
loading are exposed. stdout is reserved for newline-delimited JSON-RPC.
"""
from __future__ import annotations

import contextlib
import importlib
import json
import math
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROTOCOL = "2025-11-25"
SUPPORTED_PROTOCOLS = {PROTOCOL, "2025-06-18"}
MAX_LINE_BYTES = 2 * 1024 * 1024
MAX_NODES = 100000
SPEC_SCHEMA = {"type": "object", "minProperties": 1, "maxProperties": 100,
               "description": "Engine parameters. Use planning_cases with case_id for an executable example. Road plan may omit kind; road_cross_section and regulatory_parcels require kind. Units and coordinate_reference must be explicit."}


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ToolError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.payload = {"status": "failed", "code": code, "message": message, **details}


def _object_schema(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


EXPORT_SCHEMA = _object_schema({
    "spec": SPEC_SCHEMA,
    "out": {"type": "string", "minLength": 1, "maxLength": 4096,
            "description": "Absolute local path to a NEW output directory; its parent must already exist."},
    "cad_new": {"type": "boolean", "default": False,
                "description": "Also create a separate new AutoCAD drawing and save DWG. Never modifies a pre-existing drawing."},
    "confirm_cad_new": {"type": "boolean", "default": False,
                        "description": "Set true only with the user's authorization to create a new CAD drawing."},
}, ("spec", "out"))


def _tool(name, description, schema, read_only):
    return {"name": name, "description": description, "inputSchema": schema,
            "annotations": {"readOnlyHint": read_only, "destructiveHint": False,
                            "idempotentHint": read_only, "openWorldHint": False}}


def tool_definitions():
    return [
        _tool("planning_cases", "List original synthetic teaching cases, or obtain a case/variant with its full editable spec. No files or CAD changes.",
              _object_schema({"case_id": {"type": "string", "minLength": 1, "maxLength": 128},
                              "variant": {"type": "string", "minLength": 1, "maxLength": 128}}), True),
        _tool("planning_validate", "Run the actual deterministic geometry and limited rule checks for roads, cross sections or parcels. Geometry checks do not certify planning compliance. No files or CAD changes.",
              _object_schema({"spec": SPEC_SCHEMA}, ("spec",)), True),
        _tool("planning_export", "Validate then export editable DXF, parameters, result and QA to a new directory. Optional CAD output requires cad_new=true AND confirm_cad_new=true; only a bridge-created separate drawing is written.",
              EXPORT_SCHEMA, False),
        _tool("planning_export_control_sheet", "Generate parcels from an explicit regulatory_parcels spec, then export an editable single-parcel control sheet by parcel_id. Values remain user assumptions; missing values are shown as unverified. Uses a new output directory and the same optional CAD authorization rule.",
              _object_schema({**EXPORT_SCHEMA["properties"], "parcel_id": {"type": "string", "minLength": 1, "maxLength": 128}},
                             ("spec", "out", "parcel_id")), False),
    ]


def _bounded_json(value):
    """Reject invalid/non-finite values and excessive nesting before engine calls."""
    count = 0

    def walk(item, depth):
        nonlocal count
        count += 1
        if count > MAX_NODES or depth > 32:
            raise RpcError(-32602, "Input exceeds the supported JSON size or depth")
        if isinstance(item, dict):
            if len(item) > 1000 or any(not isinstance(k, str) or len(k) > 512 for k in item):
                raise RpcError(-32602, "Invalid or excessive object keys")
            for child in item.values():
                walk(child, depth + 1)
        elif isinstance(item, list):
            if len(item) > 10000:
                raise RpcError(-32602, "Arrays are limited to 10000 items")
            for child in item:
                walk(child, depth + 1)
        elif isinstance(item, str):
            if len(item) > 65536:
                raise RpcError(-32602, "String exceeds the supported length")
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            try:
                finite = math.isfinite(item)
            except OverflowError:
                finite = False
            if not finite:
                raise RpcError(-32602, "All numbers must be finite")
        elif item is not None and not isinstance(item, bool):
            raise RpcError(-32602, "Unsupported JSON value")

    walk(value, 0)


def _validate_arguments(name, arguments):
    definition = next((tool for tool in tool_definitions() if tool["name"] == name), None)
    if definition is None:
        raise RpcError(-32602, "Unknown tool: " + name)
    _bounded_json(arguments)
    from jsonschema import Draft202012Validator
    error = next(Draft202012Validator(definition["inputSchema"]).iter_errors(arguments), None)
    if error:
        location = "/".join(str(v) for v in error.absolute_path) or "arguments"
        # Do not echo arbitrary user input in protocol diagnostics.
        raise RpcError(-32602, f"Invalid {location}: input does not satisfy {error.validator}")


def _engine(spec):
    kind = spec.get("kind")
    if kind in (None, "road_plan"):
        module, export = "app.geometry", "export_dxf"
    elif kind == "road_cross_section":
        module, export = "app.sections", "export_section_dxf"
    elif kind == "regulatory_parcels":
        module, export = "app.parcels", "export_parcels_dxf"
    else:
        raise ToolError("unsupported_kind", "Unsupported planning spec kind")
    try:
        engine = importlib.import_module(module)
    except ImportError as exc:
        raise ToolError("engine_unavailable", f"Required engine module unavailable: {module}") from exc
    return engine.generate, getattr(engine, export)


def _generate(spec):
    generate, exporter = _engine(spec)
    result = generate(spec)
    from app.rules import annotate
    annotate(result)
    # Serializability and finiteness are checked before any output file is made.
    json.dumps(result, ensure_ascii=False, allow_nan=False)
    return result, exporter


def _summary(result):
    return {"status": "invalid" if result["report"]["errors"] else "validated",
            "report": result["report"], "metrics": result["metrics"],
            "bounds": result["bounds"], "entity_count": len(result["entities"]),
            "scope": "Geometry and explicit limited rules only; not approval or full standards compliance."}


def _new_output_path(raw):
    if any(ord(c) < 32 for c in raw) or raw.startswith(("\\\\", "//")) or "://" in raw:
        raise ToolError("invalid_output_path", "Use an absolute local filesystem path, not a URL or network share")
    path = Path(raw)
    if not path.is_absolute() or not path.name or (os.name == "nt" and ":" in str(path)[2:]):
        raise ToolError("invalid_output_path", "An absolute local output path is required")
    if path.exists() or path.is_symlink():
        raise ToolError("output_exists", "Output directory already exists; choose a new directory")
    if not path.parent.is_dir():
        raise ToolError("output_parent_missing", "Output parent directory must already exist")
    return path.resolve()


def _write_json(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _export(arguments, control_sheet=False):
    if arguments.get("cad_new", False) and not arguments.get("confirm_cad_new", False):
        raise ToolError("cad_authorization_required", "Creating a new CAD drawing requires confirm_cad_new=true and user authorization")
    out = _new_output_path(arguments["out"])
    result, exporter = _generate(arguments["spec"])
    if result["report"]["errors"]:
        raise ToolError("validation_failed", "Geometry errors prevent export; no output directory was created", report=result["report"])
    if control_sheet:
        if arguments["spec"].get("kind") != "regulatory_parcels":
            raise ToolError("wrong_sheet_kind", "Control sheets require a regulatory_parcels spec")
        from app.parcels import build_control_sheet
        try:
            result = build_control_sheet(result, arguments["parcel_id"])
        except (ValueError, KeyError) as exc:
            raise ToolError("control_sheet_failed", str(exc)) from exc
        from app.rules import annotate
        annotate(result)
        if result["report"]["errors"]:
            raise ToolError("validation_failed", "Control sheet errors prevent export", report=result["report"])
        json.dumps(result, ensure_ascii=False, allow_nan=False)
    if arguments.get("cad_new", False) and arguments["spec"].get("units") != "m":
        raise ToolError("cad_units_unsupported", "CAD bridge output currently requires metres; changing the label does not convert coordinates")
    # Atomic claim of the new directory prevents overwriting an existing target.
    out.mkdir()
    files = []
    try:
        for name, data in (("parameters.json", arguments["spec"]), ("quality.json", result["report"]), ("result.json", result)):
            _write_json(out / name, data)
            files.append(str(out / name))
        exporter(result, out / "drawing.dxf")
        files.append(str(out / "drawing.dxf"))
        if arguments["spec"].get("kind") == "regulatory_parcels" and not control_sheet:
            from app.parcels import export_parcels_csv, export_parcels_json
            for filename, writer in (("parcels.csv", export_parcels_csv), ("parcels.json", export_parcels_json)):
                writer(result, out / filename)
                files.append(str(out / filename))
        cad = None
        if arguments.get("cad_new", False):
            from app.cad import CadBridge
            bridge = CadBridge(out)
            try:
                document = bridge.new_document()
                doc_id = document["document_id"]
                applied = bridge.apply(doc_id, result["entities"], "mcp-" + uuid.uuid4().hex, document.get("version"))
                saved = bridge.save(doc_id, out / "drawing.dwg")
                cad = {"applied": applied, "saved": saved}
                _write_json(out / "cad-readback.json", cad)
                files.extend([str(out / "drawing.dwg"), str(out / "cad-readback.json")])
            finally:
                bridge.close()
        return {"status": "exported", "output": str(out), "files": files,
                "metrics": result["metrics"], "report": result["report"], "cad": cad}
    except Exception as exc:
        # Preserve partial files for diagnosis, never pretend CAD side effects were undone.
        failure = {"status": "partial_failure", "output": str(out), "files": files,
                   "message": str(exc), "error_type": type(exc).__name__,
                   "note": "Partial output is preserved. A CAD drawing may remain open; inspect before retrying with another new directory."}
        try:
            _write_json(out / "failure.json", failure)
        except OSError:
            pass
        raise ToolError("export_failed", "Export failed after output creation", partial_failure=failure) from exc


def call_tool(name, arguments):
    _validate_arguments(name, arguments)
    try:
        if name == "planning_cases":
            from app.cases import get_case, list_cases
            if "case_id" not in arguments:
                if "variant" in arguments:
                    raise RpcError(-32602, "variant requires case_id")
                payload = {"cases": list_cases()}
            else:
                try:
                    case = get_case(arguments["case_id"])
                except KeyError as exc:
                    raise ToolError("unknown_case", "Unknown teaching case") from exc
                if "variant" in arguments:
                    variant = next((v for v in case.get("variants", []) if v["id"] == arguments["variant"]), None)
                    if variant is None:
                        raise ToolError("unknown_variant", "Unknown variant for the selected teaching case")
                    case["spec"] = variant["spec"]
                    case["selected_variant"] = variant["id"]
                payload = case
        elif name == "planning_validate":
            payload = _summary(_generate(arguments["spec"])[0])
        else:
            payload = _export(arguments, control_sheet=name == "planning_export_control_sheet")
        is_error = False
    except RpcError:
        raise
    except ToolError as exc:
        payload, is_error = exc.payload, True
    except Exception as exc:
        print(f"Tool error: {type(exc).__name__}: {exc}", file=sys.stderr)
        payload, is_error = {"status": "failed", "code": "tool_execution_error", "message": str(exc)}, True
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, allow_nan=False)}],
            "structuredContent": payload, "isError": is_error}


class Server:
    def __init__(self):
        self.initialized = False
        self.ready = False

    def handle(self, message):
        # MCP 2025-06-18+ does not support JSON-RPC batch messages.
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return self.error(None, -32600, "Expected one JSON-RPC 2.0 request or notification; batches are unsupported")
        has_id = "id" in message
        request_id = message.get("id")
        if has_id and (isinstance(request_id, bool) or not isinstance(request_id, (str, int))):
            return self.error(None, -32600, "Request id must be a string or integer")
        try:
            if set(message) - {"jsonrpc", "id", "method", "params"}:
                raise RpcError(-32600, "Unexpected request fields")
            params = message.get("params", {})
            if not isinstance(params, dict):
                raise RpcError(-32602, "params must be an object")
            _bounded_json(params)
            method = message["method"]
            if not has_id:
                if method == "notifications/initialized" and self.initialized:
                    self.ready = True
                elif method != "notifications/initialized":
                    print("Ignored notification: " + method[:200], file=sys.stderr)
                # Notifications never execute tools and never receive replies.
                return None
            if method == "initialize":
                if self.initialized:
                    raise RpcError(-32600, "Session has already been initialized")
                if not isinstance(params.get("protocolVersion"), str) or not isinstance(params.get("capabilities"), dict):
                    raise RpcError(-32602, "initialize requires protocolVersion and capabilities")
                info = params.get("clientInfo")
                if not isinstance(info, dict) or not all(isinstance(info.get(k), str) and info[k] for k in ("name", "version")):
                    raise RpcError(-32602, "initialize requires clientInfo name and version")
                self.initialized = True
                version = params["protocolVersion"] if params["protocolVersion"] in SUPPORTED_PROTOCOLS else PROTOCOL
                result = {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": "planning-workbench-open", "version": "0.2.0"},
                          "instructions": "Independent planning teaching engine. Validate before export. New CAD drawings require explicit authorization. No active-drawing editing or arbitrary command execution."}
            elif method == "ping":
                result = {}
            elif not self.ready:
                raise RpcError(-32002, "Initialize the session and send notifications/initialized first")
            elif method == "tools/list":
                if set(params) - {"_meta"}:
                    raise RpcError(-32602, "This fixed tool list has no pagination cursor")
                result = {"tools": tool_definitions()}
            elif method == "tools/call":
                if set(params) - {"name", "arguments", "_meta"} or not isinstance(params.get("name"), str):
                    raise RpcError(-32602, "tools/call requires a tool name and optional arguments object")
                result = call_tool(params["name"], params.get("arguments", {}))
            else:
                raise RpcError(-32601, "Method not found")
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RpcError as exc:
            return self.error(request_id, exc.code, str(exc)) if has_id else None
        except Exception as exc:
            print(f"Request error: {type(exc).__name__}: {exc}", file=sys.stderr)
            return self.error(request_id, -32603, "Internal error") if has_id else None

    @staticmethod
    def error(request_id, code, message):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _no_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON object key")
        value[key] = item
    return value


def _reject_constant(value):
    raise ValueError("Non-finite JSON numeric literal")


def main():
    server = Server()
    input_stream = sys.stdin.buffer
    output_stream = sys.stdout
    if hasattr(output_stream, "reconfigure"):
        output_stream.reconfigure(encoding="utf-8", errors="strict", newline="\n")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    while True:
        line = input_stream.readline(MAX_LINE_BYTES + 1)
        if not line:
            break
        if len(line) > MAX_LINE_BYTES:
            while line and not line.endswith(b"\n"):
                line = input_stream.readline(MAX_LINE_BYTES + 1)
            response = server.error(None, -32700, "Message exceeds the 2 MiB line limit")
        else:
            try:
                message = json.loads(line.decode("utf-8"), object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)
            except (UnicodeError, ValueError, RecursionError):
                response = server.error(None, -32700, "Invalid UTF-8 JSON message")
            else:
                # A dependency's incidental prints cannot corrupt stdout framing.
                with contextlib.redirect_stdout(sys.stderr):
                    response = server.handle(message)
        if response is not None:
            try:
                output_stream.write(json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
                output_stream.flush()
            except BrokenPipeError:
                return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
