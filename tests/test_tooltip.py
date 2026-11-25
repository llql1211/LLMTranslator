"""弹窗的建窗参数、颜色配置与高度估算"""

from __future__ import annotations

import pytest

import ui


class FakeText:
    """只记录 height 设置的假 Text 控件"""

    def __init__(self):
        self.height = None

    def config(self, **kwargs):
        self.height = kwargs.get("height")


class FakeRoot:
    """假 Tk 根窗口"""

    def __init__(self):
        self.config_kwargs = {}
        self.geometry_str = None

    def overrideredirect(self, _value):
        pass

    def attributes(self, *_args):
        pass

    def configure(self, **kwargs):
        self.config_kwargs.update(kwargs)

    def geometry(self, value):
        self.geometry_str = value


class FakeWidget:
    """假 Text 控件，只记录建窗时传入的参数"""

    def __init__(self, _master, **kwargs):
        self.kwargs = kwargs

    def pack(self, **_kwargs):
        pass


class FakeTkinter:
    """只够 _create_tooltip_window 用的假 tkinter，避免测试真的弹出窗口"""

    WORD = "word"
    FLAT = "flat"
    BOTH = "both"

    def __init__(self):
        self.root = None
        self.text = None

    def Tk(self):
        self.root = FakeRoot()
        return self.root

    def Text(self, master, **kwargs):
        self.text = FakeWidget(master, **kwargs)
        return self.text


def create_window(app, monkeypatch, x=11, y=22, w=30, h=8) -> FakeTkinter:
    """用假 tkinter 调一次 _create_tooltip_window，返回建窗过程中记录下的参数"""
    fake = FakeTkinter()
    monkeypatch.setattr(app, "tkinter", fake)
    app._create_tooltip_window(x, y, w, h)
    return fake


# ===== 建窗参数 =====


def test_window_uses_configured_background_color(make_app, build_config, monkeypatch):
    app = make_app(build_config(tooltip_background_color="#112233"))

    fake = create_window(app, monkeypatch)

    assert fake.text.kwargs["bg"] == "#112233"


def test_window_uses_configured_text_color(make_app, build_config, monkeypatch):
    app = make_app(build_config(tooltip_text_color="#AABBCC"))

    fake = create_window(app, monkeypatch)

    assert fake.text.kwargs["fg"] == "#AABBCC"


def test_window_cursor_follows_text_color(make_app, build_config, monkeypatch):
    """文本光标跟随文字颜色，深色背景下才不会留下一道刺眼的黑竖线"""
    app = make_app(
        build_config(tooltip_background_color="#323232", tooltip_text_color="#FFFFFF")
    )

    fake = create_window(app, monkeypatch)

    assert fake.text.kwargs["insertbackground"] == "#FFFFFF"


def test_root_background_matches_tooltip(app, monkeypatch):
    """窗口自身的底色也要设置，否则四角会露出系统默认灰"""
    fake = create_window(app, monkeypatch)

    assert fake.root.config_kwargs["bg"] == app.BACKGROUND_COLOR


def test_window_size_comes_from_arguments(app, monkeypatch):
    fake = create_window(app, monkeypatch, w=30, h=8)

    assert fake.text.kwargs["width"] == 30
    assert fake.text.kwargs["height"] == 8


def test_window_is_positioned_by_mouse_plus_offsets(app, monkeypatch):
    fake = create_window(app, monkeypatch, x=11, y=22)

    expected = f"+{11 + app.TOOLTIP_OFFSET_X}+{22 + app.TOOLTIP_OFFSET_Y}"
    assert fake.root.geometry_str == expected


# ===== estimate_display_lines =====


def test_empty_text_still_needs_one_line(app):
    assert app.estimate_display_lines("", 30) == 1


def test_short_text_needs_one_line(app):
    assert app.estimate_display_lines("你好", 30) == 1


def test_latin_text_wraps_by_width(app):
    """拉丁字符按一倍宽度计"""
    assert app.estimate_display_lines("a" * 30, 30) == 1
    assert app.estimate_display_lines("a" * 31, 30) == 2
    assert app.estimate_display_lines("a" * 60, 30) == 2


def test_cjk_text_counts_double_width(app):
    """中日韩字符约占两倍字符宽度"""
    assert app.estimate_display_lines("一" * 15, 30) == 1
    assert app.estimate_display_lines("一" * 16, 30) == 2
    assert app.estimate_display_lines("一" * 30, 30) == 2


def test_mixed_width_text(app):
    """中英混排时按各自宽度累加"""
    assert app.estimate_display_lines("你a" * 5, 30) == 1


def test_newlines_start_new_lines(app):
    assert app.estimate_display_lines("a\nb\nc", 30) == 3


def test_blank_lines_still_occupy_a_line(app):
    assert app.estimate_display_lines("a\n\nb", 30) == 3


def test_lines_are_measured_independently(app):
    """每行单独计算，上一行的剩余宽度不借给下一行"""
    assert app.estimate_display_lines("a" * 20 + "\n" + "a" * 20, 30) == 2


def test_estimate_grows_with_content(app):
    """估算值必须随内容单调增长，否则弹窗高度不会跟着长"""
    texts = ["", "短句", "一" * 60, "一" * 200, "一" * 600]
    lines = [app.estimate_display_lines(t, 30) for t in texts]

    assert lines == sorted(lines)
    assert lines[-1] > lines[0]


# ===== _fit_tooltip_height =====


def test_fit_height_grows_with_content(app):
    area = FakeText()

    app._fit_tooltip_height(area, "a" * 60, 30, 8)

    assert area.height == 2


def test_fit_height_is_capped(app):
    """超过上限即封顶，之后靠内部滚动查看"""
    area = FakeText()

    app._fit_tooltip_height(area, "a" * 300, 30, 8)

    assert area.height == 8


def test_fit_height_never_below_one(app):
    """空内容时至少占一行，避免窗口塌成零高度"""
    area = FakeText()

    app._fit_tooltip_height(area, "", 30, 8)

    assert area.height == 1


def test_fit_height_uses_configured_width(app):
    """宽度越大，同样的文本占的行数越少"""
    narrow, wide = FakeText(), FakeText()

    app._fit_tooltip_height(narrow, "a" * 60, 20, 8)
    app._fit_tooltip_height(wide, "a" * 60, 60, 8)

    assert narrow.height > wide.height


# ===== 外观与排版 =====


def test_window_uses_larger_font_and_subtle_border(app, monkeypatch):
    fake = create_window(app, monkeypatch)

    assert fake.text.kwargs["font"] == ("Microsoft YaHei", 11)
    assert fake.text.kwargs["highlightthickness"] == 1
    assert fake.text.kwargs["padx"] == 10


def test_window_uses_configured_font(make_app, build_config, monkeypatch):
    """字体与字号来自配置，而不是写死在代码里"""
    app = make_app(build_config(tooltip_font_family="Consolas", tooltip_font_size=16))

    assert app._ui_settings().font_family == "Consolas"
    assert app._ui_settings().font_size == 16
    fake = create_window(app, monkeypatch)
    assert fake.text.kwargs["font"] == ("Consolas", 16)


def test_window_uses_default_font_when_not_configured(make_app, build_config, missing, monkeypatch):
    """旧配置没写字体/字号时仍沿用原来的内置字体"""
    app = make_app(build_config(tooltip_font_family=missing, tooltip_font_size=missing))
    fake = create_window(app, monkeypatch)

    assert fake.text.kwargs["font"] == ("Microsoft YaHei", 11)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  a  \r\n\r\n\r\nb  \n", "a\n\nb"),
        ("\n\nhi\n\n", "hi"),
        ("a\n\n\n\nb", "a\n\nb"),
        ("", ""),
    ],
)
def test_normalize_result_cleans_layout(raw, expected):
    assert ui.normalize_result(raw) == expected


@pytest.mark.parametrize(
    ("message", "style"),
    [
        ("等待快捷键...", "idle"),
        ("翻译中...", "busy"),
        ("未获取到文本", "error"),
        ("翻译失败", "error"),
        ("翻译中断", "error"),
        ("正在退出...", "exit"),
    ],
)
def test_hint_style_matches_status(message, style):
    assert ui._hint_style(message, "light") == ui._HINT_STYLES["light"][style]


@pytest.mark.parametrize(
    "message",
    ["等待快捷键...", "翻译中...", "未获取到文本", "翻译失败", "翻译中断", "正在退出..."],
)
def test_light_hint_always_has_white_background(message):
    """浅色模式的提示框保持白底，仅靠文字与强调条区分状态"""
    bg, _fg, _accent = ui._hint_style(message, "light")

    assert bg == "#FFFFFF"


def test_dark_hint_uses_dark_palette():
    assert ui._hint_style("翻译中...", "dark") == ui._HINT_STYLES["dark"]["busy"]
    assert ui._hint_style("等待快捷键...", "dark") == ui._HINT_STYLES["dark"]["idle"]
