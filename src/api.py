"""LLM 请求构造、重定向处理与翻译调用（依赖通过参数传入，便于测试）。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests

from config import GEN_PARAM_MAP

MAX_REDIRECTS = 5
REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})

PostFunc = Callable[..., requests.Response]


@dataclass(frozen=True)
class ApiSettings:
    """构造翻译请求所需的配置快照"""

    base_url: str
    api_key: str
    model_name: str
    prompt_template: str
    target_lang: str
    generation_params: dict[str, Any]
    # 模型配置里的 extra_body，仅对 OpenAI 兼容格式生效
    extra_params: dict[str, Any]


def chat_completions_url(base_url: str) -> str:
    """把服务根地址补全为 /v1/chat/completions，已是完整地址则原样返回"""
    url = base_url.rstrip("/")
    if url.endswith("/v1/chat/completions"):
        return url
    if url.endswith("/v1"):
        return url + "/chat/completions"
    return url + "/v1/chat/completions"


def build_request(text: str, stream: bool, settings: ApiSettings) -> tuple[str, dict, dict]:
    """
    构造翻译请求，返回 (url, payload, headers)

    - api_key 为空 → Ollama 原生格式（/api/generate）
    - api_key 非空 → OpenAI 兼容格式（/v1/chat/completions）

    生成参数按格式转换后一并写入 payload
    """
    prompt = settings.prompt_template.format(
        target_lang=settings.target_lang, input_text=text
    )

    if settings.api_key:
        # OpenAI 兼容格式
        url = chat_completions_url(settings.base_url)
        headers = {
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            # 模型自定义的额外请求字段（如 thinking 开关），核心字段优先于它
            **settings.extra_params,
            "model": settings.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
            # OpenAI 兼容格式的生成参数平铺在顶层，字段名与配置项一致
            **settings.generation_params,
        }
    else:
        # Ollama 原生格式
        url = settings.base_url
        headers = {}
        payload = {
            "model": settings.model_name,
            "prompt": prompt,
            "stream": stream
        }
        if settings.generation_params:
            # Ollama 原生格式的生成参数统一放在 options 中，且部分字段名与 OpenAI 不同
            payload["options"] = {
                GEN_PARAM_MAP[k]: v for k, v in settings.generation_params.items()
            }

    return url, payload, headers


def http_post(url: str, post: PostFunc = requests.post, **kwargs) -> requests.Response:
    """
    发送 POST 请求，并在跟随 3xx 重定向时保持原有的方法与请求体

    requests 默认在 301/302 后会改成 GET。若服务把 http 地址重定向到 https，
    且只接受 POST（如 /v1/chat/completions），改写成 GET 就会得到 405。
    这里手动跟随重定向并用同样的参数重新 POST。
    """
    for _ in range(MAX_REDIRECTS):
        response = post(url, allow_redirects=False, **kwargs)
        location = response.headers.get("Location")
        if response.status_code not in REDIRECT_STATUS or not location:
            return response
        response.close()
        url = urljoin(url, location)
    raise RuntimeError(f"重定向次数超过 {MAX_REDIRECTS} 次：{url}")


def parse_ollama_stream_line(line: str) -> str | None:
    """
    解析 Ollama 流式响应的一行（NDJSON），返回增量文本

    空行、坏 JSON、无内容的分块一律返回 None，不让单行异常打断整段翻译
    """
    line = line.strip()
    if not line:
        return None

    try:
        chunk = json.loads(line)
    except json.JSONDecodeError:
        return None

    if not isinstance(chunk, dict):
        return None

    text = chunk.get("response")
    return text if isinstance(text, str) and text else None


def parse_openai_stream_line(line: str) -> str | None:
    """
    解析 OpenAI 流式响应的一行（SSE），返回增量文本

    非 data: 开头的行、结束标记 [DONE]、坏 JSON、无内容的分块一律返回 None
    """
    line = line.strip()
    if not line.startswith("data:"):
        return None

    data = line[len("data:"):].strip()
    if not data or data == "[DONE]":
        return None

    try:
        chunk = json.loads(data)
    except json.JSONDecodeError:
        return None

    if not isinstance(chunk, dict):
        return None

    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return None

    delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
    text = delta.get("content") if isinstance(delta, dict) else None
    return text if isinstance(text, str) and text else None


def translate_once(text: str, settings: ApiSettings, post: PostFunc = requests.post) -> str:
    """调用 LLM API 翻译，等全部生成完再返回；报错返回空串"""
    url, payload, headers = build_request(text, stream=False, settings=settings)

    result_text = ""
    try:
        print("-> 翻译中... ", end="")
        response = http_post(url, post=post, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        if settings.api_key:
            # OpenAI 格式：response.choices[0].message.content
            result_text = result["choices"][0]["message"]["content"].strip()
        else:
            # Ollama 格式：response
            result_text = result.get("response", "").strip()
    except Exception as e:
        print(f"-> 翻译失败：{e} ")

    return result_text


def translate_stream(
    text: str, settings: ApiSettings, post: PostFunc = requests.post
) -> Iterator[str]:
    """
    流式调用 LLM API 翻译，逐块产出增量文本

    网络或服务端出错时抛异常，调用方已收到的部分由调用方自己保留

    调用方提前结束迭代（如 break）时，生成器被关闭并断开连接
    """
    url, payload, headers = build_request(text, stream=True, settings=settings)
    parse_line = parse_openai_stream_line if settings.api_key else parse_ollama_stream_line

    response = http_post(url, post=post, json=payload, headers=headers, timeout=30, stream=True)
    try:
        response.raise_for_status()
        for raw_line in response.iter_lines():
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line.removeprefix("data:").strip() == "[DONE]":
                # OpenAI 兼容格式的结束标记，收到即停止
                break
            chunk = parse_line(line)
            if chunk:
                yield chunk
    finally:
        response.close()
