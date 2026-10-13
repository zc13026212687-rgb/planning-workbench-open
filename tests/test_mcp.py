import sys
from pathlib import Path

import pytest

from app.mcp_client import McpError, StdioMcpClient, run_builtin_diagnostic

FIXTURE = Path(__file__).resolve().parents[1] / "app" / "mcp_fixture.py"


def test_real_stdio_initialize_list_call_and_clean_exit():
    result = run_builtin_diagnostic()
    assert result["success"] and result["child_exited"]
    assert {t["name"] for t in result["tools"]} == {"echo", "summarize_geometry"}
    assert result["summary"]["structuredContent"]["by_type"] == {"line": 1, "arc": 1}


def test_utf8_echo_and_tool_input_error_do_not_fake_success():
    with StdioMcpClient([sys.executable, "-u", str(FIXTURE)], authorized=True) as client:
        echoed = client.call_tool("echo", {"text": "道路中心线 → 圆角"})
        assert echoed["structuredContent"]["text"] == "道路中心线 → 圆角"
        assert not echoed["isError"]
        rejected = client.call_tool("echo", {"text": 25})
        assert rejected["isError"]
        assert client._process.poll() is None
    assert client._process.poll() is not None


def test_external_child_requires_explicit_authorization():
    with pytest.raises(McpError, match="authorization"):
        StdioMcpClient([sys.executable, "-c", "raise SystemExit(99)"])


def test_timeout_terminates_only_the_owned_child():
    client = StdioMcpClient([sys.executable, "-u", "-c", "import time; time.sleep(30)"],
                            authorized=True, timeout=0.15)
    with pytest.raises(McpError, match="timed out"):
        client.initialize()
    assert client._process.poll() is not None


def test_non_protocol_stdout_is_rejected_and_child_closed():
    client = StdioMcpClient([sys.executable, "-u", "-c", "import time; print('not JSON'); time.sleep(30)"],
                            authorized=True, timeout=2)
    with pytest.raises(McpError, match="Invalid MCP stdout"):
        client.initialize()
    assert client._process.poll() is not None


def test_provider_key_environment_is_not_inherited(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "TEST_SENTINEL_DO_NOT_INHERIT")
    code = (
        "import sys,json,os; q=json.loads(sys.stdin.readline()); "
        "print(json.dumps({'jsonrpc':'2.0','id':q['id'],'result':{'protocolVersion':'2025-06-18',"
        "'capabilities':{},'serverInfo':{'name':'env-test','version':'1',"
        "'provider_key_inherited':'OPENAI_API_KEY' in os.environ}}}),flush=True); sys.stdin.read()"
    )
    with StdioMcpClient([sys.executable, "-u", "-c", code], authorized=True) as client:
        assert client.initialize()["serverInfo"]["provider_key_inherited"] is False
