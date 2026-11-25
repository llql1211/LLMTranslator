"""深浅主题的配色选择"""

from __future__ import annotations

import main


def test_light_mode_uses_sticky_note_yellow(app):
    """默认浅色模式沿用配置里的便签黄与深色字"""
    assert app.THEME == "light"
    assert app._tooltip_colors() == ("#FFFFE0", "#000000")
    assert app._ui_settings().background_color == "#FFFFE0"


def test_dark_mode_uses_dark_palette(make_app, build_config):
    app = make_app(build_config(theme="dark"))

    assert app._tooltip_colors() == ("#2B2B2B", "#EAEAEA")
    settings = app._ui_settings()
    assert settings.background_color == "#2B2B2B"
    assert settings.text_color == "#EAEAEA"


def test_dark_colors_can_be_customized(make_app, build_config):
    app = make_app(
        build_config(
            theme="dark",
            tooltip_background_color_dark="#101010",
            tooltip_text_color_dark="#EEEEEE",
        )
    )

    assert app._tooltip_colors() == ("#101010", "#EEEEEE")


def test_theme_light_ignores_legacy_dark_colors(make_app, build_config):
    """显式写了 theme 后，旧字段里的深色值不应把浅色模式带偏"""
    app = make_app(
        build_config(
            theme="light",
            tooltip_background_color="#323232",
            tooltip_text_color="#FFFFFF",
        )
    )

    assert app._tooltip_colors() == ("#FFFFE0", "#000000")


def test_light_colors_can_be_customized(make_app, build_config):
    app = make_app(
        build_config(
            theme="light",
            tooltip_background_color_light="#FFF9C4",
            tooltip_text_color_light="#222222",
        )
    )

    assert app._tooltip_colors() == ("#FFF9C4", "#222222")


def test_legacy_colors_still_work_without_theme(make_app, build_config):
    """没写 theme 的旧配置继续沿用旧的自定义颜色"""
    lines = [
        line for line in build_config().splitlines()
        if not line.startswith("theme =")
    ]
    text = "\n".join(lines).replace(
        'tooltip_background_color = "#FFFFE0"', 'tooltip_background_color = "#123456"'
    ).replace(
        'tooltip_text_color = "#000000"', 'tooltip_text_color = "#ABCDEF"'
    )
    app = make_app(text + "\n")

    assert app._tooltip_colors() == ("#123456", "#ABCDEF")


def test_light_mode_ignores_dark_colors(make_app, build_config):
    app = make_app(
        build_config(
            theme="light",
            tooltip_background_color_dark="#101010",
        )
    )

    assert app._tooltip_colors() == ("#FFFFE0", "#000000")


def test_startup_hint_receives_theme(make_app, build_config, monkeypatch):
    app = make_app(build_config(theme="dark"))
    seen = []
    monkeypatch.setattr(app.ui, "show_startup_hint", lambda theme: seen.append(theme))

    app.show_startup_hint()

    assert seen == ["dark"]
