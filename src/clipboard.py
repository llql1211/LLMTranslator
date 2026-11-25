"""通过模拟 Ctrl+C 获取选中文本（依赖通过参数传入，便于测试）。"""

from __future__ import annotations

from collections.abc import Callable


def get_selected_text(
    *,
    controller,
    kb,
    clipboard,
    restore: bool,
    sleep: Callable[[float], None],
    clean: Callable[[str], str],
) -> str:
    """
    模拟 Ctrl+C 复制选中文本并清洗

    报错返回空串；无论成败都松开修饰键，并按配置恢复原剪贴板内容
    """
    old_clipboard = clipboard.paste()
    clipboard.copy('')
    sleep(0.03)  # 等待剪切板被清空

    try:
        # 先释放热键修饰键（Ctrl+Shift），确保键盘状态干净
        controller.release(kb.Key.ctrl)
        controller.release(kb.Key.shift)
        sleep(0.02)

        # 使用 pynput 模拟 Ctrl+C
        controller.press(kb.Key.ctrl)
        controller.press('c')
        controller.release('c')
        controller.release(kb.Key.ctrl)
        sleep(0.05)

        return clean(clipboard.paste())
    except Exception as e:
        print(f"-> 未获取选中文本，模拟 Ctrl+C 失败: {e} ")
        return ""
    finally:
        # 显式释放所有修饰键
        controller.release(kb.Key.ctrl)
        controller.release(kb.Key.shift)
        controller.release('c')

        if restore:
            clipboard.copy(old_clipboard)
