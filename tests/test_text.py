"""选中文本的清洗逻辑"""

from __future__ import annotations

from pathlib import Path

import pytest

SAMPLE_PARAGRAPH = Path(__file__).resolve().parent / "data" / "test_paragraph.txt"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 小写续行直接合并
        ("hello\nworld", "hello world"),
        # 上一行无标点、下一行以大写开头 → 补句号
        ("Hello\nWorld", "Hello.\nWorld"),
        # 上一行已有标点 → 不重复补
        ("Hello.\nWorld", "Hello.\nWorld"),
        # 大写行后接小写行 → 视为同一句被折行
        ("Hello\nworld", "Hello world"),
        # 连续空白折叠为单个空格
        ("hello    world\t\tfoo", "hello world foo"),
        # 行首行尾空格被去除
        ("  spaced  \n  lines  ", "spaced lines"),
        # 多行混合
        ("Line one\nline two\nLine three", "Line one line two.\nLine three"),
        ("Ends with period.\nnew line", "Ends with period.\nnew line"),
        # 空行是段落分隔，不能当成上一行来补句号
        ("Hello\n\nWorld", "Hello\n\nWorld"),
        ("Hello.\n\nWorld", "Hello.\n\nWorld"),
        ("Hello\n\n\nWorld", "Hello\n\n\nWorld"),
    ],
)
def test_clean_english_text(app, raw, expected):
    assert app.clean_english_text(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "\n", "\n\n", "\t\t"])
def test_blank_input_returns_empty(app, raw):
    assert app.clean_english_text(raw) == ""


def test_question_and_exclamation_count_as_punctuation(app):
    """? 和 ! 与 . 一样，其后不应再被补句号"""
    assert app.clean_english_text("Really?\nYes") == "Really?\nYes"
    assert app.clean_english_text("Stop!\nNow") == "Stop!\nNow"


def test_sample_paragraph_is_cleaned(app):
    """
    对仓库内附带的样例段落做一次整体清洗

    该段落模拟从 PDF 复制的结果：行内断句、多余空格、行尾无标点
    """
    raw = SAMPLE_PARAGRAPH.read_text(encoding="utf-8")
    cleaned = app.clean_english_text(raw)

    assert cleaned == cleaned.strip(), "结果首尾不应有空白"
    assert "  " not in cleaned, "不应残留连续空格"
    assert "\t" not in cleaned, "不应残留制表符"
    assert cleaned.startswith("Test Paragraph:"), "首行内容应保留"
    assert "A spin 1/2 particle" in cleaned, "正文内容应保留"
