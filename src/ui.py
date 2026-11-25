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

from logger import error, info, warn

STREAM_POLL_MS = 50


def _blend_color(base: str, other: str, ratio: float) -> str:
    """把两种 #RRGGBB 颜色按比例混合，ratio 为 other 所占份额"""
    try:
        b = [int(base[i:i + 2], 16) for i in (1, 3, 5)]
        o = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    except (ValueError, IndexError):
        return base
    return "#" + "".join(f"{round(x + (y - x) * ratio):02X}" for x, y in zip(b, o))


def normalize_result(text: str) -> str:
    """
    整理模型输出，让结果弹窗里的排版更干净

    - 统一换行符，去掉每行首尾空白
    - 连续空行压成一个，保留段落结构
    - 去掉整体首尾空行
    """
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    cleaned: list[str] = []
    blank = False
    for line in lines:
        if line.strip():
            cleaned.append(line)
            blank = False
        elif not blank:
            cleaned.append("")
            blank = True
    while cleaned and not cleaned[0]:
        cleaned.pop(0)
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return "\n".join(cleaned)


@dataclass(frozen=True)
class UiSettings:
    """弹窗外观与行为所需的配置快照"""

    background_color: str
    text_color: str
    offset_x: int
    offset_y: int
    duration_ms: int
    font_family: str
    font_size: int


# 全局 Tkinter 窗口，复用避免重复创建
_TOOLTIP_ROOT = None
_TOOLTIP_TEXT = None

# 当前弹窗关闭方式的清理函数（停鼠标监听、取消定时器）
_TOOLTIP_CLEANUP: Callable[[], None] | None = None

# 右上角常驻提示框
_HINT_ROOT = None
_HINT_LABEL = None
_HINT_ACCENT = None
_HINT_THEME = "light"

# 主题 → 状态 → (底色, 文字色, 左侧强调条颜色)
# 浅色模式统一白底，靠文字色与左侧强调条区分状态；深色模式沿用原有的深色配色
_HINT_STYLES = {
    "light": {
        "idle": ("#FFFFFF", "#24292F", "#2E7D32"),
        "busy": ("#FFFFFF", "#24292F", "#1976D2"),
        "error": ("#FFFFFF", "#B3261E", "#D32F2F"),
        "exit": ("#FFFFFF", "#6B7280", "#9CA3AF"),
    },
    "dark": {
        "idle": ("#2B3038", "#F0F2F5", "#66BB6A"),
        "busy": ("#1B3A4B", "#EAF6FF", "#29B6F6"),
        "error": ("#452A2A", "#FFE9E9", "#EF5350"),
        "exit": ("#33383F", "#E0E0E0", "#90A4AE"),
    },
}


def _hint_style(msg: str, theme: str | None = None) -> tuple[str, str, str]:
    """根据提示文案与主题挑选配色，让等待/翻译/出错/退出一眼可辨"""
    palette = _HINT_STYLES.get(theme or _HINT_THEME, _HINT_STYLES["light"])
    # 先判错误：「翻译中断」也含「翻译中」，不能误判成忙碌
    if any(key in msg for key in ("失败", "未获取", "中断", "错误")):
        return palette["error"]
    if "翻译中" in msg:
        return palette["busy"]
    if "退出" in msg:
        return palette["exit"]
    return palette["idle"]


def _apply_hint_message(msg: str) -> None:
    """在 Tk 线程内更新提示框的文本与配色"""
    bg, fg, accent = _hint_style(msg)
    try:
        if _HINT_ROOT:
            _HINT_ROOT.configure(bg=bg)
        if _HINT_LABEL:
            _HINT_LABEL.config(text=msg, bg=bg, fg=fg)
        if _HINT_ACCENT:
            _HINT_ACCENT.config(bg=accent)
    except tkinter.TclError:
        pass


def set_hint_message(msg: str) -> None:
    """线程安全地更新右上角常驻提示框的文本与状态配色"""
    root = _HINT_ROOT
    if root and root.winfo_exists():
        root.after(0, lambda: _apply_hint_message(msg))


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

    # 边框与选中高亮都从主题色推导，浅色/深色背景都能自动适配
    border = _blend_color(settings.background_color, settings.text_color, 0.3)
    selection = _blend_color(settings.background_color, settings.text_color, 0.35)

    text_area = tk.Text(
        root,
        wrap=tk.WORD,
        font=(settings.font_family, settings.font_size),
        width=w,
        height=h,
        relief=tk.FLAT,
        bg=settings.background_color,
        fg=settings.text_color,
        # 文本光标跟随文字颜色，深色背景下不会留下一道刺眼的黑竖线
        insertbackground=settings.text_color,
        bd=0,
        padx=10,
        pady=8,
        # 段前/行间/段后留白，避免译文挤成一片
        spacing1=2,
        spacing2=3,
        spacing3=2,
        highlightthickness=1,
        highlightbackground=border,
        highlightcolor=border,
        selectbackground=selection,
        selectforeground=settings.text_color,
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
    text = normalize_result(text)

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
            display = normalize_result(latest)
            text_area.delete("1.0", tkinter.END)
            text_area.insert(tkinter.END, display)
            fit_tooltip_height(text_area, display, w, h)
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
        info("开始流式接收译文")
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
        warn("翻译已中断（用户关闭弹窗）")
        return None

    result_text = normalize_result("".join(parts))
    if failure is not None:
        error(f"翻译中断：{failure}")
    elif result_text == "":
        warn("流式响应未返回任何内容")
    else:
        info(f"译文接收完成，共 {len(result_text)} 字符")

    return result_text


def show_startup_hint(theme: str = "light") -> None:
    """
    显示常驻右上角的状态提示框（无边框置顶、半透明、可拖动）

    左侧的强调条会随状态变色：绿色等待、蓝色翻译中、红色出错、灰色退出；
    浅色模式为白底深字，深色模式为深色底浅色字
    """
    global _HINT_ROOT, _HINT_LABEL, _HINT_ACCENT, _HINT_THEME

    _HINT_THEME = theme if theme in _HINT_STYLES else "light"
    bg, fg, accent_color = _hint_style("等待快捷键...", _HINT_THEME)

    root = tkinter.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.attributes('-alpha', 0.85)
    root.configure(bg=bg)

    root.update_idletasks()
    screen_width = root.winfo_screenwidth()

    accent = tkinter.Frame(root, bg=accent_color, width=4)
    accent.pack(side="left", fill="y", padx=(8, 0), pady=8)

    label = tkinter.Label(
        root,
        text="等待快捷键...",
        font=("Microsoft YaHei", 11, "bold"),
        bg=bg,
        fg=fg,
        width=16,
        anchor="center",
        padx=8,
        pady=9,
    )
    label.pack(side="left", padx=(8, 10))
    root.update_idletasks()

    # 固定窗口宽度，不让文本变化导致窗口伸缩
    win_w = root.winfo_reqwidth()

    # 赋值到全局，供 set_hint_message() 使用
    _HINT_ROOT = root
    _HINT_LABEL = label
    _HINT_ACCENT = accent

    # 拖动功能：强调条与文字区域都可以拖动
    drag_data = {"x": 0, "y": 0}

    def on_mouse_down(event):
        drag_data["x"] = event.x_root - root.winfo_x()
        drag_data["y"] = event.y_root - root.winfo_y()

    def on_mouse_move(event):
        root.geometry(f"+{event.x_root - drag_data['x']}+{event.y_root - drag_data['y']}")

    for widget in (label, accent):
        widget.bind("<Button-1>", on_mouse_down)
        widget.bind("<B1-Motion>", on_mouse_move)

    # 放在屏幕右上角
    root.geometry(f"+{screen_width - win_w - 250}+{30}")
    root.mainloop()
