"""选中文本的清洗：合并被折行的句子，保留段落空行。"""

from __future__ import annotations

import re

PUNCTUATION = {'.', '?', '!'}


def clean_english_text(text: str) -> str:
    """
    清洗 ASCII 文本

    将连续空格替换为单个空格，根据上下文补句号，同时保留原换行与段落空行
    """
    lines = [line.strip() for line in text.splitlines()]
    cleaned = ""
    blank_lines = 0

    for current in lines:
        if not current:
            # 只在已有正文时记录空行，段首的空白直接丢弃
            if cleaned:
                blank_lines += 1
            continue

        if not cleaned:
            cleaned = current
        elif blank_lines:
            # 空行是段落分隔，不参与「上一行末尾是否有标点」的判断
            cleaned += "\n" * (blank_lines + 1) + current
            blank_lines = 0
        elif current[0].islower() and cleaned[-1] not in PUNCTUATION:
            # 小写开头：视为上一句被折行
            cleaned += " " + current
        elif current[0].isupper() and cleaned[-1] not in PUNCTUATION:
            # 大写开头：视作新句子，补句号
            cleaned += ".\n" + current
        else:
            cleaned += "\n" + current

    return re.sub(r'[ \t]+', ' ', cleaned).strip()
