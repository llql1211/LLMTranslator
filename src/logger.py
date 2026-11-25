"""统一终端日志与翻译统计。

所有面向用户的调试输出都走这里，格式固定为：

    [HH:MM:SS] [INFO ] 消息

同时提供 Timer（计时）与 Usage（token 用量）两个小工具，
让各轮翻译的耗时和 token 消耗能以同一行统计信息输出。
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TextIO

LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}

# 默认输出 INFO 及以上，DEBUG 由 configure(level="DEBUG") 打开
_min_level = LEVELS["INFO"]
_output: TextIO | None = None
_lock = threading.Lock()


def configure(level: str = "INFO", stream: TextIO | None = None) -> None:
    """
    调整日志级别与输出流

    - level: DEBUG / INFO / WARN / ERROR（大小写不敏感）
    - stream: 默认 sys.stdout；测试时传入 StringIO 即可捕获输出
    """
    global _min_level, _output
    normalized = level.upper()
    if normalized not in LEVELS:
        raise ValueError(f"未知日志级别：{level}")
    _min_level = LEVELS[normalized]
    _output = stream


def _write(level: str, message: str) -> None:
    if LEVELS[level] < _min_level:
        return
    stream = _output or sys.stdout
    stamp = datetime.now().strftime("%H:%M:%S")
    with _lock:
        print(f"[{stamp}] [{level:<5}] {message}", file=stream)


def debug(message: str) -> None:
    _write("DEBUG", message)


def info(message: str) -> None:
    _write("INFO", message)


def warn(message: str) -> None:
    _write("WARN", message)


def error(message: str) -> None:
    _write("ERROR", message)


def shorten(text: str, limit: int = 80) -> str:
    """
    把多行文本压缩成适合单行日志的预览

    换行替换为「↵」，超长部分用省略号截断，避免整段选中文本刷屏
    """
    flat = " ".join(line.strip() for line in text.splitlines() if line.strip())
    flat = flat.replace("\t", " ")
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1] + "…"


@dataclass
class Timer:
    """轻量计时器，创建即开始"""

    started_at: float = field(default_factory=time.perf_counter)

    @property
    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started_at) * 1000

    @property
    def elapsed_text(self) -> str:
        return f"{self.elapsed_ms / 1000:.2f}s"


@dataclass
class Usage:
    """一次翻译的 token 用量；total 为空时由输入+输出推算"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @property
    def total(self) -> int:
        return self.total_tokens or self.prompt_tokens + self.completion_tokens

    @property
    def is_empty(self) -> bool:
        return self.prompt_tokens == 0 and self.completion_tokens == 0 and self.total == 0

    def update_from(self, other: Usage) -> None:
        """用另一份统计覆盖当前值（流式结束时拿到的是最终统计）"""
        self.prompt_tokens = other.prompt_tokens
        self.completion_tokens = other.completion_tokens
        self.total_tokens = other.total_tokens

    def describe(self) -> str:
        if self.is_empty:
            return "token 统计不可用"
        parts = [f"输入 {self.prompt_tokens}", f"输出 {self.completion_tokens}"]
        if self.total:
            parts.append(f"合计 {self.total}")
        return " / ".join(parts) + " tokens"


def report(timer: Timer, usage: Usage | None = None) -> None:
    """统一输出一轮翻译的耗时与 token 统计"""
    if usage is None or usage.is_empty:
        info(f"翻译完成 · 耗时 {timer.elapsed_text} · token 统计不可用")
    else:
        info(f"翻译完成 · 耗时 {timer.elapsed_text} · {usage.describe()}")
