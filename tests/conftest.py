"""
pytest 公共夹具

main.py 在导入时就会读取配置，因此必须在任何测试模块导入 main 之前
先准备好一份临时配置，并用 LLMTRANSLATOR_CONFIG 指向它。
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CONFIG_ENV_VAR = "LLMTRANSLATOR_CONFIG"

# 测试用配置，字段含义见 data/config.example.toml
BASE_CONFIG_VALUES: dict[str, object] = {
    "base_url": "http://localhost:11434/api/generate",
    "api_key": "",
    "model_name": "test-model",
    "target_lang": "Chinese",
    "prompt_template": "把 {input_text} 翻译成 {target_lang}",
    "hotkey_translate": "<ctrl>+<shift>+e",
    "hotkey_quit": "<ctrl>+<shift>+q",
    "tooltip_background_color": "#FFFFE0",
    "tooltip_text_color": "#000000",
    "tooltip_offset_x": 20,
    "tooltip_offset_y": 20,
    "tooltip_result_max_width": 30,
    "tooltip_result_max_height": 8,
    "tooltip_duration_ms": 1500,
    "restore_clipboard": False,
    # 默认关，需要验证流式分支的用例自行打开
    "stream": False,
}

# 生成参数不在此列：不写即不发送，需要时由用例通过 render_toml() 显式传入
# 传入该哨兵值表示「该键不出现在配置中」
MISSING = object()


def render_toml(**overrides) -> str:
    """把配置渲染成 TOML 文本；值为 MISSING 的键会被省略，用于模拟「未配置」"""
    values = {**BASE_CONFIG_VALUES, **overrides}
    lines = []
    for key, value in values.items():
        if value is MISSING:
            continue
        if isinstance(value, bool):
            lines.append(f"{key} = {str(value).lower()}")
        elif isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        else:
            lines.append(f"{key} = {value}")
    return "\n".join(lines) + "\n"


DEFAULT_CONFIG = render_toml()

_TMP_DIR = Path(tempfile.mkdtemp(prefix="llmtranslator-tests-"))
_SESSION_CONFIG = _TMP_DIR / "config.toml"
_SESSION_CONFIG.write_text(DEFAULT_CONFIG, encoding="utf-8")
os.environ[CONFIG_ENV_VAR] = str(_SESSION_CONFIG)


@pytest.fixture(scope="session", autouse=True)
def _cleanup_tmp_dir():
    """会话结束后清理临时配置目录"""
    yield
    shutil.rmtree(_TMP_DIR, ignore_errors=True)


@pytest.fixture
def app():
    """导入 main 模块（此时配置已由本文件就绪）"""
    return importlib.import_module("main")


@pytest.fixture
def build_config():
    """返回配置文本构造函数 render_toml"""
    return render_toml


@pytest.fixture
def missing():
    """哨兵值：表示该配置键不出现在配置文件中"""
    return MISSING


@pytest.fixture
def reset_mods(app):
    """用例前后重置修饰键状态，避免用例之间相互污染"""
    app._pressed_mods = set()
    yield
    app._pressed_mods = set()


@pytest.fixture
def make_app(tmp_path):
    """
    用指定配置重新加载 main 并返回模块

    用于验证「配置不同 → 行为不同」的场景，用例结束后恢复默认测试配置
    """
    import main

    def _make(config_text: str):
        path = tmp_path / "config.toml"
        path.write_text(config_text, encoding="utf-8")
        os.environ[CONFIG_ENV_VAR] = str(path)
        return importlib.reload(main)

    yield _make

    os.environ[CONFIG_ENV_VAR] = str(_SESSION_CONFIG)
    importlib.reload(main)
