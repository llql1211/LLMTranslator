"""流式请求与逐块解析"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


class FakeStreamResponse:
    """假流式响应：逐行产出给定内容，并记录是否被关闭"""

    def __init__(self, lines=(), error: Exception | None = None, status_code=200, headers=None):
        self._lines = list(lines)
        self._error = error
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def iter_lines(self):
        yield from self._lines

    def close(self):
        self.closed = True


def ndjson(*chunks) -> list[bytes]:
    """把若干分块编码成 Ollama 的 NDJSON 行"""
    return [json.dumps(c).encode("utf-8") for c in chunks]


def sse(*chunks) -> list[bytes]:
    """把若干分块编码成 OpenAI 的 SSE 行"""
    return [f"data: {json.dumps(c)}".encode("utf-8") for c in chunks]


@pytest.fixture
def stream_post(app, monkeypatch):
    """替换 requests.post，返回记录调用信息的容器"""
    state = SimpleNamespace(calls=[], response=FakeStreamResponse())

    def fake_post(url, json=None, headers=None, timeout=None, stream=False, **kwargs):
        state.calls.append(
            SimpleNamespace(
                url=url,
                payload=json,
                headers=headers,
                timeout=timeout,
                stream=stream,
            )
        )
        return state.response

    monkeypatch.setattr(app, "requests", SimpleNamespace(post=fake_post))
    return state


# ===== Ollama NDJSON 逐行解析 =====


def test_ollama_line_returns_delta(app):
    assert app.parse_ollama_stream_line('{"response": "你好", "done": false}') == "你好"


def test_ollama_line_tolerates_surrounding_whitespace(app):
    assert app.parse_ollama_stream_line('  {"response": "好"}  ') == "好"


@pytest.mark.parametrize(
    "line",
    [
        "",
        "   ",
        "not json",
        "[1, 2]",
        '"纯字符串"',
        "123",
        '{"other": 1}',
        '{"response": ""}',
        '{"response": null}',
        '{"response": 42}',
    ],
)
def test_ollama_line_without_text_is_skipped(app, line):
    """空行、坏 JSON、无内容的分块不应产出文本"""
    assert app.parse_ollama_stream_line(line) is None


# ===== OpenAI SSE 逐行解析 =====


def test_openai_line_returns_delta(app):
    line = 'data: {"choices": [{"delta": {"content": "你好"}}]}'
    assert app.parse_openai_stream_line(line) == "你好"


def test_openai_done_marker_has_no_text(app):
    assert app.parse_openai_stream_line("data: [DONE]") is None


@pytest.mark.parametrize(
    "line",
    [
        "",
        ": keep-alive",
        "event: message",
        "data:",
        "data: [DONE]",
        "data: {坏 json",
        "data: [1, 2]",
        "data: 123",
        'data: {"choices": []}',
        'data: {"choices": [{"delta": {}}]}',
        'data: {"choices": [{"delta": {"content": null}}]}',
        '{"choices": [{"delta": {"content": "你好"}}]}',
    ],
)
def test_openai_line_without_content_is_skipped(app, line):
    """非 data: 行、结束标记、坏 JSON、无内容的分块不应产出文本"""
    assert app.parse_openai_stream_line(line) is None


# ===== 流式请求 =====


def test_stream_request_is_flagged(app, stream_post, monkeypatch):
    """流式请求应带 stream=True，并以流式方式读取响应"""
    monkeypatch.setattr(app, "API_KEY", "")
    stream_post.response = FakeStreamResponse()

    list(app.translate_stream("hello"))

    call = stream_post.calls[0]
    assert call.payload["stream"] is True
    assert call.stream is True
    assert call.timeout == 30


def test_non_stream_request_is_not_flagged(app, monkeypatch):
    """一次性请求不应开启流式"""
    state = SimpleNamespace(calls=[], payload=None)

    class FakeJsonResponse:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            pass

        def json(self):
            return {"response": "好"}

        def close(self):
            pass

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        state.calls.append(kwargs)
        return FakeJsonResponse()

    monkeypatch.setattr(app, "API_KEY", "")
    monkeypatch.setattr(app, "requests", SimpleNamespace(post=fake_post))

    app.translate_with_llm("hello")

    assert state.calls[0].get("stream") is None


def test_ollama_stream_yields_deltas(app, stream_post, monkeypatch):
    """Ollama 流式响应逐块产出增量文本，忽略无内容的收尾分块"""
    monkeypatch.setattr(app, "API_KEY", "")
    stream_post.response = FakeStreamResponse(
        ndjson(
            {"response": "你", "done": False},
            {"response": "好", "done": False},
            {"response": "", "done": True},
        )
    )

    assert list(app.translate_stream("hello")) == ["你", "好"]


def test_openai_stream_yields_deltas(app, stream_post, monkeypatch):
    """OpenAI 流式响应逐块产出增量文本，忽略注释行与结束标记"""
    monkeypatch.setattr(app, "API_KEY", "sk-test")
    stream_post.response = FakeStreamResponse(
        [
            *sse({"choices": [{"delta": {"content": "你"}}]}),
            b": keep-alive",
            *sse({"choices": [{"delta": {"content": "好"}}]}),
            b"data: [DONE]",
        ]
    )

    assert list(app.translate_stream("hello")) == ["你", "好"]


def test_openai_stream_stops_at_done_marker(app, stream_post, monkeypatch):
    """收到 [DONE] 后不再读取后续内容"""
    monkeypatch.setattr(app, "API_KEY", "sk-test")
    stream_post.response = FakeStreamResponse(
        [
            *sse({"choices": [{"delta": {"content": "好"}}]}),
            b"data: [DONE]",
            *sse({"choices": [{"delta": {"content": "不应出现"}}]}),
        ]
    )

    assert list(app.translate_stream("hello")) == ["好"]


def test_stream_prompt_uses_configured_template(app, stream_post, monkeypatch):
    """流式请求的 prompt 与一次性请求走同一套构造逻辑"""
    monkeypatch.setattr(app, "API_KEY", "")
    stream_post.response = FakeStreamResponse()

    list(app.translate_stream("hello"))

    assert stream_post.calls[0].payload["prompt"] == "把 hello 翻译成 Chinese"


# ===== 连接关闭 =====


def test_response_is_closed_after_read(app, stream_post, monkeypatch):
    monkeypatch.setattr(app, "API_KEY", "")
    response = FakeStreamResponse(ndjson({"response": "好", "done": True}))
    stream_post.response = response

    list(app.translate_stream("hello"))

    assert response.closed is True


def test_response_is_closed_when_consumer_stops_early(app, stream_post, monkeypatch):
    """调用方提前结束迭代（模拟用户关闭弹窗）时连接也要断开"""
    monkeypatch.setattr(app, "API_KEY", "")
    response = FakeStreamResponse(ndjson({"response": "一"}, {"response": "二"}))
    stream_post.response = response

    chunks = app.translate_stream("hello")
    next(chunks)
    chunks.close()

    assert response.closed is True


def test_response_is_closed_on_http_error(app, stream_post, monkeypatch):
    monkeypatch.setattr(app, "API_KEY", "")
    response = FakeStreamResponse([], error=RuntimeError("500 Server Error"))
    stream_post.response = response

    with pytest.raises(RuntimeError):
        list(app.translate_stream("hello"))

    assert response.closed is True


# ===== 错误传播：与一次性请求不同，流式向上抛由调用方处理 =====


def test_network_error_propagates(app, monkeypatch):
    monkeypatch.setattr(app, "API_KEY", "")

    def boom(*_args, **_kwargs):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(app, "requests", SimpleNamespace(post=boom))

    with pytest.raises(ConnectionError):
        list(app.translate_stream("hello"))


def test_partial_result_survives_mid_stream_error(app, stream_post, monkeypatch):
    """中途断开时，已收到的分块仍然保留在调用方手里"""
    monkeypatch.setattr(app, "API_KEY", "")

    class BrokenResponse(FakeStreamResponse):
        def iter_lines(self):
            yield json.dumps({"response": "你"}).encode("utf-8")
            raise ConnectionError("connection reset")

    stream_post.response = BrokenResponse()

    received = []
    with pytest.raises(ConnectionError):
        for chunk in app.translate_stream("hello"):
            received.append(chunk)

    assert received == ["你"]
