"""热键解析与按键状态机"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pynput.keyboard import Key, KeyCode

# 通过 app 夹具动态取 main 的函数：make_app 会 reload main，
# 模块导入时抓到的旧引用在 reload 后可能已不是当前实现


class FakeThread:
    """替换 threading.Thread，记录被启动的目标而不真正起线程"""

    started: list = []

    def __init__(self, target=None, daemon=None, **_kwargs):
        self.target = target

    def start(self):
        FakeThread.started.append(self.target)


def patch_threads(module, monkeypatch) -> list:
    """
    把模块内的 threading.Thread 换成 FakeThread

    注意：importlib.reload 会重新执行模块体、重新绑定 threading，
    因此必须在使用 make_app 重载之后再调用本函数。
    """
    FakeThread.started = []
    monkeypatch.setattr(module, "threading", SimpleNamespace(Thread=FakeThread))
    return FakeThread.started


@pytest.fixture
def spawn(app, monkeypatch):
    """拦截 on_press 启动的线程，返回被启动目标的列表"""
    return patch_threads(app, monkeypatch)


# ===== parse_hotkey =====


@pytest.mark.parametrize(
    ("spec", "expected_mods", "expected_key"),
    [
        ("<ctrl>+<shift>+e", {"ctrl", "shift"}, "e"),
        ("<ctrl>+e", {"ctrl"}, "e"),
        ("e", set(), "e"),
        ("<alt>+<cmd>+k", {"alt", "cmd"}, "k"),
        ("<CTRL>+E", {"ctrl"}, "e"),  # 大小写不敏感
        ("<ctrl> + <shift> + e", {"ctrl", "shift"}, "e"),  # 容忍空格
        ("<shift>+<alt>+<ctrl>+q", {"shift", "alt", "ctrl"}, "q"),
    ],
)
def test_parse_hotkey(app, spec, expected_mods, expected_key):
    mods, key = app.parse_hotkey(spec)

    assert mods == expected_mods
    assert key == expected_key


# ===== _matches_key =====


def test_matches_key_by_vk(app):
    """按 VK 匹配，与字符大小写无关"""
    assert app._matches_key(KeyCode.from_vk(ord("E")), "e")
    assert app._matches_key(KeyCode.from_vk(ord("E")), "E")
    assert app._matches_key(KeyCode.from_vk(ord("Q")), "q")


def test_matches_key_rejects_other_characters(app):
    assert not app._matches_key(KeyCode.from_vk(ord("W")), "e")


def test_matches_key_rejects_special_keys(app):
    """空格、功能键等不应被当成字母匹配"""
    assert not app._matches_key(Key.space, "e")
    assert not app._matches_key(Key.f12, "e")
    assert not app._matches_key(None, "e")


# ===== on_press / on_release 状态机 =====


def test_translate_hotkey_triggers_on_activate(app, spawn, reset_mods):
    """Ctrl+Shift+E 应触发翻译"""
    app.on_press(Key.ctrl)
    app.on_press(Key.shift)
    app.on_press(KeyCode.from_vk(ord("E")))

    assert spawn == [app.on_activate]


def test_quit_hotkey_triggers_on_quit(app, spawn, reset_mods):
    """Ctrl+Shift+Q 应触发退出"""
    app.on_press(Key.ctrl)
    app.on_press(Key.shift)
    app.on_press(KeyCode.from_vk(ord("Q")))

    assert spawn == [app.on_quit]


def test_hotkey_requires_all_modifiers(app, spawn, reset_mods):
    """只按 Ctrl（缺 Shift）不应触发"""
    app.on_press(Key.ctrl)
    app.on_press(KeyCode.from_vk(ord("E")))

    assert spawn == []


def test_hotkey_rejects_extra_modifier(app, spawn, reset_mods):
    """多按一个 Alt 不应触发，避免 Ctrl+Shift+Alt+E 之类的误触"""
    app.on_press(Key.ctrl)
    app.on_press(Key.shift)
    app.on_press(Key.alt)
    app.on_press(KeyCode.from_vk(ord("E")))

    assert spawn == []


def test_hotkey_not_triggered_without_modifiers(app, spawn, reset_mods):
    """裸按 E 不应触发"""
    app.on_press(KeyCode.from_vk(ord("E")))

    assert spawn == []


def test_release_clears_modifier_state(app, spawn, reset_mods):
    """松开修饰键后热键不再命中"""
    app.on_press(Key.ctrl)
    app.on_press(Key.shift)
    app.on_release(Key.shift)
    app.on_press(KeyCode.from_vk(ord("E")))

    assert spawn == []


def test_left_right_modifier_variants_are_tracked(app, spawn, reset_mods):
    """左右两侧的 Ctrl/Shift 应视为同一个修饰键"""
    app.on_press(Key.ctrl_l)
    app.on_press(Key.shift_r)
    app.on_press(KeyCode.from_vk(ord("E")))

    assert spawn == [app.on_activate]


def test_press_is_robust_against_weird_keys(app, spawn, reset_mods):
    """无关按键不应让监听线程崩溃"""
    app.on_press(Key.f12)
    app.on_release(Key.f12)
    app.on_press(None)

    assert spawn == []


# ===== 热键随配置变化 =====


def test_custom_hotkeys_from_config(make_app, build_config, monkeypatch):
    """热键改为自定义值后应按新配置生效"""
    app = make_app(build_config(hotkey_translate="<alt>+t"))
    started = patch_threads(app, monkeypatch)
    app._pressed_mods = set()

    app.on_press(Key.alt)
    app.on_press(KeyCode.from_vk(ord("T")))

    assert started == [app.on_activate]


def test_old_default_hotkey_no_longer_works(make_app, build_config, monkeypatch):
    """改用自定义热键后，默认的 Ctrl+Shift+E 应失效"""
    app = make_app(build_config(hotkey_translate="<alt>+t"))
    started = patch_threads(app, monkeypatch)
    app._pressed_mods = set()

    app.on_press(Key.ctrl)
    app.on_press(Key.shift)
    app.on_press(KeyCode.from_vk(ord("E")))

    assert started == []
