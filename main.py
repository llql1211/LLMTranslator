import threading
import time
import pyautogui
from pynput import keyboard
import pyperclip
import re
import requests
import signal
import sys
import tkinter

# ================
# 用户设置
# ================

# Ollama API 配置
OLLAMA_URL = "http://localhost:11434/api/generate"
# 模型名称（建议在末尾加上 ":latest"）
MODEL_NAME = "HY-MT1.5-1.8B-Q8_0:latest"
# 目标语言
TARGET_LANG = "Chinese"
# Prompt（注意：此 Prompt 专门适配模型 "HY-MT1.5-1.8B-Q8_0"，其他模型可能需要调整）
PROMPT_TEMPLATE = f"<｜hy_begin▁of▁sentence｜>你是一个翻译助手，专门将输入的文本翻译成{TARGET_LANG}。<｜hy_place▁holder▁no▁3｜><｜hy_User｜>{{input_text}}<｜hy_Assistant｜>"
# 翻译与退出热键
HOTKEY_TRANSLATE = '<ctrl>+<shift>+e'
HOTKEY_QUIT = '<ctrl>+<shift>+q'
# 是否在获取选中文本后恢复剪切板内容
RESTORE_CLIPBOARD = False

# 若要修改请求体 payload 内容，请 Ctrl+F 搜索 payload

# ================
# 默认配置项
# ================

# 文本框背景颜色
BACKGROUND_COLOR = '#FFFFE0'
# 文本框相对鼠标向右下偏移量（像素）
TOOLTIP_OFFSET_X = 20
TOOLTIP_OFFSET_Y = 20
# 翻译结果文本框最大宽度（字符）/高度（行）
RESULT_MAX_WIDTH = 30
RESULT_MAX_HEIGHT = 8
# 提示信息显示时间（ms）
TOOLTIP_DURATION = 1500

# ================
# Main Code
# ================

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
    调用 Ollama API 翻译
    
    报错返回空串
    """
    prompt = PROMPT_TEMPLATE.format(input_text=text)
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False
    }
    result_text = ""

    try:
        print("-> 翻译中... ", end="")
        response = requests.post(OLLAMA_URL, json=payload, timeout=30)
        response.raise_for_status()  # 检查 HTTP 响应状态码
        result = response.json()
        if "response" in result:
            result_text = result["response"].strip()
        else:
            print("-> 翻译失败：API 相应中缺少 'response' 字段 ")
    except Exception as e:
        print("-> 翻译失败：{e} ")

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
