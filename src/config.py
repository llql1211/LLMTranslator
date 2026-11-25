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

# 全局必填配置项（平台与模型相关字段放在各自的表格数组里）
REQUIRED_KEYS = (
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

# 旧扁平格式（既无 platforms 也无 models 时）需要的 API 字段
LEGACY_API_KEYS = ("base_url", "api_key", "model_name")

# 平台的必填字段；api_key 允许为空（表示走 Ollama 原生格式）
PLATFORM_REQUIRED_KEYS = ("name", "base_url")

# 模型的必填字段；platform 指向平台名称，prompt_template 可选
MODEL_REQUIRED_KEYS = ("name", "platform", "model_name")

# 必填且不能为空的字段
NON_EMPTY_KEYS = ("base_url", "model_name")

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


def _check_table_array(config: dict, key: str, required: tuple[str, ...]) -> list[dict]:
    """校验一个表格数组：非空、元素为字典、必填字段齐全、名称唯一"""
    items = config.get(key)
    if not isinstance(items, list) or not items:
        raise ConfigError(f"{key} 至少要包含一项")

    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ConfigError(f"{key}[{index}] 必须是一个配置表")
        missing = [field for field in required if field not in item]
        if missing:
            raise ConfigError(f"{key}[{index}] 缺少必要项：{', '.join(missing)}")
        for field in NON_EMPTY_KEYS:
            if field in item and not item[field]:
                raise ConfigError(f"{key}[{index}] 的 {field} 不能为空")
        name = item["name"]
        if name in seen:
            raise ConfigError(f"{key} 名称重复：{name}")
        seen.add(name)
    return items


def resolve_active_model(config: dict) -> dict:
    """
    返回当前生效的模型配置，合并其依赖的平台配置

    统一返回含 name/platform/base_url/api_key/model_name 的字典；
    模型未写 prompt_template 时不补默认值，由调用方用全局默认提示词兜底。

    - 新格式：[[platforms]] 存 API 地址与密钥，[[models]] 存模型名与提示词
    - 旧格式：无表格数组时把扁平的 API 字段当成一个模型，保持向后兼容
    """
    if "platforms" not in config and "models" not in config:
        return {
            "name": "default",
            "platform": "default",
            "base_url": config["base_url"],
            "api_key": config["api_key"],
            "model_name": config["model_name"],
        }

    platforms = _check_table_array(config, "platforms", PLATFORM_REQUIRED_KEYS)
    models = _check_table_array(config, "models", MODEL_REQUIRED_KEYS)
    platform_by_name = {p["name"]: p for p in platforms}

    for model in models:
        if model["platform"] not in platform_by_name:
            raise ConfigError(f"模型 {model['name']} 引用了不存在的平台：{model['platform']}")
        if "extra_body" in model and not isinstance(model["extra_body"], dict):
            raise ConfigError(f"模型 {model['name']} 的 extra_body 必须是键值表")

    active = config.get("active_model")
    if active:
        selected = next((m for m in models if m["name"] == active), None)
        if selected is None:
            raise ConfigError(f"active_model 指向不存在的模型：{active}")
    else:
        selected = models[0]

    platform = platform_by_name[selected["platform"]]
    return {
        "name": selected["name"],
        "platform": platform["name"],
        "base_url": platform["base_url"],
        "api_key": platform.get("api_key", ""),
        "model_name": selected["model_name"],
        **({"prompt_template": selected["prompt_template"]} if "prompt_template" in selected else {}),
        **({"extra_body": selected["extra_body"]} if "extra_body" in selected else {}),
    }


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

    if "platforms" not in config and "models" not in config:
        # 兼容旧格式：API 字段直接写在顶层
        missing = [k for k in LEGACY_API_KEYS if k not in config]
        if missing:
            raise ConfigError(f"配置文件缺少必要项：{', '.join(missing)}")
        empty = [k for k in NON_EMPTY_KEYS if not config[k]]
        if empty:
            raise ConfigError(
                f"以下配置项不能为空：{', '.join(empty)}\n请在 {config_path} 中填写"
            )
    else:
        # 选模型时一并校验平台与模型配置
        resolve_active_model(config)

    return config
