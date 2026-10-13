"""Transport fixtures only: these tests never contact or pay a real provider."""
import json
import threading

import httpx
import pytest

from app import providers
from app.store import Store

FAKE_KEY = "test-only-not-a-real-api-key"
FAKE_HEADER = "test-only-extra-header-secret"


class ChunkedStream(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    def __iter__(self):
        yield from self.chunks


def sse(*packets, done=True):
    wire = "".join("data: " + json.dumps(p, ensure_ascii=False) + "\n\n" for p in packets)
    if done:
        wire += "data: [DONE]\n\n"
    data = wire.encode("utf-8")
    return ChunkedStream([data[i:i + 7] for i in range(0, len(data), 7)])


def install_mock(monkeypatch, handler):
    original_client = httpx.Client
    def factory(*args, **kwargs):
        return original_client(*args, transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(providers.httpx, "Client", factory)


def profile(protocol="chat_completions"):
    return {"id": "fixture", "name": "Fixture", "protocol": protocol,
            "base_url": "https://fixture.invalid/v1", "model": "fixture-model", "timeout": 10,
            "secret": providers.protect({"api_key": FAKE_KEY, "headers": {"X-Fixture": FAKE_HEADER}})}


def run(p, emit=lambda *args: None, cancel=None, messages=None, tools=None):
    return providers.chat_response(p, messages or [{"role": "user", "content": "test"}],
                                   tools or [], emit, cancel or threading.Event())


def test_chat_fragmented_tool_calls_usage_and_utf8(monkeypatch):
    requests, emitted = [], []
    packets = [
        {"choices": [{"index": 0, "delta": {"content": "道路"}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                    "function": {"name": "road_", "arguments": '{"left_'}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"name": "generate", "arguments": 'width":8}'}}]}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19}},
    ]
    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=sse(*packets))
    install_mock(monkeypatch, handler)
    result = run(profile(), lambda *event: emitted.append(event), tools=[{"name": "road_generate", "parameters": {"type": "object"}}])
    assert len(requests) == 1
    assert str(requests[0].url) == "https://fixture.invalid/v1/chat/completions"
    assert requests[0].headers["Authorization"] == "Bearer " + FAKE_KEY
    assert requests[0].headers["X-Fixture"] == FAKE_HEADER
    assert json.loads(requests[0].content)["tools"][0]["function"]["name"] == "road_generate"
    assert result["text"] == "道路"
    assert emitted == [("token", "道路")]
    assert result["calls"] == [{"id": "call_1", "name": "road_generate", "arguments": '{"left_width":8}', "parsed": {"left_width": 8}}]
    assert result["usage"]["total_tokens"] == 19


def test_responses_tool_item_done_and_final_usage(monkeypatch):
    seen = []
    item = {"id": "fc_item", "type": "function_call", "call_id": "call_actual", "name": "road_generate", "arguments": '{"width":12}'}
    packets = [
        {"type": "response.output_item.added", "output_index": 0, "item": {**item, "arguments": ""}},
        {"type": "response.function_call_arguments.delta", "output_index": 0, "item_id": "fc_item", "delta": '{"width":'},
        {"type": "response.function_call_arguments.delta", "output_index": 0, "item_id": "fc_item", "delta": "12}"},
        {"type": "response.function_call_arguments.done", "output_index": 0, "arguments": '{"width":12}'},
        {"type": "response.output_item.done", "output_index": 0, "item": item},
        {"type": "response.completed", "response": {"status": "completed", "output": [item],
         "usage": {"input_tokens": 20, "output_tokens": 6, "total_tokens": 26}}},
    ]
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, stream=sse(*packets, done=False))
    install_mock(monkeypatch, handler)
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "call_previous", "type": "function",
                  "function": {"name": "road_read", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "call_previous", "content": "ok"}]
    result = run(profile("responses"), messages=messages, tools=[{"name": "road_generate", "parameters": {"type": "object"}}])
    assert result["calls"][0]["id"] == "call_actual"  # Must not use the response item id.
    assert result["calls"][0]["parsed"] == {"width": 12}
    assert result["usage"]["total_tokens"] == 26
    assert seen[0]["store"] is False
    assert seen[0]["input"][-1] == {"type": "function_call_output", "call_id": "call_previous", "output": "ok"}
    assert seen[0]["tools"][0]["type"] == "function"
    assert "function" not in seen[0]["tools"][0]


@pytest.mark.parametrize("protocol,packet", [("chat_completions", {"choices": [{"delta": {"content": "partial"}}]}),
                                             ("responses", {"type": "response.output_text.delta", "delta": "partial"})])
def test_partial_stream_refuses_completion_and_never_replays(monkeypatch, protocol, packet):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=sse(packet))
    install_mock(monkeypatch, handler)
    with pytest.raises(providers.ProviderError, match="未收到完成"):
        run(profile(protocol))
    assert len(calls) == 1


@pytest.mark.parametrize("finish_reason", ["length", "content_filter"])
def test_chat_truncation_is_not_success(monkeypatch, finish_reason):
    install_mock(monkeypatch, lambda request: httpx.Response(200, stream=sse({"choices": [{"delta": {}, "finish_reason": finish_reason}]})))
    with pytest.raises(providers.ProviderError, match="截断或过滤"):
        run(profile())


def test_401_error_body_and_secret_not_exposed(monkeypatch):
    install_mock(monkeypatch, lambda request: httpx.Response(401, text=f"debug echo {FAKE_KEY} / {FAKE_HEADER}"))
    with pytest.raises(providers.ProviderError) as captured:
        run(profile())
    message = str(captured.value)
    assert "401" in message and "身份验证失败" in message
    assert FAKE_KEY not in message and FAKE_HEADER not in message and "debug echo" not in message


def test_network_exception_is_redacted_and_not_retried(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("sensitive echo " + FAKE_KEY)
    install_mock(monkeypatch, handler)
    with pytest.raises(providers.ProviderError) as captured:
        run(profile())
    assert FAKE_KEY not in str(captured.value)
    assert len(calls) == 1


def test_cancelled_before_start_does_not_send_http(monkeypatch):
    calls = []
    install_mock(monkeypatch, lambda request: calls.append(request))
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(providers.Cancelled):
        run(profile(), cancel=cancel)
    assert calls == []


def test_cancel_between_stream_events_stops_consumption(monkeypatch):
    cancel, emitted = threading.Event(), []
    packets = [{"choices": [{"delta": {"content": "first"}}]},
               {"choices": [{"delta": {"content": "second"}}]},
               {"choices": [{"delta": {}, "finish_reason": "stop"}]}]
    install_mock(monkeypatch, lambda request: httpx.Response(200, stream=sse(*packets)))
    def emit(kind, value):
        emitted.append(value)
        cancel.set()
    with pytest.raises(providers.Cancelled):
        run(profile(), emit=emit, cancel=cancel)
    assert emitted == ["first"]


@pytest.mark.parametrize("args", ['{"unfinished":', "[]"])
def test_invalid_tool_argument_shape_rejected(monkeypatch, args):
    packet = {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "x", "function": {"name": "road_generate", "arguments": args}}]},
                           "finish_reason": "tool_calls"}]}
    install_mock(monkeypatch, lambda request: httpx.Response(200, stream=sse(packet)))
    with pytest.raises(providers.ProviderError, match="工具参数"):
        run(profile())


def test_dpapi_storage_public_profile_and_secret_preserving_edit(tmp_path):
    store = Store(tmp_path)
    body = {"name": "Local fixture", "base_url": "https://fixture.invalid/v1", "model": "m",
            "api_key": FAKE_KEY, "headers": {"X-Fixture": FAKE_HEADER}}
    public = providers.save_profile(store, body)
    assert public["has_key"] is True
    assert public["header_names"] == ["X-Fixture"]
    assert not {"secret", "api_key", "headers"} & public.keys()
    raw = store.get("providers", public["id"])
    encoded = json.dumps(raw)
    assert FAKE_KEY not in encoded and FAKE_HEADER not in encoded
    assert providers.unprotect(raw["secret"]) == {"api_key": FAKE_KEY, "headers": {"X-Fixture": FAKE_HEADER}}
    public2 = providers.save_profile(store, {"id": public["id"], "name": "Renamed", "model": "m2", "base_url": body["base_url"]})
    assert public2["name"] == "Renamed" and public2["has_key"] is True
    assert providers.unprotect(store.get("providers", public["id"])["secret"])["api_key"] == FAKE_KEY
    store.db.execute("pragma wal_checkpoint(TRUNCATE)")
    assert FAKE_KEY.encode() not in (tmp_path / "workbench.sqlite3").read_bytes()
    assert FAKE_HEADER.encode() not in (tmp_path / "workbench.sqlite3").read_bytes()
    store.db.close()


def test_legacy_plaintext_fields_not_rewritten_in_new_record(tmp_path):
    store = Store(tmp_path)
    old = {"id": "legacy", "name": "old", "model": "m", "base_url": "https://fixture.invalid/v1",
           "api_key": "legacy-plaintext", "headers": {"X-Old": "legacy-header"}}
    store.put("providers", old)
    providers.save_profile(store, {"id": "legacy", "name": "new", "model": "m", "base_url": old["base_url"], "api_key": FAKE_KEY})
    saved = store.get("providers", "legacy")
    assert "api_key" not in saved and "headers" not in saved
    assert providers.unprotect(saved["secret"])["api_key"] == FAKE_KEY
    store.db.close()


def test_partial_profile_edit_preserves_protocol_endpoint_timeout_and_secret(tmp_path):
    store = Store(tmp_path)
    public = providers.save_profile(store, {"name": "Responses", "model": "m", "protocol": "responses",
        "base_url": "https://fixture.invalid/v1", "timeout": 45, "api_key": FAKE_KEY})
    changed = providers.save_profile(store, {"id": public["id"], "name": "Renamed"})
    assert changed["protocol"] == "responses"
    assert changed["base_url"] == "https://fixture.invalid/v1"
    assert changed["timeout"] == 45
    assert changed["has_key"] is True
    store.db.close()


@pytest.mark.parametrize("url", ["http://remote.example/v1", "https://name:password@example.test/v1", "https://example.test/v1?key=foo"])
def test_profile_rejects_remote_http_or_embedded_credentials(tmp_path, url):
    store = Store(tmp_path)
    with pytest.raises(ValueError):
        providers.save_profile(store, {"name": "x", "model": "m", "base_url": url})
    assert store.list("providers") == []
    store.db.close()
