"""Tkinter 弹窗、右上角提示框与流式增量显示。"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal

import tkinter

import pyautogui
from pynput import mouse

STREAM_POLL_MS = 50


@dataclass(frozen=True)
class UiSettings:
    """弹窗外观与行为所需的配置快照"""

    background_color: str
    text_color: str
    offset_x: int
    offset_y: int
    duration_ms: int


# 全局 Tkinter 窗口，复用避免重复创建
_TOOLTIP_ROOT = None
_TOOLTIP_TEXT = None

# 当前弹窗关闭方式的清理函数（停鼠标监听、取消定时器）
_TOOLTIP_CLEANUP: Callable[[], None] | None = None

# 右上角常驻提示框
_HINT_ROOT = None
_HINT_LABEL = None


def set_hint_message(msg: str) -> None:
    """线程安全地更新右上角常驻提示框的文本"""
    root = _HINT_ROOT
    if root and root.winfo_exists():
        root.after(0, lambda: _HINT_LABEL.config(text=msg) if _HINT_LABEL else None)


def create_tooltip_window(
    x: int, y: int, w: int, h: int, settings: UiSettings, tk=tkinter
) -> tuple:
    """
    在鼠标位置创建无边框置顶弹窗

    返回 (root, text_area)，须在随后运行该 root 的 mainloop 的线程中调用
    """
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.configure(bg=settings.background_color)
    root.geometry(f"+{x + settings.offset_x}+{y + settings.offset_y}")

    text_area = tk.Text(
        root,
        wrap=tk.WORD,
        font=("Microsoft YaHei", 10),
        width=w,
        height=h,
        relief=tk.FLAT,
        bg=settings.background_color,
        fg=settings.text_color,
        # 文本光标跟随文字颜色，深色背景下不会留下一道刺眼的黑竖线
        insertbackground=settings.text_color,
        bd=0,
        padx=5,
        pady=5
    )
    text_area.pack(fill=tk.BOTH, expand=True)

    return root, text_area


def attach_close_handlers(
    root,
    on_close: Callable[[], None],
    mode: Literal["timed", "persistent"],
    settings: UiSettings,
) -> Callable[[], None]:
    """
    给弹窗绑定关闭方式，返回清理函数

    - "timed"：duration_ms 毫秒后自动关闭
    - "persistent"：点击弹窗外部或按 Esc 关闭

    销毁窗口前必须先调用清理函数
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
        holder["timer"] = root.after(settings.duration_ms, on_close)
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


def fit_tooltip_height(text_area, text: str, w: int, max_height: int) -> None:
    """按内容估算高度，到 max_height 行封顶，超出部分靠内部滚动查看"""
    text_area.config(height=max(1, min(max_height, estimate_display_lines(text, w))))


def show_tooltip(
    text: str,
    w: int,
    h: int,
    mode: Literal["timed", "persistent"],
    settings: UiSettings,
) -> None:
    """
    在鼠标右下角显示无边框矩形文本框

    - w: 字符, h: 行
    - "timed" 定时关闭，"persistent" 点击外部或按 Esc 关闭
    - 不抢焦点，点击弹窗内部可选中文本，鼠标悬停可滚动
    """
    global _TOOLTIP_ROOT, _TOOLTIP_TEXT, _TOOLTIP_CLEANUP

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
            root.geometry(f"+{x + settings.offset_x}+{y + settings.offset_y}")
            text_area.config(height=h, width=w)
            text_area.delete(1.0, tkinter.END)
            text_area.insert(tkinter.END, text)
            _TOOLTIP_CLEANUP = attach_close_handlers(root, safe_destroy, mode, settings)
            root.lift()
            return

        # 首次创建窗口
        root, text_area = create_tooltip_window(x, y, w, h, settings)
        text_area.insert(tkinter.END, text)

        _TOOLTIP_ROOT = root
        _TOOLTIP_TEXT = text_area
        _TOOLTIP_CLEANUP = attach_close_handlers(root, safe_destroy, mode, settings)

        root.mainloop()

    # 使用线程避免阻塞
    thread = threading.Thread(target=update_or_create, daemon=True)
    thread.start()


def show_streaming_tooltip(
    chunks: Iterator[str], w: int, h: int, settings: UiSettings
) -> str | None:
    """
    边接收边刷新弹窗，返回最终文本

    用户在中途关闭弹窗时停止接收并返回 None

    - 弹窗先于首个分块创建，用户立刻有反馈
    - 高度随内容增长，到 h 行封顶后靠内部滚动
    - 全程 persistent 语义：点击外部或按 Esc 关闭，并中断请求
    """
    global _TOOLTIP_ROOT, _TOOLTIP_TEXT, _TOOLTIP_CLEANUP

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
            fit_tooltip_height(text_area, latest, w, h)
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
            root.geometry(f"+{x + settings.offset_x}+{y + settings.offset_y}")
            text_area.config(width=w, height=1)
            text_area.delete("1.0", tkinter.END)
            _TOOLTIP_CLEANUP = attach_close_handlers(root, safe_destroy, "persistent", settings)
            root.lift()
            window_ready.set()
            root.after(0, poll)
            return

        root, text_area = create_tooltip_window(x, y, w, 1, settings)
        _TOOLTIP_ROOT = root
        _TOOLTIP_TEXT = text_area
        _TOOLTIP_CLEANUP = attach_close_handlers(root, safe_destroy, "persistent", settings)

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
