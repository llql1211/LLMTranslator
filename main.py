import json
import os
import re
import signal
import sys
import threading
import time
import tkinter

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

def handler(signum, frame):
    '''将 handler 函数设置为空，忽略 Ctrl+C 中断信号'''
    ...
signal.signal(signal.SIGINT, handler)

def on_activate():
    '''翻译热键触发时的回调函数'''
    main()

def on_quit():
    '''退出热键触发时的回调函数'''
    print("\n退出程序")
    show_tooltip("程序已退出", 15, 1, "timed")
    sys.exit(0)

# 绑定热键与响应函数
hotkeys = {
    HOTKEY_TRANSLATE: on_activate,
    HOTKEY_QUIT: on_quit
}

def clean_english_text(text):
    """
    清洗 ASCII 文本

    将连续空格替换为单个空格，根据上下文添加句号，同时保留原换行格式
    """
    lines = [line.strip() for line in text.splitlines()]
    punctuation = {'.', '?', '!'}
    cleaned = ""

    # 若当前行以小写字母开头，且上一行不以标点结尾，则直接合并
    # 若当前行以大写字母开头，且上一行末尾无标点，默认添加句号
    for i in range(len(lines)):
        current = lines[i]
        if not cleaned:
            cleaned = current
        elif not current:
            cleaned += '\n'
        elif current[0].islower() and (cleaned[-1] not in punctuation):
            cleaned = cleaned + ' ' + current
        elif current[0].isupper() and (cleaned[-1] not in punctuation):
            cleaned += '.\n' + current
        else:
            cleaned = cleaned + '\n' + current

    # 正则表达式，将连续的空格或制表符替换为单个空格
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    return cleaned.strip()

def get_selected_text():
    """
    模拟 Ctrl+C 获取当前选中文本
    
    报错返回空串
    """
    old_clipboard = pyperclip.paste()
    pyperclip.copy('')
    time.sleep(0.1)  # 等待剪切板被清空

    try:
        # 使用 pynput 模拟 Ctrl+C
        KB_CONTR.release(keyboard.Key.shift)  # 松开 Shift 键，防止与 Ctrl+C 冲突为 Ctrl+Shift+C
        KB_CONTR.press(keyboard.Key.ctrl)
        KB_CONTR.press('c')
        KB_CONTR.release('c')
        KB_CONTR.release(keyboard.Key.ctrl)
        time.sleep(0.2)
        
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

def translate_with_llm(text):
    """
    调用 LLM API 翻译
    - api_key 为空 → Ollama 原生格式（/api/generate）
    - api_key 非空 → OpenAI 兼容格式（/v1/chat/completions）
    报错返回空串
    """
    prompt = PROMPT_TEMPLATE.format(input_text=text)

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

def show_tooltip(text, w, h, mode):
    """
    在鼠标右下角显示无边框矩形文本框（非阻塞）

    w：字符，h：行，

    mode: "timed" 5秒后自动关闭，"persistent" 长期显示

    点击外部或按下 ESC 关闭
    """
    def run():
        x, y = pyautogui.position()  # 获取光标位置
        
        root = tkinter.Tk()
        root.overrideredirect(True)  # 移除标题栏和边框
        root.attributes('-topmost', True)  # 置顶窗口
        root.configure(bg=BACKGROUND_COLOR)
        root.geometry(f"+{x+TOOLTIP_OFFSET_X}+{y+TOOLTIP_OFFSET_Y}")  # 向右下方偏移
        
        text_area = tkinter.Text(
            root,
            wrap=tkinter.WORD,  # 按单词换行，避免单词被切断
            font=("Microsoft YaHei", 10),
            width=w,  # 宽度（字符数）
            height=h,  # 高度（行数）
            relief=tkinter.FLAT,
            bg=BACKGROUND_COLOR,
            fg='black',
            insertbackground='black',  # 光标颜色
            bd=0,  # 去掉边框
            padx=5,  # 内边距
            pady=5
        )
        text_area.pack(fill=tkinter.BOTH, expand=True)
        text_area.insert(tkinter.END, text)

        timer_id = None
        
        # 安全销毁函数：取消定时器（若存在）并销毁窗口，避免重复销毁
        def safe_destroy():
            nonlocal timer_id
            try:
                if root.winfo_exists():
                    if timer_id:
                        root.after_cancel(timer_id)
                        timer_id = None
                    root.destroy()
            except tkinter.TclError:
                pass  # 窗口已不存在，忽略错误

        # 设置定时器，"persistent" 无需设置
        if mode == "timed":
            timer_id = root.after(TOOLTIP_DURATION, safe_destroy)

        # 点击外部区域（失去焦点）时关闭（延迟检查，避免误关）
        def on_focus_out(event):
            root.after(100, lambda: safe_destroy() if not root.focus_get() else None)

        # 失去焦点时关闭
        root.bind("<FocusOut>", on_focus_out)
        # 按下 ESC 键时关闭
        root.bind("<Escape>", lambda e: safe_destroy())

        root.focus_force()  # 让窗口获得焦点
        root.mainloop()
    # daemon=False 表示主线程结束后等待子线程结束
    thread = threading.Thread(target=run, daemon=False)
    thread.start()

def main():
    print("-> 翻译热键触发 ", end="")

    selected = get_selected_text()
    if selected == "":
        print("-> 未获取到选中文本，翻译取消")
        show_tooltip("未获取选中文本", 15, 1, "timed")
    else:
        print("-> 已获取选中文本：\n" + selected)

        show_tooltip("正在翻译...", 15, 1, "timed")
        translation = translate_with_llm(selected)
        if translation == "":
            print("-> 翻译失败")
            show_tooltip("翻译失败", 15, 1, "timed")
        else:
            print("-> 翻译成功：\n" + translation)
            show_tooltip(translation, RESULT_MAX_WIDTH, RESULT_MAX_HEIGHT, "persistent")
            print(" -> 结果已显示")

    print("========\n等待快捷键... ", end="")
    # # 此处输出提示信息会覆盖翻译结果
    # show_tooltip("等待快捷键...", 15, 1, "timed")

if __name__ == "__main__":
    with keyboard.GlobalHotKeys(hotkeys) as h:
        # 仅一次，输出提示信息
        print("========\n等待快捷键... ", end="")
        show_tooltip("等待快捷键...", 15, 1, "timed")
        h.join()
