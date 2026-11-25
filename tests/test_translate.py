"""请求构造与错误处理"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"


class FakeResponse:
    """可配置返回体与 HTTP 错误的假响应"""

    def __init__(self, body=None, error: Exception | None = None, status_code=200, headers=None):
        self._body = body
        self._error = error
        self.status_code = status_code
        self.headers = headers or {}

    def close(self):
        pass

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        return self._body


@pytest.fixture
def post(app, monkeypatch):
    """
    替换 requests.post，返回记录调用信息的容器

    通过 post.response 指定本次要返回的响应
    """
    state = SimpleNamespace(calls=[], response=FakeResponse({}))

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        state.calls.append(
            SimpleNamespace(url=url, payload=json, headers=headers, timeout=timeout)
        )
        return state.response

    monkeypatch.setattr(app, "requests", SimpleNamespace(post=fake_post))
    return state


# ===== Ollama 原生格式 =====


def test_ollama_payload(app, post, monkeypatch):
    """api_key 为空时走 Ollama 原生格式"""
    monkeypatch.setattr(app, "API_KEY", "")
    post.response = FakeResponse({"response": "你好"})

    app.translate_with_llm("hello")

    call = post.calls[0]
    assert call.url == OLLAMA_GENERATE_URL
    assert call.payload["model"] == app.MODEL_NAME
    assert call.payload["prompt"] == "把 hello 翻译成 Chinese"
    assert call.payload["stream"] is False
    assert call.timeout == 30


def test_ollama_options_from_config(make_app, build_config, monkeypatch):
    """Ollama 原生格式下生成参数进入 options，且字段名按 Ollama 约定转换"""
    app = make_app(
        build_config(
            temperature=0.7,
            top_p=0.6,
            top_k=20,
            repetition_penalty=1.05,
            max_tokens=4096,
        )
    )
    state = SimpleNamespace(calls=[], response=FakeResponse({"response": "好"}))

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        state.calls.append(SimpleNamespace(url=url, payload=json))
        return state.response

    monkeypatch.setattr(app, "requests", SimpleNamespace(post=fake_post))
    app.translate_with_llm("hi")

    assert state.calls[0].payload["options"] == {
        "temperature": 0.7,
        "top_p": 0.6,
        "top_k": 20,
        "repeat_penalty": 1.05,
        "num_predict": 4096,
    }


def test_unset_generation_params_are_not_sent(app, post):
    """未在配置中写出的生成参数不应出现在请求里（测试用配置未含生成参数）"""
    post.response = FakeResponse({"response": "你好"})

    app.translate_with_llm("hello")

    assert "options" not in post.calls[0].payload


def test_partial_generation_params(make_app, build_config, monkeypatch):
    """只写出部分生成参数时，只发送写出的那些"""
    app = make_app(build_config(temperature=0.3, max_tokens=512))
    state = SimpleNamespace(calls=[], response=FakeResponse({"response": "好"}))

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        state.calls.append(SimpleNamespace(url=url, payload=json))
        return state.response

    monkeypatch.setattr(app, "requests", SimpleNamespace(post=fake_post))
    app.translate_with_llm("hi")

    assert state.calls[0].payload["options"] == {"temperature": 0.3, "num_predict": 512}


def test_ollama_result_is_stripped(app, post):
    """返回文本两端的空白应被去掉"""
    post.response = FakeResponse({"response": "  你好  "})

    assert app.translate_with_llm("hello") == "你好"


# ===== OpenAI 兼容格式 =====


def test_openai_payload(app, post, monkeypatch):
    """api_key 非空时走 OpenAI 兼容格式，生成参数平铺在顶层"""
    monkeypatch.setattr(app, "API_KEY", "sk-test")
    post.response = FakeResponse({"choices": [{"message": {"content": "你好"}}]})

    app.translate_with_llm("hello")

    call = post.calls[0]
    assert call.url.endswith("/v1/chat/completions")
    assert call.headers["Authorization"] == "Bearer sk-test"
    assert call.payload["messages"] == [
        {"role": "user", "content": "把 hello 翻译成 Chinese"}
    ]
    assert call.payload["stream"] is False
    assert "options" not in call.payload


def test_openai_generation_params_are_flattened(make_app, build_config, monkeypatch):
    """OpenAI 兼容格式下生成参数平铺在顶层，字段名与配置项一致"""
    app = make_app(build_config(max_tokens=4096, repetition_penalty=1.05))
    monkeypatch.setattr(app, "API_KEY", "sk-test")
    state = SimpleNamespace(
        calls=[],
        response=FakeResponse({"choices": [{"message": {"content": "好"}}]}),
    )

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        state.calls.append(SimpleNamespace(url=url, payload=json))
        return state.response

    monkeypatch.setattr(app, "requests", SimpleNamespace(post=fake_post))
    app.translate_with_llm("hi")

    payload = state.calls[0].payload
    assert payload["max_tokens"] == 4096
    assert payload["repetition_penalty"] == 1.05
    assert "options" not in payload


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("http://localhost:11434", "http://localhost:11434/v1/chat/completions"),
        ("http://localhost:11434/", "http://localhost:11434/v1/chat/completions"),
        ("http://localhost:11434/v1", "http://localhost:11434/v1/chat/completions"),
        ("http://localhost:11434/v1/", "http://localhost:11434/v1/chat/completions"),
        (
            "http://localhost:11434/v1/chat/completions",
            "http://localhost:11434/v1/chat/completions",
        ),
        # 域名恰好以 1 / v 结尾时不能被误当成 /v1 后缀裁掉
        ("http://host1", "http://host1/v1/chat/completions"),
        ("http://myv1", "http://myv1/v1/chat/completions"),
        ("https://api.v1.com", "https://api.v1.com/v1/chat/completions"),
    ],
)
def test_openai_url_normalisation(app, post, monkeypatch, base_url, expected):
    """base_url 的各种写法都应补全成 /v1/chat/completions"""
    monkeypatch.setattr(app, "API_KEY", "sk-test")
    monkeypatch.setattr(app, "API_BASE_URL", base_url)
    post.response = FakeResponse({"choices": [{"message": {"content": "好"}}]})

    app.translate_with_llm("hello")

    assert post.calls[0].url == expected


def test_openai_result_is_stripped(app, post, monkeypatch):
    monkeypatch.setattr(app, "API_KEY", "sk-test")
    post.response = FakeResponse({"choices": [{"message": {"content": " 你好 "}}]})

    assert app.translate_with_llm("hello") == "你好"


# ===== 错误处理：一律返回空串，不向上抛 =====


def test_network_error_returns_empty(app, monkeypatch):
    """请求抛异常时返回空串"""
    monkeypatch.setattr(app, "API_KEY", "")

    def boom(*_args, **_kwargs):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(app, "requests", SimpleNamespace(post=boom))

    assert app.translate_with_llm("hello") == ""


def test_http_error_returns_empty(app, post):
    """HTTP 状态码错误时返回空串"""
    post.response = FakeResponse({}, error=RuntimeError("500 Server Error"))

    assert app.translate_with_llm("hello") == ""


def test_malformed_ollama_body_returns_empty(app, post):
    """返回体缺少 response 字段时返回空串"""
    post.response = FakeResponse({"unexpected": "结构"})

    assert app.translate_with_llm("hello") == ""


def test_malformed_openai_body_returns_empty(app, post, monkeypatch):
    """返回体结构不符时返回空串"""
    monkeypatch.setattr(app, "API_KEY", "sk-test")
    post.response = FakeResponse({"unexpected": "结构"})

    assert app.translate_with_llm("hello") == ""


def test_prompt_uses_configured_template(make_app, build_config, monkeypatch):
    """prompt 由配置中的模板、目标语言与选中文本拼成"""
    app = make_app(
        build_config(
            prompt_template="[{target_lang}] <<{input_text}>>",
            target_lang="Japanese",
        )
    )
    state = SimpleNamespace(calls=[], response=FakeResponse({"response": "好"}))

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        state.calls.append(SimpleNamespace(url=url, payload=json))
        return state.response

    monkeypatch.setattr(app, "requests", SimpleNamespace(post=fake_post))
    app.translate_with_llm("hello")

    assert state.calls[0].payload["prompt"] == "[Japanese] <<hello>>"
