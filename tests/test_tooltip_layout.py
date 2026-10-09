"""弹窗高度估算与封顶"""

from __future__ import annotations


class FakeText:
    """只记录 height 设置的假 Text 控件"""

    def __init__(self):
        self.height = None

    def config(self, **kwargs):
        self.height = kwargs.get("height")


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
