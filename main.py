from __future__ import annotations

import json
import os
import re
import signal
import threading
import time
import tkinter
from typing import Literal

import pyautogui
from pynput import keyboard
import pyperclip
import requests


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE_DIR, "config.json"), "r", encoding="utf-8") as f:
    config = json.load(f)

API_BASE_URL = config["api"]["base_url"]
MODEL_NAME = config["api"]["model_name"]
API_KEY = config["api"]["api_key"]

TARGET_LANG = config["translation"]["target_lang"]
PROMPT_TEMPLATE = config["translation"]["prompt_template"]

HOTKEY_TRANSLATE = config["hotkeys"]["translate"]
HOTKEY_QUIT = config["hotkeys"]["quit"]

TOOLTIP_DURATION = config["tooltip"]["duration_ms"]
BACKGROUND_COLOR = config["tooltip"]["background_color"]
TOOLTIP_OFFSET_X = config["tooltip"]["offset_x"]
TOOLTIP_OFFSET_Y = config["tooltip"]["offset_y"]
RESULT_MAX_WIDTH = config["tooltip"]["result_max_width"]
RESULT_MAX_HEIGHT = config["tooltip"]["result_max_height"]

RESTORE_CLIPBOARD = config["restore_clipboard"]


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
    """解析 '<ctrl>+<shift>+e' 格式的热键，返回 (修饰键集合, 主键)"""
    parts = spec.lower().split("+")
    mods: set[str] = set()
    key_char = ""
    for p in parts:
        p = p.strip("<>")
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


def translate_with_llm(text: str) -> str:
    """
    调用 LLM API 翻译

    - api_key 为空 → Ollama 原生格式（/api/generate）
    - api_key 非空 → OpenAI 兼容格式（/v1/chat/completions）

    报错返回空串
    """
    prompt = PROMPT_TEMPLATE.format(target_lang=TARGET_LANG, input_text=text)

    if API_KEY:
        # OpenAI 兼容格式
        chat_url = API_BASE_URL.rstrip("/")
        if not chat_url.endswith("/chat/completions"):
            chat_url = chat_url.rstrip("/v1") + "/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False
        }
        do_request = lambda: requests.post(chat_url, json=payload, headers=headers, timeout=30)
    else:
        # Ollama 原生格式
        payload = {
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False
        }
        do_request = lambda: requests.post(API_BASE_URL, json=payload, timeout=30)

    result_text = ""
    try:
        print("-> 翻译中... ", end="")
        response = do_request()
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


# 全局 Tkinter 窗口，复用避免重复创建
_TOOLTIP_ROOT = None
_TOOLTIP_TEXT = None
_TOOLTIP_TIMER_ID = None

# 右上角常驻提示框
_HINT_ROOT = None
_HINT_LABEL = None


def set_hint_message(msg: str) -> None:
    """线程安全地更新右上角常驻提示框的文本"""
    root = _HINT_ROOT
    if root and root.winfo_exists():
        root.after(0, lambda: _HINT_LABEL.config(text=msg) if _HINT_LABEL else None)


def show_tooltip(text: str, w: int, h: int, mode: Literal["timed", "persistent"]) -> None:
    """
    在鼠标右下角显示无边框矩形文本框（非阻塞）

    w：字符，h：行，

    mode: "timed" 5秒后自动关闭，"persistent" 长期显示

    点击外部或按下 ESC 关闭
    """
    def safe_destroy(_event=None):
        """安全销毁窗口（接受可选 event 参数用于 bind 回调）"""
        global _TOOLTIP_ROOT, _TOOLTIP_TEXT, _TOOLTIP_TIMER_ID
        try:
            if _TOOLTIP_ROOT and _TOOLTIP_ROOT.winfo_exists():
                if _TOOLTIP_TIMER_ID:
                    _TOOLTIP_ROOT.after_cancel(_TOOLTIP_TIMER_ID)
                    _TOOLTIP_TIMER_ID = None
                _TOOLTIP_ROOT.destroy()
        except tkinter.TclError:
            pass
        finally:
            _TOOLTIP_ROOT = None
            _TOOLTIP_TEXT = None

    def update_or_create():
        global _TOOLTIP_ROOT, _TOOLTIP_TEXT, _TOOLTIP_TIMER_ID

        x, y = pyautogui.position()

        if _TOOLTIP_TEXT and _TOOLTIP_ROOT and _TOOLTIP_ROOT.winfo_exists():
            # 复用已有窗口：移动位置、更新文本
            _TOOLTIP_ROOT.geometry(f"+{x+TOOLTIP_OFFSET_X}+{y+TOOLTIP_OFFSET_Y}")
            _TOOLTIP_TEXT.config(height=h, width=w)
            _TOOLTIP_TEXT.delete(1.0, tkinter.END)
            _TOOLTIP_TEXT.insert(tkinter.END, text)

            if _TOOLTIP_TIMER_ID:
                _TOOLTIP_ROOT.after_cancel(_TOOLTIP_TIMER_ID)
                _TOOLTIP_TIMER_ID = None
            if mode == "timed":
                _TOOLTIP_TIMER_ID = _TOOLTIP_ROOT.after(TOOLTIP_DURATION, safe_destroy)

            _TOOLTIP_ROOT.lift()
            _TOOLTIP_ROOT.focus_force()
            return

        # 首次创建窗口
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
        text_area.insert(tkinter.END, text)

        _TOOLTIP_ROOT = root
        _TOOLTIP_TEXT = text_area
        _TOOLTIP_TIMER_ID = None

        # 定时关闭
        if mode == "timed":
            _TOOLTIP_TIMER_ID = root.after(TOOLTIP_DURATION, safe_destroy)

        # 失去焦点关闭
        root.bind("<FocusOut>", safe_destroy)
        root.bind("<Escape>", lambda _e: safe_destroy())

        root.focus_force()
        root.mainloop()

    # 使用线程避免阻塞
    thread = threading.Thread(target=update_or_create, daemon=True)
    thread.start()


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
