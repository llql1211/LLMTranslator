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


# ===== 流式分支 =====


@pytest.fixture
def streaming(monkeypatch):
    """打开流式的配置，并拦下除翻译外的所有输出"""
    def _build(make_app, build_config, **config):
        app = make_app(build_config(stream=True, **config))
        monkeypatch.setattr(app, "get_selected_text", lambda: "hello")
        monkeypatch.setattr(app, "set_hint_message", lambda _msg: None)
        monkeypatch.setattr(app, "print", lambda *_args, **_kwargs: None, raising=False)
        return app

    return _build


def test_stream_enabled_uses_streaming_display(streaming, make_app, build_config, monkeypatch):
    """开启流式时走增量显示，不再调用一次性翻译"""
    app = streaming(make_app, build_config)
    calls = []
    monkeypatch.setattr(
        app, "translate_with_llm", lambda _text: pytest.fail("不应调用一次性翻译")
    )
    monkeypatch.setattr(app, "translate_stream", lambda _text: iter(["你", "好"]))
    monkeypatch.setattr(
        app,
        "show_streaming_tooltip",
        lambda chunks, w, h: calls.append((list(chunks), w, h)) or "你好",
    )

    app.main()

    assert calls == [(["你", "好"], app.RESULT_MAX_WIDTH, app.RESULT_MAX_HEIGHT)]


def test_stream_size_follows_config(streaming, make_app, build_config, monkeypatch):
    """流式弹窗尺寸同样取自配置"""
    app = streaming(
        make_app, build_config, tooltip_result_max_width=50, tooltip_result_max_height=12
    )
    sizes = []
    monkeypatch.setattr(app, "translate_stream", lambda _text: iter(()))
    monkeypatch.setattr(
        app, "show_streaming_tooltip", lambda _chunks, w, h: sizes.append((w, h)) or "你好"
    )

    app.main()

    assert sizes == [(50, 12)]


def test_stream_error_shows_timed_tooltip(streaming, make_app, build_config, monkeypatch):
    """一块都没收到时弹出自动关闭的错误提示"""
    app = streaming(make_app, build_config)
    tooltips = []
    monkeypatch.setattr(app, "translate_stream", lambda _text: iter(()))
    monkeypatch.setattr(app, "show_streaming_tooltip", lambda *_args: "")
    monkeypatch.setattr(
        app, "show_tooltip", lambda text, w, h, mode: tooltips.append((text, w, h, mode))
    )

    app.main()

    assert tooltips == [("翻译失败", 15, 1, "timed")]


def test_stream_success_shows_no_extra_tooltip(streaming, make_app, build_config, monkeypatch):
    """流式成功时结果已由增量弹窗展示，不再补一个窗口"""
    app = streaming(make_app, build_config)
    tooltips = []
    monkeypatch.setattr(app, "translate_stream", lambda _text: iter(["你好"]))
    monkeypatch.setattr(app, "show_streaming_tooltip", lambda *_args: "你好")
    monkeypatch.setattr(
        app, "show_tooltip", lambda text, w, h, mode: tooltips.append((text, w, h, mode))
    )

    app.main()

    assert tooltips == []


def test_stream_cancelled_shows_nothing(streaming, make_app, build_config, monkeypatch):
    """用户中途关掉弹窗时不再弹错误提示"""
    app = streaming(make_app, build_config)
    tooltips = []
    monkeypatch.setattr(app, "translate_stream", lambda _text: iter(["你"]))
    monkeypatch.setattr(app, "show_streaming_tooltip", lambda *_args: None)
    monkeypatch.setattr(
        app, "show_tooltip", lambda text, w, h, mode: tooltips.append((text, w, h, mode))
    )

    app.main()

    assert tooltips == []


def test_stream_disabled_uses_oneshot_display(app, ui, monkeypatch):
    """关闭流式时仍走一次性翻译，不触碰流式路径"""
    monkeypatch.setattr(app, "get_selected_text", lambda: "hello")
    monkeypatch.setattr(app, "translate_with_llm", lambda _text: "你好")
    monkeypatch.setattr(app, "translate_stream", lambda _text: pytest.fail("不应走流式"))
    monkeypatch.setattr(app, "show_streaming_tooltip", lambda *_args: pytest.fail("不应走流式"))

    app.main()

    assert ui["tooltips"] == [
        ("你好", app.RESULT_MAX_WIDTH, app.RESULT_MAX_HEIGHT, "persistent")
    ]


def test_stream_hint_resets_after_run(streaming, make_app, build_config, monkeypatch):
    """流式跑完后右上角提示同样复位"""
    app = streaming(make_app, build_config)
    hints = []
    monkeypatch.setattr(app, "set_hint_message", hints.append)
    monkeypatch.setattr(app, "translate_stream", lambda _text: iter(("你好",)))
    monkeypatch.setattr(app, "show_streaming_tooltip", lambda *_args: "你好")

    app.main()

    assert hints == ["翻译中...", "等待快捷键..."]
