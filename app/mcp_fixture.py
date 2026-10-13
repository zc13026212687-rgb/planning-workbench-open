"""Independent read-only MCP stdio fixture, never writes files or executes tools."""
import json
import sys
from collections import Counter

TOOLS = [
    {"name": "echo", "description": "Return a bounded text value unchanged.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string", "maxLength": 4096}},
                     "required": ["text"], "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}},
    {"name": "summarize_geometry", "description": "Count supplied entities by type and layer, without accessing a CAD drawing.",
     "inputSchema": {"type": "object", "properties": {"entities": {"type": "array", "maxItems": 5000,
                     "items": {"type": "object", "properties": {"type": {"type": "string"}, "layer": {"type": "string"}},
                               "required": ["type"], "additionalProperties": True}}},
                     "required": ["entities"], "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}},
]


def tool(name, args):
    if not isinstance(args, dict):
        raise ValueError("arguments must be an object")
    if name == "echo":
        if set(args) != {"text"} or not isinstance(args["text"], str) or len(args["text"]) > 4096:
            raise ValueError("echo needs one text string of at most 4096 characters")
        return {"text": args["text"]}
    if name == "summarize_geometry":
        values = args.get("entities")
        if set(args) != {"entities"} or not isinstance(values, list) or len(values) > 5000:
            raise ValueError("summarize_geometry needs an entities array of at most 5000 items")
        if any(not isinstance(e, dict) or not isinstance(e.get("type"), str)
               or not isinstance(e.get("layer", "0"), str) for e in values):
            raise ValueError("entity type and layer must be strings")
        return {"entity_count": len(values), "by_type": dict(Counter(e["type"] for e in values)),
                "by_layer": dict(Counter(e.get("layer", "0") for e in values))}
    raise ValueError("Unknown read-only tool")


def main():
    initialized = False
    for raw in sys.stdin.buffer:
        try:
            if len(raw) > 2 * 1024 * 1024:
                break
            request = json.loads(raw)
            request_id = request.get("id")
            method, params = request.get("method"), request.get("params", {})
            if method == "notifications/initialized":
                initialized = True
                continue
            if request_id is None:
                continue
            if method == "initialize":
                result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": "planning-workbench-readonly-fixture", "version": "0.1.0"}}
            elif not initialized:
                raise ValueError("Initialize the MCP session first")
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                try:
                    data = tool(params.get("name"), params.get("arguments", {}))
                    result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                              "structuredContent": data, "isError": False}
                except ValueError as exc:
                    result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
            elif method == "ping":
                result = {}
            else:
                raise ValueError("Unsupported JSON-RPC method")
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(locals().get("request"), dict) else None,
                        "error": {"code": -32602, "message": str(exc)[:300]}}
        sys.stdout.buffer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
