"""选中文本获取（模拟 Ctrl+C）"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


class FakeClipboard:
    """
    假剪贴板

    - 第一次 paste() 返回操作前的旧内容，之后返回「模拟 Ctrl+C 复制到的新内容」
    - copy() 记录每次写入，便于断言是否写回旧内容
    """

    def __init__(self, old: str = "OLD", selected: str = "SELECTED"):
        self.old = old
        self.selected = selected
        self.written: list[str] = []
        self._paste_calls = 0

    def paste(self) -> str:
        self._paste_calls += 1
        return self.old if self._paste_calls == 1 else self.selected

    def copy(self, text: str) -> None:
        self.written.append(text)


class FakeController:
    """记录按键模拟调用，不真的操作系统键盘"""

    def __init__(self, raise_on_press: bool = False):
        self.events: list[tuple[str, object]] = []
        self._raise_on_press = raise_on_press

    def press(self, key):
        if self._raise_on_press:
            raise RuntimeError("模拟按键失败")
        self.events.append(("press", key))

    def release(self, key):
        self.events.append(("release", key))


@pytest.fixture
def clipboard(app, monkeypatch):
    """替换 pyperclip，并去掉等待用的 sleep"""
    fake = FakeClipboard()
    monkeypatch.setattr(app, "pyperclip", fake)
    monkeypatch.setattr(app.time, "sleep", lambda _seconds: None)
    return fake


@pytest.fixture
def controller(app, monkeypatch):
    fake = FakeController()
    monkeypatch.setattr(app, "KB_CONTR", fake)
    return fake


def test_returns_cleaned_selected_text(app, clipboard, controller):
    """正常路径：取到文本并走清洗"""
    clipboard.selected = "hello\nworld"

    assert app.get_selected_text() == "hello world"


def test_simulates_ctrl_c(app, clipboard, controller):
    """应模拟按下 Ctrl+C 复制选中内容"""
    app.get_selected_text()

    assert ("press", app.keyboard.Key.ctrl) in controller.events


def test_clears_clipboard_before_copying(app, clipboard, controller):
    """复制前先清空剪贴板，避免误取上一次的残留内容"""
    app.get_selected_text()

    assert clipboard.written[0] == ""


def test_restore_clipboard_disabled_keeps_new_content(app, clipboard, controller, monkeypatch):
    """restore_clipboard 为 false 时不写回旧内容"""
    monkeypatch.setattr(app, "RESTORE_CLIPBOARD", False)

    app.get_selected_text()

    assert clipboard.written == [""]


def test_restore_clipboard_enabled_writes_back_old_content(
    app, clipboard, controller, monkeypatch
):
    """restore_clipboard 为 true 时把旧内容写回剪贴板"""
    monkeypatch.setattr(app, "RESTORE_CLIPBOARD", True)

    app.get_selected_text()

    assert clipboard.written[-1] == clipboard.old


def test_returns_empty_when_simulation_fails(app, clipboard, monkeypatch):
    """模拟 Ctrl+C 抛异常时返回空串，而不是向上抛"""
    monkeypatch.setattr(app, "KB_CONTR", FakeController(raise_on_press=True))

    assert app.get_selected_text() == ""


def test_modifiers_released_even_on_failure(app, clipboard, monkeypatch):
    """失败时仍需松开修饰键，否则会残留按下的 Ctrl/Shift 影响用户输入"""
    fake = FakeController(raise_on_press=True)
    monkeypatch.setattr(app, "KB_CONTR", fake)

    app.get_selected_text()

    released = {key for action, key in fake.events if action == "release"}
    assert app.keyboard.Key.ctrl in released
    assert app.keyboard.Key.shift in released


def test_empty_selection_returns_empty(app, clipboard, controller):
    """未选中内容时返回空串"""
    clipboard.selected = ""

    assert app.get_selected_text() == ""


def test_whitespace_selection_returns_empty(app, clipboard, controller):
    """只选中空白字符时等同于未选中"""
    clipboard.selected = "   \n\t "

    assert app.get_selected_text() == ""


def test_uses_configured_restore_flag(make_app, build_config, monkeypatch):
    """restore_clipboard 由配置决定"""
    app = make_app(build_config(restore_clipboard=True))
    fake = FakeClipboard()
    monkeypatch.setattr(app, "pyperclip", fake)
    monkeypatch.setattr(app.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(app, "KB_CONTR", SimpleNamespace(
        press=lambda _key: None, release=lambda _key: None
    ))

    app.get_selected_text()

    assert fake.written[-1] == fake.old
