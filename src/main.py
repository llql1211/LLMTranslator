"""程序入口与各子系统的组装层。

具体逻辑按职责拆分在同级的 config / text / api / hotkeys / clipboard / ui 模块中；
本模块保留原有的模块级接口，既作为对外入口，也让现有测试可以继续以 main.X 的方式打桩。
"""

from __future__ import annotations

import os
import queue
import signal
import sys
import threading
import time
import tkinter

import pyautogui
from pynput import keyboard, mouse
import pyperclip
import requests

import api, clipboard, hotkeys, text, ui
from logger import Timer, error, info, report, shorten, warn
from config import (
    CONFIG_EXAMPLE_PATH,
    CONFIG_PATH_ENV_VAR,
    DEFAULT_CONFIG_PATH,
    GEN_PARAM_MAP,
    NON_EMPTY_KEYS,
    REQUIRED_KEYS,
    ConfigError,
    load_config,
    resolve_active_model,
    resolve_config_path,
)
from hotkeys import parse_hotkey

# --------------------------------------------------------------------------
# 配置：启动时读取一次，运行期这些模块级变量即为各子系统的输入
# --------------------------------------------------------------------------

try:
    config_data = load_config()
except ConfigError as e:
    error(str(e))
    sys.exit(1)

active_model = resolve_active_model(config_data)
ACTIVE_MODEL_NAME = active_model["name"]
ACTIVE_PLATFORM_NAME = active_model["platform"]

API_BASE_URL = active_model["base_url"]
API_KEY = active_model.get("api_key", "")
MODEL_NAME = active_model["model_name"]

TARGET_LANG = config_data["target_lang"]
# 模型未写提示词时，用顶层默认提示词兜底
PROMPT_TEMPLATE = active_model.get("prompt_template") or config_data["prompt_template"]

# 模型自定义的额外请求字段（如关闭 thinking），仅 OpenAI 兼容格式生效
EXTRA_BODY = active_model.get("extra_body", {})

HOTKEY_TRANSLATE = config_data["hotkey_translate"]
HOTKEY_QUIT = config_data["hotkey_quit"]

TOOLTIP_DURATION = config_data["tooltip_duration_ms"]
BACKGROUND_COLOR = config_data["tooltip_background_color"]
TEXT_COLOR = config_data["tooltip_text_color"]
TOOLTIP_OFFSET_X = config_data["tooltip_offset_x"]
TOOLTIP_OFFSET_Y = config_data["tooltip_offset_y"]
RESULT_MAX_WIDTH = config_data["tooltip_result_max_width"]
RESULT_MAX_HEIGHT = config_data["tooltip_result_max_height"]

RESTORE_CLIPBOARD = config_data["restore_clipboard"]

# 开：边翻译边显示；关：等整段翻完再一次性显示
STREAM = config_data["stream"]

# OpenAI 流式请求是否请服务端在末帧返回 token 统计；不兼容的服务可关掉
STREAM_INCLUDE_USAGE = config_data.get("stream_include_usage", True)

# 只在配置文件中写出的生成参数才会被发送，注释掉即使用服务端默认值
GENERATION_PARAMS = {k: config_data[k] for k in GEN_PARAM_MAP if k in config_data}

# 从 keyboard 创建 Controller 实例，用于模拟按键操作
KB_CONTR = keyboard.Controller()


def handler(signum: int, _: object) -> None:
    """将 handler 函数设置为空，忽略 Ctrl+C 中断信号"""
    pass


signal.signal(signal.SIGINT, handler)


# --------------------------------------------------------------------------
# 热键：状态机留在本模块，解析与按键匹配交给 hotkeys 子系统
# --------------------------------------------------------------------------

_matches_key = hotkeys.matches_key

HOTKEY_TRANSLATE_MODS, HOTKEY_TRANSLATE_KEY = parse_hotkey(HOTKEY_TRANSLATE)
HOTKEY_QUIT_MODS, HOTKEY_QUIT_KEY = parse_hotkey(HOTKEY_QUIT)

# 当前修饰键按下状态
_pressed_mods = set()


def on_activate() -> None:
    """翻译热键触发时的回调函数"""
    main()


def on_quit() -> None:
    """退出热键触发时的回调函数"""
    info("正在退出...")
    set_hint_message("正在退出...")
    # 不能只用 sys.exit()（守护线程中只退出线程），用 os._exit 强制结束整个进程
    threading.Thread(target=lambda: (time.sleep(0.5), os._exit(0)), daemon=True).start()


def on_press(key: keyboard.Key | keyboard.KeyCode | None) -> None:
    """键盘按下监听"""
    global _pressed_mods

    try:
        # 记录修饰键
        if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            _pressed_mods.add("ctrl")
            return
        if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
            _pressed_mods.add("shift")
            return
        if key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r):
            _pressed_mods.add("alt")
            return
        if key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            _pressed_mods.add("cmd")
            return

        # 检查翻译热键
        if _matches_key(key, HOTKEY_TRANSLATE_KEY) and _pressed_mods == HOTKEY_TRANSLATE_MODS:
            threading.Thread(target=on_activate, daemon=True).start()
            return

        # 检查退出热键
        if _matches_key(key, HOTKEY_QUIT_KEY) and _pressed_mods == HOTKEY_QUIT_MODS:
            threading.Thread(target=on_quit, daemon=True).start()
            return

    except Exception:
        pass


def on_release(key: keyboard.Key | keyboard.KeyCode | None) -> None:
    """键盘释放监听"""
    global _pressed_mods
    try:
        if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            _pressed_mods.discard("ctrl")
        elif key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
            _pressed_mods.discard("shift")
        elif key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r):
            _pressed_mods.discard("alt")
        elif key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            _pressed_mods.discard("cmd")
    except Exception:
        pass


# --------------------------------------------------------------------------
# 文本清洗与剪贴板
# --------------------------------------------------------------------------

clean_english_text = text.clean_english_text


def get_selected_text() -> str:
    """模拟 Ctrl+C 获取当前选中文本，报错返回空串"""
    return clipboard.get_selected_text(
        controller=KB_CONTR,
        kb=keyboard,
        clipboard=pyperclip,
        restore=RESTORE_CLIPBOARD,
        sleep=time.sleep,
        clean=clean_english_text,
    )


# --------------------------------------------------------------------------
# API：每次调用都用当前模块级配置构造快照，测试可临时替换这些变量
# --------------------------------------------------------------------------

MAX_REDIRECTS = api.MAX_REDIRECTS
REDIRECT_STATUS = api.REDIRECT_STATUS
parse_ollama_stream_line = api.parse_ollama_stream_line
parse_openai_stream_line = api.parse_openai_stream_line
last_usage = api.last_usage


def _api_settings() -> api.ApiSettings:
    return api.ApiSettings(
        base_url=API_BASE_URL,
        api_key=API_KEY,
        model_name=MODEL_NAME,
        prompt_template=PROMPT_TEMPLATE,
        target_lang=TARGET_LANG,
        generation_params=GENERATION_PARAMS,
        extra_params=EXTRA_BODY,
        include_stream_usage=STREAM_INCLUDE_USAGE,
    )


def build_request(text_value: str, stream: bool) -> tuple[str, dict, dict]:
    return api.build_request(text_value, stream, _api_settings())


def http_post(url: str, **kwargs) -> requests.Response:
    return api.http_post(url, post=requests.post, **kwargs)


def translate_with_llm(text_value: str) -> str:
    return api.translate_once(text_value, _api_settings(), post=requests.post)


def translate_stream(text_value: str):
    return api.translate_stream(text_value, _api_settings(), post=requests.post)


# --------------------------------------------------------------------------
# UI：外观参数在调用时从模块级配置构造，窗口状态由 ui 子系统维护
# --------------------------------------------------------------------------

STREAM_POLL_MS = ui.STREAM_POLL_MS
estimate_display_lines = ui.estimate_display_lines


def _ui_settings() -> ui.UiSettings:
    return ui.UiSettings(
        background_color=BACKGROUND_COLOR,
        text_color=TEXT_COLOR,
        offset_x=TOOLTIP_OFFSET_X,
        offset_y=TOOLTIP_OFFSET_Y,
        duration_ms=TOOLTIP_DURATION,
    )


def set_hint_message(msg: str) -> None:
    ui.set_hint_message(msg)


def _create_tooltip_window(x: int, y: int, w: int, h: int) -> tuple:
    return ui.create_tooltip_window(x, y, w, h, _ui_settings(), tk=tkinter)


def _fit_tooltip_height(text_area, text_value: str, w: int, max_height: int) -> None:
    ui.fit_tooltip_height(text_area, text_value, w, max_height)


def show_tooltip(text_value: str, w: int, h: int, mode) -> None:
    ui.show_tooltip(text_value, w, h, mode, _ui_settings())


def show_streaming_tooltip(chunks, w: int, h: int):
    return ui.show_streaming_tooltip(chunks, w, h, _ui_settings())


def show_startup_hint() -> None:
    ui.show_startup_hint()


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------


def main() -> None:
    info("翻译热键触发")
    set_hint_message("翻译中...")

    selected = get_selected_text()
    if selected == "":
        warn("未获取到选中文本，翻译取消")
        set_hint_message("未获取到文本")
    else:
        info(f"选中文本：{shorten(selected)}")
        timer = Timer()
        if STREAM:
            # 流式：内容边到边显示；返回 None 表示用户中途关掉了弹窗
            translation = show_streaming_tooltip(
                translate_stream(selected), RESULT_MAX_WIDTH, RESULT_MAX_HEIGHT
            )
            if translation is None:
                info("翻译已取消")
            elif translation == "":
                warn("翻译失败")
                show_tooltip("翻译失败", 15, 1, "timed")
            else:
                report(timer, last_usage())
        else:
            translation = translate_with_llm(selected)
            if translation == "":
                warn("翻译失败")
                show_tooltip("翻译失败", 15, 1, "timed")
            else:
                report(timer, last_usage())
                show_tooltip(translation, RESULT_MAX_WIDTH, RESULT_MAX_HEIGHT, "persistent")
                info("结果已显示")

    info("等待快捷键...")
    set_hint_message("等待快捷键...")


if __name__ == "__main__":
    # 启动提示框（守护线程，程序退出时自动销毁）
    threading.Thread(target=show_startup_hint, daemon=True).start()

    # 仅一次，输出提示信息
    info("等待快捷键...")

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()
