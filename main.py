from __future__ import annotations

import json
import os
import queue
import re
import signal
import sys
import threading
import time
import tkinter
import tomllib
from collections.abc import Callable, Iterator
from typing import Literal

import pyautogui
from pynput import keyboard, mouse
import pyperclip
import requests


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(BASE_DIR, "data", "config.toml")
CONFIG_EXAMPLE_PATH = os.path.join(BASE_DIR, "data", "config.example.toml")

# 可用该环境变量指定其他配置文件，覆盖默认路径
CONFIG_PATH_ENV_VAR = "LLMTRANSLATOR_CONFIG"

# 必填配置项，缺失时直接报错退出
REQUIRED_KEYS = (
    "base_url",
    "api_key",
    "model_name",
    "target_lang",
    "prompt_template",
    "hotkey_translate",
    "hotkey_quit",
    "tooltip_background_color",
    "tooltip_offset_x",
    "tooltip_offset_y",
    "tooltip_result_max_width",
    "tooltip_result_max_height",
    "tooltip_duration_ms",
    "restore_clipboard",
    "stream",
)

# 必填且不能为空的配置项
NON_EMPTY_KEYS = (
    "base_url",
    "model_name",
)

# 生成参数：配置项名 → Ollama 原生格式对应的 options 字段名
GEN_PARAM_MAP = {
    "temperature": "temperature",
    "top_p": "top_p",
    "top_k": "top_k",
    "repetition_penalty": "repeat_penalty",
    "max_tokens": "num_predict",
}


class ConfigError(Exception):
    """配置文件缺失、格式错误或内容不合法"""


def resolve_config_path(path: str | None = None) -> str:
    """按 显式参数 → 环境变量 → 默认路径 的优先级确定配置文件位置"""
    if path:
        return path
    return os.environ.get(CONFIG_PATH_ENV_VAR) or DEFAULT_CONFIG_PATH


def load_config(path: str | None = None) -> dict:
    """
    读取并校验配置

    出错时抛出 ConfigError，由调用方决定如何提示与退出
    """
    config_path = resolve_config_path(path)

    if not os.path.exists(config_path):
        raise ConfigError(
            f"未找到配置文件：{config_path}\n"
            "请复制模板后按需修改：\n"
            f"    copy {CONFIG_EXAMPLE_PATH} {config_path}"
        )

    try:
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"配置文件解析失败：{config_path}\n{e}") from e

    missing = [k for k in REQUIRED_KEYS if k not in config]
    if missing:
        raise ConfigError(
            f"配置文件缺少必要项：{', '.join(missing)}\n"
            f"请参考模板：{CONFIG_EXAMPLE_PATH}"
        )

    # 模板中将访问地址与模型名留空，需用户自行填写
    empty = [k for k in NON_EMPTY_KEYS if not config[k]]
    if empty:
        raise ConfigError(
            f"以下配置项不能为空：{', '.join(empty)}\n请在 {config_path} 中填写"
        )

    return config


try:
    config = load_config()
except ConfigError as e:
    print(e)
    sys.exit(1)

API_BASE_URL = config["base_url"]
MODEL_NAME = config["model_name"]
API_KEY = config["api_key"]

TARGET_LANG = config["target_lang"]
PROMPT_TEMPLATE = config["prompt_template"]

HOTKEY_TRANSLATE = config["hotkey_translate"]
HOTKEY_QUIT = config["hotkey_quit"]

TOOLTIP_DURATION = config["tooltip_duration_ms"]
BACKGROUND_COLOR = config["tooltip_background_color"]
TOOLTIP_OFFSET_X = config["tooltip_offset_x"]
TOOLTIP_OFFSET_Y = config["tooltip_offset_y"]
RESULT_MAX_WIDTH = config["tooltip_result_max_width"]
RESULT_MAX_HEIGHT = config["tooltip_result_max_height"]

RESTORE_CLIPBOARD = config["restore_clipboard"]

# 开：边翻译边显示；关：等整段翻完再一次性显示
STREAM = config["stream"]

# 只在配置文件中写出的生成参数才会被发送，注释掉即使用服务端默认值
GENERATION_PARAMS = {k: config[k] for k in GEN_PARAM_MAP if k in config}


# 从 keyboard 创建 Controller 实例，用于模拟按键操作
KB_CONTR = keyboard.Controller()


def handler(signum: int, _: object) -> None:
    """将 handler 函数设置为空，忽略 Ctrl+C 中断信号"""
    pass


signal.signal(signal.SIGINT, handler)


def on_activate() -> None:
    """翻译热键触发时的回调函数"""
    main()


def on_quit() -> None:
    """退出热键触发时的回调函数"""
    print("\n正在退出...\n")
    set_hint_message("正在退出...")
    # 不能只用 sys.exit()（守护线程中只退出线程），用 os._exit 强制结束整个进程
    threading.Thread(target=lambda: (time.sleep(0.5), os._exit(0)), daemon=True).start()


def parse_hotkey(spec: str) -> tuple[set[str], str]:
    """
    解析 '<ctrl>+<shift>+e' 格式的热键，返回 (修饰键集合, 主键)

    容忍配置中书写时多余的空白，如 '<ctrl> + <shift> + e'
    """
    parts = spec.lower().split("+")
    mods: set[str] = set()
    key_char = ""
    for p in parts:
        p = p.strip().strip("<>")
        if p in ("ctrl", "shift", "alt", "cmd"):
            mods.add(p)
        else:
            key_char = p
    return mods, key_char


HOTKEY_TRANSLATE_MODS, HOTKEY_TRANSLATE_KEY = parse_hotkey(HOTKEY_TRANSLATE)
HOTKEY_QUIT_MODS, HOTKEY_QUIT_KEY = parse_hotkey(HOTKEY_QUIT)

# 当前修饰键按下状态
_pressed_mods = set()


def _matches_key(key: object, expected_char: str) -> bool:
    """
    判断按键是否匹配期望字符（通过 VK 精确匹配，不受 Ctrl/Shift 修饰键影响）

    Windows 下字母 VK 等于其大写 ASCII 码
    """
    vk = getattr(key, 'vk', None)
    if vk is None:
        return False
    expected_vk = ord(expected_char.upper())
    return vk == expected_vk


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


def clean_english_text(text: str) -> str:
    """
    清洗 ASCII 文本

    将连续空格替换为单个空格，根据上下文添加句号，同时保留原换行格式
    """
    lines = [line.strip() for line in text.splitlines()]
    punctuation = {'.', '?', '!'}
    cleaned = ""

    for i in range(len(lines)):
        current = lines[i]
        if not cleaned:
            cleaned = current
        elif not current:
            cleaned += '\n'
        # 若当前行以小写字母开头，且上一行不以标点结尾，则直接合并
        elif current[0].islower() and (cleaned[-1] not in punctuation):
            cleaned = cleaned + ' ' + current
        # 若当前行以大写字母开头，且上一行末尾无标点，默认添加句号
        elif current[0].isupper() and (cleaned[-1] not in punctuation):
            cleaned += '.\n' + current
        else:
            cleaned = cleaned + '\n' + current

    # 正则表达式，将连续的空格或制表符替换为单个空格
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    return cleaned.strip()


def get_selected_text() -> str:
    """
    模拟 Ctrl+C 获取当前选中文本

    报错返回空串
    """
    old_clipboard = pyperclip.paste()
    pyperclip.copy('')
    time.sleep(0.03)  # 等待剪切板被清空

    try:
        # 先释放热键修饰键（Ctrl+Shift），确保键盘状态干净
        KB_CONTR.release(keyboard.Key.ctrl)
        KB_CONTR.release(keyboard.Key.shift)
        time.sleep(0.02)

        # 使用 pynput 模拟 Ctrl+C
        KB_CONTR.press(keyboard.Key.ctrl)
        KB_CONTR.press('c')
        KB_CONTR.release('c')
        KB_CONTR.release(keyboard.Key.ctrl)
        time.sleep(0.05)
        
        new_text = clean_english_text(pyperclip.paste())
        return new_text
    except Exception as e:
        print(f"-> 未获取选中文本，模拟 Ctrl+C 失败: {e} ")
        return ""
    finally:
        # 显式释放所有修饰键
        KB_CONTR.release(keyboard.Key.ctrl)
        KB_CONTR.release(keyboard.Key.shift)
        KB_CONTR.release('c')

        # 恢复原剪贴板内容（若设置了 RESTORE_CLIPBOARD）
        if RESTORE_CLIPBOARD:
            pyperclip.copy(old_clipboard)


def build_request(text: str, stream: bool) -> tuple[str, dict, dict]:
    """
    构造翻译请求，返回 (url, payload, headers)

    - api_key 为空 → Ollama 原生格式（/api/generate）
    - api_key 非空 → OpenAI 兼容格式（/v1/chat/completions）

    生成参数（GENERATION_PARAMS）按格式转换后一并写入 payload
    """
    prompt = PROMPT_TEMPLATE.format(target_lang=TARGET_LANG, input_text=text)

    if API_KEY:
        # OpenAI 兼容格式
        url = API_BASE_URL.rstrip("/")
        if not url.endswith("/chat/completions"):
            url = url.rstrip("/v1") + "/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
            # OpenAI 兼容格式的生成参数平铺在顶层，字段名与配置项一致
            **GENERATION_PARAMS,
        }
    else:
        # Ollama 原生格式
        url = API_BASE_URL
        headers = {}
        payload = {
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": stream
        }
        if GENERATION_PARAMS:
            # Ollama 原生格式的生成参数统一放在 options 中，且部分字段名与 OpenAI 不同
            payload["options"] = {
                GEN_PARAM_MAP[k]: v for k, v in GENERATION_PARAMS.items()
            }

    return url, payload, headers


def parse_ollama_stream_line(line: str) -> str | None:
    """
    解析 Ollama 流式响应的一行（NDJSON），返回增量文本

    空行、坏 JSON、无内容的分块一律返回 None，不让单行异常打断整段翻译
    """
    line = line.strip()
    if not line:
        return None

    try:
        chunk = json.loads(line)
    except json.JSONDecodeError:
        return None

    if not isinstance(chunk, dict):
        return None

    text = chunk.get("response")
    return text if isinstance(text, str) and text else None


def parse_openai_stream_line(line: str) -> str | None:
    """
    解析 OpenAI 流式响应的一行（SSE），返回增量文本

    非 data: 开头的行、结束标记 [DONE]、坏 JSON、无内容的分块一律返回 None
    """
    line = line.strip()
    if not line.startswith("data:"):
        return None

    data = line[len("data:"):].strip()
    if not data or data == "[DONE]":
        return None

    try:
        chunk = json.loads(data)
    except json.JSONDecodeError:
        return None

    if not isinstance(chunk, dict):
        return None

    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return None

    delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
    text = delta.get("content") if isinstance(delta, dict) else None
    return text if isinstance(text, str) and text else None


def translate_with_llm(text: str) -> str:
    """
    调用 LLM API 翻译，等全部生成完再返回

    报错返回空串
    """
    url, payload, headers = build_request(text, stream=False)

    result_text = ""
    try:
        print("-> 翻译中... ", end="")
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        if API_KEY:
            # OpenAI 格式：response.choices[0].message.content
            result_text = result["choices"][0]["message"]["content"].strip()
        else:
            # Ollama 格式：response
            result_text = result.get("response", "").strip()
    except Exception as e:
        print(f"-> 翻译失败：{e} ")

    return result_text


def translate_stream(text: str) -> Iterator[str]:
    """
    流式调用 LLM API 翻译，逐块产出增量文本

    网络或服务端出错时抛异常，调用方已收到的部分由调用方自己保留

    调用方提前结束迭代（如 break）时，生成器被关闭并断开连接
    """
    url, payload, headers = build_request(text, stream=True)
    parse_line = parse_openai_stream_line if API_KEY else parse_ollama_stream_line

    response = requests.post(
        url, json=payload, headers=headers, timeout=30, stream=True
    )
    try:
        response.raise_for_status()
        for raw_line in response.iter_lines():
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line.removeprefix("data:").strip() == "[DONE]":
                # OpenAI 兼容格式的结束标记，收到即停止
                break
            chunk = parse_line(line)
            if chunk:
                yield chunk
    finally:
        response.close()


# 全局 Tkinter 窗口，复用避免重复创建
_TOOLTIP_ROOT = None
_TOOLTIP_TEXT = None

# 当前弹窗关闭方式的清理函数（停鼠标监听、取消定时器）
_TOOLTIP_CLEANUP: Callable[[], None] | None = None

# 流式显示的刷新间隔（毫秒）
STREAM_POLL_MS = 50

# 右上角常驻提示框
_HINT_ROOT = None
_HINT_LABEL = None


def set_hint_message(msg: str) -> None:
    """线程安全地更新右上角常驻提示框的文本"""
    root = _HINT_ROOT
    if root and root.winfo_exists():
        root.after(0, lambda: _HINT_LABEL.config(text=msg) if _HINT_LABEL else None)


def _create_tooltip_window(x: int, y: int, w: int, h: int) -> tuple:
    """
    在鼠标位置创建无边框置顶弹窗

    返回 (root, text_area)，须在随后运行该 root 的 mainloop 的线程中调用
    """
    root = tkinter.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.configure(bg=BACKGROUND_COLOR)
    root.geometry(f"+{x+TOOLTIP_OFFSET_X}+{y+TOOLTIP_OFFSET_Y}")

    text_area = tkinter.Text(
        root,
        wrap=tkinter.WORD,
        font=("Microsoft YaHei", 10),
        width=w,
        height=h,
        relief=tkinter.FLAT,
        bg=BACKGROUND_COLOR,
        fg='black',
        insertbackground='black',
        bd=0,
        padx=5,
        pady=5
    )
    text_area.pack(fill=tkinter.BOTH, expand=True)

    return root, text_area


def _attach_close_handlers(root, on_close: Callable[[], None], mode: Literal["timed", "persistent"]) -> Callable[[], None]:
    """
    给弹窗绑定关闭方式，返回清理函数

    - "timed"：TOOLTIP_DURATION 毫秒后自动关闭
    - "persistent"：点击弹窗外部或按 Esc 关闭

    清理函数用于取消定时器并停止鼠标监听，销毁窗口前必须先调用
    """
    holder = {"listener": None, "timer": None}

    def stop_listener():
        listener = holder["listener"]
        if listener and listener.running:
            listener.stop()
        holder["listener"] = None

    def on_click(x, y, _, pressed):
        """全局鼠标点击回调——点击外部关闭弹窗"""
        if not pressed:
            return
        try:
            x1 = root.winfo_rootx()
            y1 = root.winfo_rooty()
            x2 = x1 + root.winfo_width()
            y2 = y1 + root.winfo_height()
            if not (x1 <= x <= x2 and y1 <= y <= y2):
                root.after(0, on_close)
        except tkinter.TclError:
            pass

    def start_listener():
        stop_listener()
        listener = mouse.Listener(on_click=on_click)
        listener.daemon = True
        listener.start()
        holder["listener"] = listener

    if mode == "timed":
        holder["timer"] = root.after(TOOLTIP_DURATION, on_close)
    else:
        start_listener()

    root.bind("<Escape>", lambda _e: on_close())

    def cleanup():
        stop_listener()
        if holder["timer"]:
            try:
                root.after_cancel(holder["timer"])
            except tkinter.TclError:
                pass
            holder["timer"] = None

    return cleanup


def estimate_display_lines(text: str, width: int) -> int:
    """
    估算文本在给定宽度下占用的显示行数

    Text 的 width 以「平均字符宽度」为单位，中日韩字符约占两倍，其余按一倍计

    以估算代替 Tk 的 displaylines：后者要求控件已完成布局，刷新过程中拿到的
    数值并不可靠。此处宁可粗糙，只要随内容单调增长即可
    """
    total = 0
    for line in text.split("\n"):
        units = sum(2 if ord(ch) > 0x2E80 else 1 for ch in line)
        total += max(1, -(-units // width))
    return total


def _fit_tooltip_height(text_area, text: str, w: int, max_height: int) -> None:
    """按内容估算高度，到 max_height 行封顶，超出部分靠内部滚动查看"""
    text_area.config(height=max(1, min(max_height, estimate_display_lines(text, w))))


def show_tooltip(text: str, w: int, h: int, mode: Literal["timed", "persistent"]) -> None:
    """
    在鼠标右下角显示无边框矩形文本框

    - w: 字符, h: 行
    - mode: "timed" 5秒自动关闭，"persistent" 点击外部或按 Esc 关闭
    - 不抢焦点，点击弹窗内部可选中文本，鼠标悬停可滚动
    """

    def safe_destroy(_event=None):
        """安全销毁窗口（接受可选 event 参数用于 bind 回调）"""
        global _TOOLTIP_ROOT, _TOOLTIP_TEXT, _TOOLTIP_CLEANUP
        cleanup, _TOOLTIP_CLEANUP = _TOOLTIP_CLEANUP, None
        if cleanup:
            cleanup()
        try:
            if _TOOLTIP_ROOT and _TOOLTIP_ROOT.winfo_exists():
                _TOOLTIP_ROOT.destroy()
        except tkinter.TclError:
            pass
        _TOOLTIP_ROOT = None
        _TOOLTIP_TEXT = None

    def update_or_create():
        global _TOOLTIP_ROOT, _TOOLTIP_TEXT, _TOOLTIP_CLEANUP

        x, y = pyautogui.position()

        if _TOOLTIP_TEXT and _TOOLTIP_ROOT and _TOOLTIP_ROOT.winfo_exists():
            # 复用已有窗口：移动位置、更新文本、重绑关闭方式
            root, text_area = _TOOLTIP_ROOT, _TOOLTIP_TEXT
            if _TOOLTIP_CLEANUP:
                _TOOLTIP_CLEANUP()
            root.geometry(f"+{x+TOOLTIP_OFFSET_X}+{y+TOOLTIP_OFFSET_Y}")
            text_area.config(height=h, width=w)
            text_area.delete(1.0, tkinter.END)
            text_area.insert(tkinter.END, text)
            _TOOLTIP_CLEANUP = _attach_close_handlers(root, safe_destroy, mode)
            root.lift()
            return

        # 首次创建窗口
        root, text_area = _create_tooltip_window(x, y, w, h)
        text_area.insert(tkinter.END, text)

        _TOOLTIP_ROOT = root
        _TOOLTIP_TEXT = text_area
        _TOOLTIP_CLEANUP = _attach_close_handlers(root, safe_destroy, mode)

        root.mainloop()

    # 使用线程避免阻塞
    thread = threading.Thread(target=update_or_create, daemon=True)
    thread.start()


def show_streaming_tooltip(chunks: Iterator[str], w: int, h: int) -> str | None:
    """
    边接收边刷新弹窗，返回最终文本

    用户在中途关闭弹窗时停止接收并返回 None

    - 弹窗先于首个分块创建，用户立刻有反馈
    - 高度随内容增长，到 h 行封顶后靠内部滚动
    - 全程 persistent 语义：点击外部或按 Esc 关闭，并中断请求
    """
    updates: queue.Queue[str] = queue.Queue()
    window_ready = threading.Event()
    finished = threading.Event()
    cancelled = threading.Event()

    def safe_destroy(_event=None):
        """关闭弹窗，并通知接收循环停下来"""
        global _TOOLTIP_ROOT, _TOOLTIP_TEXT, _TOOLTIP_CLEANUP
        cancelled.set()
        cleanup, _TOOLTIP_CLEANUP = _TOOLTIP_CLEANUP, None
        if cleanup:
            cleanup()
        try:
            if _TOOLTIP_ROOT and _TOOLTIP_ROOT.winfo_exists():
                _TOOLTIP_ROOT.destroy()
        except tkinter.TclError:
            pass
        _TOOLTIP_ROOT = None
        _TOOLTIP_TEXT = None

    def drain() -> str | None:
        """取走队列中的全部文本，只留最后一条——中间的中间态没有显示价值"""
        latest = None
        while True:
            try:
                latest = updates.get_nowait()
            except queue.Empty:
                return latest

    def poll():
        """在 Tk 线程内刷新弹窗"""
        root, text_area = _TOOLTIP_ROOT, _TOOLTIP_TEXT
        if not root or not text_area or not root.winfo_exists():
            return

        latest = drain()
        if latest is not None:
            text_area.delete("1.0", tkinter.END)
            text_area.insert(tkinter.END, latest)
            _fit_tooltip_height(text_area, latest, w, h)
            text_area.see(tkinter.END)

        if not finished.is_set():
            root.after(STREAM_POLL_MS, poll)

    def create_and_run():
        global _TOOLTIP_ROOT, _TOOLTIP_TEXT, _TOOLTIP_CLEANUP

        x, y = pyautogui.position()

        if _TOOLTIP_ROOT and _TOOLTIP_TEXT and _TOOLTIP_ROOT.winfo_exists():
            # 复用已有窗口：清空内容、重绑关闭方式
            # 轮询回调交给该窗口自己的事件循环执行
            root, text_area = _TOOLTIP_ROOT, _TOOLTIP_TEXT
            if _TOOLTIP_CLEANUP:
                _TOOLTIP_CLEANUP()
            root.geometry(f"+{x+TOOLTIP_OFFSET_X}+{y+TOOLTIP_OFFSET_Y}")
            text_area.config(width=w, height=1)
            text_area.delete("1.0", tkinter.END)
            _TOOLTIP_CLEANUP = _attach_close_handlers(root, safe_destroy, "persistent")
            root.lift()
            window_ready.set()
            root.after(0, poll)
            return

        root, text_area = _create_tooltip_window(x, y, w, 1)
        _TOOLTIP_ROOT = root
        _TOOLTIP_TEXT = text_area
        _TOOLTIP_CLEANUP = _attach_close_handlers(root, safe_destroy, "persistent")

        window_ready.set()
        poll()
        root.mainloop()

    threading.Thread(target=create_and_run, daemon=True).start()
    # 等窗口就绪，避免失败时与随后的 show_tooltip 争夺全局窗口
    window_ready.wait(timeout=5)

    parts: list[str] = []
    failure: Exception | None = None
    try:
        print("-> 翻译中（流式）... ")
        for chunk in chunks:
            if cancelled.is_set():
                break
            parts.append(chunk)
            updates.put("".join(parts))
    except Exception as e:
        failure = e
    finally:
        finished.set()

    if cancelled.is_set():
        print("-> 翻译已中断")
        return None

    result_text = "".join(parts)
    if failure is not None:
        print(f"-> 翻译中断：{failure} ")
    elif result_text == "":
        print("-> 翻译失败")
    else:
        print("-> 翻译成功：\n" + result_text)

    return result_text


def show_startup_hint() -> None:
    """
    显示/更新程序运行提示框（灰底半透明，常驻屏幕右上角，可拖动）

    通过 Tkinter 窗口实现，无边框置顶显示
    """
    global _HINT_ROOT, _HINT_LABEL

    root = tkinter.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.attributes('-alpha', 0.80)  # 透明度 80%
    root.configure(bg='#303030')

    # 获取屏幕尺寸
    root.update_idletasks()
    screen_width = root.winfo_screenwidth()

    label = tkinter.Label(
        root,
        text="等待快捷键...",
        font=("Microsoft YaHei", 10, "bold"),
        bg='#303030',
        fg='white',
        width=16,
        anchor="center",
        padx=6,
        pady=8
    )
    label.pack()
    root.update_idletasks()

    # 固定窗口宽度，不让文本变化导致窗口伸缩
    win_w = label.winfo_reqwidth()

    # 赋值到全局，供 set_hint_message() 使用
    _HINT_ROOT = root
    _HINT_LABEL = label

    # 拖动功能
    drag_data = {"x": 0, "y": 0}

    def on_mouse_down(event):
        drag_data["x"] = event.x_root - root.winfo_x()
        drag_data["y"] = event.y_root - root.winfo_y()

    def on_mouse_move(event):
        root.geometry(f"+{event.x_root - drag_data['x']}+{event.y_root - drag_data['y']}")

    label.bind("<Button-1>", on_mouse_down)
    label.bind("<B1-Motion>", on_mouse_move)

    # 放在屏幕右上角
    root.geometry(f"+{screen_width - win_w - 250}+{30}")
    root.mainloop()
    

def main() -> None:
    print("-> 翻译热键触发 ", end="")
    set_hint_message("翻译中...")

    selected = get_selected_text()
    if selected == "":
        print("-> 未获取到选中文本，翻译取消")
        set_hint_message("未获取到文本")
    else:
        print("-> 已获取选中文本：\n" + selected)
        if STREAM:
            # 流式：内容边到边显示；返回 None 表示用户中途关掉了弹窗
            translation = show_streaming_tooltip(
                translate_stream(selected), RESULT_MAX_WIDTH, RESULT_MAX_HEIGHT
            )
            if translation == "":
                show_tooltip("翻译失败", 15, 1, "timed")
        else:
            translation = translate_with_llm(selected)
            if translation == "":
                print("-> 翻译失败")
                show_tooltip("翻译失败", 15, 1, "timed")
            else:
                print("-> 翻译成功：\n" + translation)
                show_tooltip(translation, RESULT_MAX_WIDTH, RESULT_MAX_HEIGHT, "persistent")
                print(" -> 结果已显示")

    print("========\n\n等待快捷键... ", end="")
    set_hint_message("等待快捷键...")


if __name__ == "__main__":
    # 启动提示框（守护线程，程序退出时自动销毁）
    threading.Thread(target=show_startup_hint, daemon=True).start()

    # 仅一次，输出提示信息
    print("========\n等待快捷键... ", end="")

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()
