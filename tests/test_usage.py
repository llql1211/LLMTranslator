"""token 统计的提取、流式记录与请求开关"""

from __future__ import annotations

import api
from logger import Usage


class FakeStreamResponse:
    """最小的流式响应替身"""

    def __init__(self, lines):
        self._lines = list(lines)
        self.headers = {}
        self.status_code = 200

    def raise_for_status(self):
        pass

    def iter_lines(self):
        yield from self._lines

    def close(self):
        pass


def make_settings(api_key: str = "") -> api.ApiSettings:
    return api.ApiSettings(
        base_url="http://localhost:11434/api/generate",
        api_key=api_key,
        model_name="m",
        prompt_template="{input_text}",
        target_lang="Chinese",
        generation_params={},
        extra_params={},
    )


# ===== 一次性响应的统计提取 =====


def test_extract_usage_openai():
    result = {"usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}}

    usage = api.extract_usage(result, api_key=True)

    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (12, 5, 17)


def test_extract_usage_ollama():
    result = {"prompt_eval_count": 8, "eval_count": 3}

    usage = api.extract_usage(result, api_key=False)

    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (8, 3, 0)


def test_extract_usage_of_bad_payload_is_empty():
    assert api.extract_usage(None, False).is_empty
    assert api.extract_usage([], True).is_empty
    assert api.extract_usage({"usage": "bad"}, True).is_empty


# ===== 流式响应的统计提取 =====


def test_stream_usage_openai_final_chunk():
    line = 'data: {"usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}'

    usage = api.stream_usage(line, api_key=True)

    assert usage is not None
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (1, 2, 3)


def test_stream_usage_ollama_done_chunk():
    usage = api.stream_usage('{"done": true, "prompt_eval_count": 9, "eval_count": 4}', False)

    assert usage is not None
    assert (usage.prompt_tokens, usage.completion_tokens) == (9, 4)


def test_stream_usage_ignores_content_chunks():
    assert api.stream_usage('{"response": "hi"}', False) is None
    assert api.stream_usage('data: {"choices": [{"delta": {"content": "hi"}}]}', True) is None
    assert api.stream_usage("data: [DONE]", True) is None


def test_stream_keeps_last_reported_usage():
    lines = [
        b'data: {"choices":[{"delta":{"content":"hi"}}]}',
        b'data: {"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}',
        b"data: [DONE]",
    ]

    chunks = list(api.translate_stream("x", make_settings("sk-test"), post=lambda *_args, **_kwargs: FakeStreamResponse(lines)))

    assert chunks == ["hi"]
    usage = api.last_usage()
    assert isinstance(usage, Usage)
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (2, 1, 3)


def test_stream_usage_unavailable_is_empty():
    lines = [b'{"response": "hi", "done": false}']

    list(api.translate_stream("x", make_settings(), post=lambda *_args, **_kwargs: FakeStreamResponse(lines)))

    assert api.last_usage().is_empty


# ===== 请求开关与配置 =====


def test_openai_stream_requests_usage(app, monkeypatch):
    monkeypatch.setattr(app, "API_KEY", "sk-test")

    payload = app.build_request("hello", stream=True)[1]

    assert payload["stream_options"] == {"include_usage": True}


def test_ollama_stream_does_not_request_usage(app, monkeypatch):
    monkeypatch.setattr(app, "API_KEY", "")

    assert "stream_options" not in app.build_request("hello", stream=True)[1]


def test_non_stream_does_not_request_usage(app, monkeypatch):
    monkeypatch.setattr(app, "API_KEY", "sk-test")

    assert "stream_options" not in app.build_request("hello", stream=False)[1]


def test_usage_request_can_be_disabled(make_app, build_config, monkeypatch):
    app = make_app(build_config(stream_include_usage=False))
    monkeypatch.setattr(app, "API_KEY", "sk-test")

    assert "stream_options" not in app.build_request("hello", stream=True)[1]
