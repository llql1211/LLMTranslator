"""重定向处理：http -> https 时保持 POST，避免落到 405"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


class FakeResponse:
    def __init__(self, status_code=200, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def close(self):
        self.closed = True


class FakeStreamResponse(FakeResponse):
    def __init__(self, lines=(), **kwargs):
        super().__init__(**kwargs)
        self._lines = list(lines)

    def raise_for_status(self):
        pass

    def iter_lines(self):
        yield from self._lines


@pytest.fixture
def post(app, monkeypatch):
    """记录每次 POST 的 URL 与参数；按 URL 返回预设响应"""
    state = SimpleNamespace(calls=[], responses={})

    def fake_post(url, **kwargs):
        state.calls.append(SimpleNamespace(url=url, **kwargs))
        return state.responses.get(url, FakeResponse())

    monkeypatch.setattr(app, "requests", SimpleNamespace(post=fake_post))
    return state


def test_301_preserves_post_and_body(post, app):
    """301 到 https 后应以 POST 重试，且请求体不变"""
    http_url = "http://llmapi.paratera.com/v1/chat/completions"
    https_url = "https://llmapi.paratera.com/v1/chat/completions"
    redirect = FakeResponse(301, {"Location": https_url})
    final = FakeResponse(200)
    post.responses[http_url] = redirect
    post.responses[https_url] = final

    result = app.http_post(http_url, json={"model": "m"}, headers={"k": "v"}, timeout=30)

    assert result is final
    assert [call.url for call in post.calls] == [http_url, https_url]
    assert all(call.allow_redirects is False for call in post.calls)
    assert all(call.json == {"model": "m"} for call in post.calls)
    assert all(call.headers == {"k": "v"} for call in post.calls)
    assert redirect.closed is True


def test_relative_location_is_resolved(post, app):
    """相对路径的 Location 应基于当前 URL 解析"""
    base = "https://example.com/api"
    target = "https://example.com/v1/chat/completions"
    post.responses[base] = FakeResponse(302, {"Location": "/v1/chat/completions"})

    app.http_post(base, json={})

    assert post.calls[1].url == target


def test_response_without_redirect_is_returned_directly(post, app):
    """非重定向响应直接返回，不重复请求"""
    response = FakeResponse(200)
    post.responses["https://example.com"] = response

    assert app.http_post("https://example.com", json={}) is response
    assert len(post.calls) == 1


def test_too_many_redirects_raises(post, app):
    """超过上限时报错，而不是无限循环"""
    for i in range(app.MAX_REDIRECTS + 1):
        url = f"https://example.com/{i}"
        post.responses[url] = FakeResponse(301, {"Location": f"https://example.com/{i + 1}"})

    with pytest.raises(RuntimeError, match="重定向次数超过"):
        app.http_post("https://example.com/0", json={})


def test_translate_stream_survives_http_redirect(post, app, monkeypatch):
    """端到端：配置 http 地址被重定向到 https 时，流式翻译仍能拿到结果"""
    monkeypatch.setattr(app, "API_KEY", "sk-test")
    monkeypatch.setattr(app, "API_BASE_URL", "http://llmapi.paratera.com")
    http_url = "http://llmapi.paratera.com/v1/chat/completions"
    https_url = "https://llmapi.paratera.com/v1/chat/completions"
    post.responses[http_url] = FakeResponse(301, {"Location": https_url})
    chunk = {"choices": [{"delta": {"content": "你好"}}]}
    post.responses[https_url] = FakeStreamResponse(
        [f"data: {json.dumps(chunk)}".encode("utf-8"), b"data: [DONE]"],
        headers={},
    )

    assert list(app.translate_stream("hello")) == ["你好"]
    assert [call.url for call in post.calls] == [http_url, https_url]
