"""配置文件的定位、读取与校验（无副作用，可在任意时刻调用）。"""

from __future__ import annotations

import os
import tomllib

# src/config.py 的上两级即为项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    "tooltip_text_color",
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
