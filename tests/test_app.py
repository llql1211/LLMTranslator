"""主流程编排（不创建真实窗口）"""

from __future__ import annotations

import pytest


@pytest.fixture
def ui(app, monkeypatch):
    """
    拦下所有输出，返回记录用的容器

    - hints: 右上角提示框文本的变化序列
    - tooltips: 弹窗调用参数 (text, w, h, mode)
    """
    state = {"hints": [], "tooltips": []}
    monkeypatch.setattr(app, "set_hint_message", state["hints"].append)
    monkeypatch.setattr(
        app, "show_tooltip", lambda text, w, h, mode: state["tooltips"].append((text, w, h, mode))
    )
    # main 模块没有 print 这个属性，需要 raising=False 才允许挂一个上去
    monkeypatch.setattr(app, "print", lambda *_args, **_kwargs: None, raising=False)
    return state


def test_empty_selection_shows_hint(app, ui, monkeypatch):
    """未取到文本时提示「未获取到文本」，且不弹窗"""
    monkeypatch.setattr(app, "get_selected_text", lambda: "")

    app.main()

    assert ui["hints"] == ["翻译中...", "未获取到文本", "等待快捷键..."]
    assert ui["tooltips"] == []


def test_successful_translation_shows_persistent_tooltip(app, ui, monkeypatch):
    """翻译成功时弹出可交互的结果窗口"""
    monkeypatch.setattr(app, "get_selected_text", lambda: "hello")
    monkeypatch.setattr(app, "translate_with_llm", lambda _text: "你好")

    app.main()

    assert ui["tooltips"] == [
        ("你好", app.RESULT_MAX_WIDTH, app.RESULT_MAX_HEIGHT, "persistent")
    ]
    assert ui["hints"][-1] == "等待快捷键..."


def test_failed_translation_shows_timed_tooltip(app, ui, monkeypatch):
    """翻译失败时弹出自动关闭的错误提示"""
    monkeypatch.setattr(app, "get_selected_text", lambda: "hello")
    monkeypatch.setattr(app, "translate_with_llm", lambda _text: "")

    app.main()

    assert ui["tooltips"] == [("翻译失败", 15, 1, "timed")]
    assert ui["hints"][-1] == "等待快捷键..."


def test_selected_text_is_passed_to_translator(app, ui, monkeypatch):
    """清洗后的选中文本应原样传给翻译"""
    seen = []
    monkeypatch.setattr(app, "get_selected_text", lambda: "hello world")
    monkeypatch.setattr(app, "translate_with_llm", lambda text: seen.append(text) or "你好")

    app.main()

    assert seen == ["hello world"]


def test_hint_resets_after_each_run(app, ui, monkeypatch):
    """每轮结束后提示框回到「等待快捷键...」"""
    monkeypatch.setattr(app, "get_selected_text", lambda: "hello")
    monkeypatch.setattr(app, "translate_with_llm", lambda _text: "你好")

    app.main()
    app.main()

    assert ui["hints"].count("等待快捷键...") == 2


def test_translate_hotkey_callback_runs_main(app, monkeypatch):
    """翻译热键回调直接触发主流程"""
    called = []
    monkeypatch.setattr(app, "main", lambda: called.append(True))

    app.on_activate()

    assert called == [True]


def test_tooltip_size_follows_config(make_app, build_config, monkeypatch):
    """弹窗尺寸取自配置"""
    app = make_app(build_config(tooltip_result_max_width=50, tooltip_result_max_height=12))
    tooltips = []
    monkeypatch.setattr(app, "get_selected_text", lambda: "hello")
    monkeypatch.setattr(app, "translate_with_llm", lambda _text: "你好")
    monkeypatch.setattr(app, "set_hint_message", lambda _msg: None)
    monkeypatch.setattr(app, "print", lambda *_args, **_kwargs: None, raising=False)
    monkeypatch.setattr(
        app, "show_tooltip", lambda text, w, h, mode: tooltips.append((text, w, h, mode))
    )

    app.main()

    assert tooltips == [("你好", 50, 12, "persistent")]
