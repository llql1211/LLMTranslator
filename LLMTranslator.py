# 使用部署于 Ollama 的本地大模型，将选中文本翻译成特定语言 
# 平台：Windows 可用，Linux 未知
# 已知 bug：从第二次翻译开始，热键注册异常。翻译热键仅需要 Shift 键，且要按 2 次；显示“等待按键中...”时并未进入监听状态
# 计划：将简短的提示信息使用文本框置顶显示

import time
import pyperclip
import requests
import tkinter
import pyautogui
import signal
from pynput import keyboard
import sys
import re

# ================
# 用户设置
# ================

# Ollama API 配置
OLLAMA_URL = "http://localhost:11434/api/generate"
# 模型名称（可能需要加上末尾的 ":latest"）
MODEL_NAME = "HY-MT1.5-1.8B-Q8_0:latest"
# 目标语言
TARGET_LANG = "Chinese"
# 翻译与退出热键
HOTKEY_TRANSLATE = '<ctrl>+<shift>+e'
HOTKEY_QUIT = '<ctrl>+<shift>+q'
# 是否在获取选中文本后恢复剪切板内容
RESTORE_CLIPBOARD = False

# ================
# 默认配置项
# ================

PROMPT_TEMPLATE = f"<｜hy_begin▁of▁sentence｜>你是一个翻译助手，专门将输入的文本翻译成{TARGET_LANG}。<｜hy_place▁holder▁no▁3｜><｜hy_User｜>{{input_text}}<｜hy_Assistant｜>"

# ================
# main code
# ================

# 从 keyboard 创建 Controller 实例，用于模拟按键操作
KB_CONTR = keyboard.Controller()

def handler(signum, frame):
    '''将 handler 函数设置为空，忽略 Ctrl+C 中断信号'''
    ...
signal.signal(signal.SIGINT, handler)

def on_activate():
    '''翻译热键触发时的回调函数'''
    # # 释放可能卡住的修饰键
    # KB_CONTR.release(keyboard.Key.ctrl)
    # KB_CONTR.release(keyboard.Key.shift)
    # KB_CONTR.release(keyboard.Key.alt)
    print("-> 翻译热键触发 ", end="")
    main()
    print("========\n等待快捷键... ", end="")

def on_quit():
    '''退出热键触发时的回调函数'''
    print("\n退出程序")
    sys.exit(0)

# 将热键与响应函数绑定
hotkeys = {
    HOTKEY_TRANSLATE: on_activate,
    HOTKEY_QUIT: on_quit
}

def clean_english_text(text):
    """
    清洗 ASCII 文本
    
    将连续空格替换为单个空格，根据上下文添加句号，保留原换行格式
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

def get_selected_text_windows():
    """模拟 Ctrl+C 获取当前选中文本"""
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
        print("-> 已获取选中文本：\n" + new_text)
        return new_text
    except Exception as e:
        print(f"-> 未获取选中文本，模拟 Ctrl+C 失败: {e}")
        return ""
    finally:
        # # 显式释放所有修饰键
        # KB_CONTR.release(keyboard.Key.ctrl)
        # KB_CONTR.release(keyboard.Key.shift)
        # KB_CONTR.release('c')
        # 恢复原剪贴板内容（若设置了 RESTORE_CLIPBOARD）
        if RESTORE_CLIPBOARD:
            pyperclip.copy(old_clipboard)

def translate_with_llm(text):
    """调用 Ollama API 翻译"""
    # 若为空串，直接返回
    if not text:
        return ""

    prompt = PROMPT_TEMPLATE.format(input_text=text)
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False
    }

    try:
        print("-> 翻译中... ", end="")
        response = requests.post(OLLAMA_URL, json=payload, timeout=30)
        response.raise_for_status()  # 检查 HTTP 响应状态码
        result = response.json()
        result_text = result.get("response", "-> 翻译失败 ")  # 找不到 "response" 字段时返回 "翻译失败"
        print("-> 翻译成功：\n" + result_text)
        return result_text
    except Exception as e:
        return f"-> 翻译失败：{e}"

def show_translation_popup(text):
    """在鼠标右下角显示无边框矩形文本框"""
    x, y = pyautogui.position()
    
    root = tkinter.Tk()
    root.overrideredirect(True)  # 移除标题栏和边框
    root.attributes('-topmost', True)  # 置顶窗口
    root.configure(bg='#FFFFE0')
    root.geometry(f"+{x+20}+{y+20}")  # 向右下方偏移 20 像素
    text_area = tkinter.Text(
        root,
        wrap=tkinter.WORD,  # 按单词换行，避免单词被切断
        font=("Microsoft YaHei", 10),
        width=30,  # 宽度（字符数）
        height=8,  # 高度（行数）
        relief=tkinter.FLAT,
        bg='#FFFFE0',
        fg='black',
        insertbackground='black',  # 光标颜色
        bd=0,  # 去掉边框
        padx=5,  # 内边距
        pady=5
    )
    text_area.pack(fill=tkinter.BOTH, expand=True)
    
    # 插入翻译文本
    text_area.insert(tkinter.END, text)
    print(" -> 结果已显示")

    # 绑定事件：点击外部（失去焦点）时关闭窗口
    def on_focus_out(event):
        root.after(100, lambda: root.destroy() if not root.focus_get() else None)  # 延时 100ms 检查是否真正失去焦点
    root.bind("<FocusOut>", on_focus_out)
    # 绑定事件：按 ESC 键关闭
    root.bind("<Escape>", lambda: root.destroy())
    # 让窗口获得焦点
    root.focus_force()
    # 启动 Tkinter 事件循环
    root.mainloop()

def main():
    selected = get_selected_text_windows()
    if not selected:
        print("-> 未获取到选中文本，翻译取消 ")
        return
    translation = translate_with_llm(selected)
    show_translation_popup(translation)

if __name__ == "__main__":
    with keyboard.GlobalHotKeys(hotkeys) as h:
        print("========\n等待快捷键... ", end="")  # 仅输出一次
        h.join()
