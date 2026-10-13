"""Small explicit-opt-in MCP stdio client. No shell and no detached children."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

PROTOCOL_VERSION = "2025-06-18"
MAX_MESSAGE_BYTES = 2 * 1024 * 1024


class McpError(RuntimeError):
    pass


class StdioMcpClient:
    def __init__(self, command: list[str], cwd: Path | None = None, *, authorized=False, timeout=10):
        if not authorized:
            raise McpError("Starting an external MCP process requires explicit user authorization")
        if not isinstance(command, list) or not command or any(not isinstance(v, str) or not v or "\x00" in v for v in command):
            raise McpError("MCP command must be a nonempty argument list")
        if not 0.1 <= timeout <= 120:
            raise McpError("MCP timeout must be between 0.1 and 120 seconds")
        self.timeout = float(timeout)
        self._incoming = queue.Queue(maxsize=128)
        self._lock = threading.Lock()
        self._next_id = 0
        self.initialized = False
        self.server_info = None
        self._closed = False
        # Do not implicitly give third-party MCP children provider API keys.
        env = {name: os.environ[name] for name in
               ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATHEXT")
               if name in os.environ}
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        self._process = subprocess.Popen(command, cwd=str(cwd) if cwd else None,
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, env=env, shell=False,
                                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self._reader = threading.Thread(target=self._read_stdout, daemon=True, name="MCP-stdout")
        self._stderr_reader = threading.Thread(target=self._drain_stderr, daemon=True, name="MCP-stderr")
        self._reader.start()
        self._stderr_reader.start()

    @property
    def pid(self):
        return self._process.pid

    def _read_stdout(self):
        try:
            while not self._closed:
                raw = self._process.stdout.readline(MAX_MESSAGE_BYTES + 1)
                if not raw:
                    self._incoming.put_nowait(McpError("MCP child closed stdout"))
                    return
                if len(raw) > MAX_MESSAGE_BYTES:
                    raise McpError("MCP response exceeded the message size limit")
                message = json.loads(raw.decode("utf-8"))
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise McpError("Invalid MCP JSON-RPC message")
                self._incoming.put_nowait(message)
        except Exception as exc:
            try:
                self._incoming.put_nowait(exc if isinstance(exc, McpError) else McpError(f"Invalid MCP stdout: {type(exc).__name__}"))
            except queue.Full:
                pass

    def _drain_stderr(self):
        # Drain to avoid pipe deadlocks, but never copy external stderr into logs,
        # web responses or artifacts where a server might have printed secrets.
        try:
            while not self._closed and self._process.stderr.read(4096):
                pass
        except (OSError, ValueError):
            pass

    def _send(self, message):
        if self._closed or self._process.poll() is not None:
            raise McpError("MCP child is not running")
        raw = (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(raw) > MAX_MESSAGE_BYTES:
            raise McpError("MCP request exceeded the message size limit")
        try:
            self._process.stdin.write(raw)
            self._process.stdin.flush()
        except (OSError, BrokenPipeError) as exc:
            raise McpError("MCP child input pipe closed") from exc

    def _request(self, method, params):
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            deadline = time.monotonic() + self.timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.close()
                    raise McpError(f"MCP request timed out: {method}; owned child terminated")
                try:
                    message = self._incoming.get(timeout=remaining)
                except queue.Empty:
                    self.close()
                    raise McpError(f"MCP request timed out: {method}; owned child terminated")
                if isinstance(message, Exception):
                    self.close()
                    raise message
                if "method" in message:
                    if "id" in message:
                        # No sampling, roots, elicitation or execution capabilities
                        # are advertised. Reject server requests rather than act.
                        self._send({"jsonrpc": "2.0", "id": message["id"],
                                    "error": {"code": -32601, "message": "Client capability unavailable"}})
                    continue
                if message.get("id") != request_id:
                    self.close()
                    raise McpError("Unexpected MCP response id")
                if "error" in message:
                    err = message["error"]
                    raise McpError(f"MCP protocol error {err.get('code')}: {str(err.get('message', ''))[:300]}")
                if "result" not in message:
                    raise McpError("MCP response did not contain result")
                return message["result"]

    def initialize(self):
        if self.initialized:
            return self.server_info
        result = self._request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                               "clientInfo": {"name": "PlanningWorkbench", "version": "0.1.0"}})
        if not isinstance(result, dict) or result.get("protocolVersion") not in (PROTOCOL_VERSION, "2025-03-26", "2024-11-05"):
            self.close()
            raise McpError("Unsupported MCP protocol version")
        if not isinstance(result.get("capabilities"), dict) or not isinstance(result.get("serverInfo"), dict):
            self.close()
            raise McpError("Invalid MCP initialize result")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.initialized, self.server_info = True, result
        return result

    def list_tools(self):
        self.initialize()
        tools, cursor = [], None
        for _ in range(20):
            result = self._request("tools/list", {"cursor": cursor} if cursor else {})
            if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
                raise McpError("Invalid MCP tools/list result")
            tools.extend(result["tools"])
            cursor = result.get("nextCursor")
            if not cursor:
                return tools
        raise McpError("MCP tool listing exceeded the 20-page limit")

    def call_tool(self, name: str, arguments: dict):
        self.initialize()
        if not isinstance(name, str) or not name or not isinstance(arguments, dict):
            raise McpError("Tool call needs a name and an arguments object")
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict) or not isinstance(result.get("content"), list):
            raise McpError("Invalid MCP tools/call result")
        return result

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self._process.wait(timeout=0.4)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
        self._reader.join(timeout=0.5)
        self._stderr_reader.join(timeout=0.5)
        for stream in (self._process.stdout, self._process.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def run_builtin_diagnostic():
    """Only run our fixed, read-only fixture. Never take a web-supplied command."""
    fixture = Path(__file__).with_name("mcp_fixture.py")
    with StdioMcpClient([sys.executable, "-u", str(fixture)], cwd=fixture.parent.parent,
                        authorized=True, timeout=8) as client:
        initialized = client.initialize()
        tools = client.list_tools()
        echo = client.call_tool("echo", {"text": "PlanningWorkbench MCP roundtrip"})
        summary = client.call_tool("summarize_geometry", {"entities": [
            {"type": "line", "layer": "ROAD_CENTER"}, {"type": "arc", "layer": "ROAD_JUNCTION"}]})
        pid = client.pid
        passed = (echo.get("structuredContent", {}).get("text") == "PlanningWorkbench MCP roundtrip"
                  and summary.get("structuredContent", {}).get("entity_count") == 2
                  and not echo.get("isError") and not summary.get("isError"))
    return {"success": passed, "transport": "stdio", "protocol": initialized["protocolVersion"],
            "server": initialized["serverInfo"], "tools": tools, "echo": echo, "summary": summary,
            "owned_child_pid": pid, "child_exited": client._process.poll() is not None,
            "scope": "Built-in read-only fixture only; external MCP servers and model-mediated tool selection are unverified"}
