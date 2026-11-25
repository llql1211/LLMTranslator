"""统一日志格式、计时与 token 统计"""

from __future__ import annotations

import io
import re
import time

import pytest

import logger


@pytest.fixture
def output():
    """捕获日志输出，结束后恢复默认级别与输出流"""
    stream = io.StringIO()
    logger.configure("DEBUG", stream)
    yield stream
    logger.configure("INFO", None)


def test_message_uses_unified_format(output):
    logger.info("你好")

    assert re.fullmatch(r"\[\d{2}:\d{2}:\d{2}\] \[INFO \] 你好", output.getvalue().strip())


def test_all_levels_are_padded_consistently(output):
    logger.debug("d")
    logger.info("i")
    logger.warn("w")
    logger.error("e")

    levels = [line.split("] [")[1].split("]")[0] for line in output.getvalue().splitlines()]
    assert levels == ["DEBUG", "INFO ", "WARN ", "ERROR"]


def test_debug_is_hidden_by_default():
    stream = io.StringIO()
    logger.configure("INFO", stream)
    try:
        logger.debug("不可见")
        logger.info("可见")
    finally:
        logger.configure("INFO", None)

    assert "不可见" not in stream.getvalue()
    assert "可见" in stream.getvalue()


def test_shorten_collapses_whitespace_and_truncates():
    assert logger.shorten("  a  \n b ") == "a b"
    assert logger.shorten("x" * 100, 10) == "x" * 9 + "…"


def test_timer_measures_elapsed_time():
    timer = logger.Timer(started_at=time.perf_counter() - 1.25)

    assert timer.elapsed_ms >= 1200
    assert timer.elapsed_text.startswith("1.2")


def test_usage_total_falls_back_to_prompt_plus_completion():
    usage = logger.Usage(prompt_tokens=3, completion_tokens=4)

    assert usage.total == 7
    assert not usage.is_empty


def test_usage_describe_covers_both_formats():
    assert logger.Usage().describe() == "token 统计不可用"
    assert logger.Usage(3, 4, 9).describe() == "输入 3 / 输出 4 / 合计 9 tokens"


def test_usage_update_from_overwrites_values():
    usage = logger.Usage()
    usage.update_from(logger.Usage(1, 2, 3))

    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (1, 2, 3)


def test_report_logs_elapsed_and_tokens(output):
    timer = logger.Timer(started_at=time.perf_counter() - 1)

    logger.report(timer, logger.Usage(10, 5))

    line = output.getvalue().strip()
    assert "翻译完成" in line
    assert "耗时 1.00s" in line
    assert "输入 10 / 输出 5 / 合计 15 tokens" in line


def test_report_without_usage_says_unavailable(output):
    logger.report(logger.Timer(), None)

    assert "token 统计不可用" in output.getvalue()
