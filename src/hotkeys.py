"""热键字符串的解析与按键匹配（不持有按键状态）。"""

from __future__ import annotations

MODIFIERS = {"ctrl", "shift", "alt", "cmd"}


def parse_hotkey(spec: str) -> tuple[set[str], str]:
    """
    解析 '<ctrl>+<shift>+e' 格式的热键，返回 (修饰键集合, 主键)

    容忍配置中书写时多余的空白，如 '<ctrl> + <shift> + e'
    """
    parts = spec.lower().split("+")
    mods: set[str] = set()
    key_char = ""
    for part in parts:
        part = part.strip().strip("<>")
        if part in MODIFIERS:
            mods.add(part)
        else:
            key_char = part
    return mods, key_char


def matches_key(key: object, expected_char: str) -> bool:
    """
    判断按键是否匹配期望字符（通过 VK 精确匹配，不受 Ctrl/Shift 修饰键影响）

    Windows 下字母 VK 等于其大写 ASCII 码
    """
    vk = getattr(key, 'vk', None)
    if vk is None:
        return False
    return vk == ord(expected_char.upper())
