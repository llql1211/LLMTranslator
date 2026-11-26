"""API 密钥的独立存储：放在用户数据目录，不随配置文件与仓库分发。

设计参考 Sakura：模型配置（base_url / model_name）与连接密钥分开保存，
程序运行期间才把两者在内存里合并。仓库内的 config.toml 不再出现密钥，
这样浏览配置的 agent、git 提交、日志截图都拿不到密钥。

默认路径：

    Windows: %APPDATA%\\LLMTranslator\\credentials.toml
    macOS:   ~/Library/Application Support/LLMTranslator/credentials.toml
    Linux:   ~/.config/llmtranslator/credentials.toml

可用 LLMTRANSLATOR_CREDENTIALS 环境变量覆盖（测试与多实例场景）。
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path

CREDENTIALS_PATH_ENV_VAR = "LLMTRANSLATOR_CREDENTIALS"
APP_NAME = "LLMTranslator"
PLATFORMS_TABLE = "platforms"


class CredentialsError(ValueError):
    """密钥文件读写或格式错误"""


def resolve_credentials_path(path: str | None = None) -> str:
    """按 显式参数 → 环境变量 → 用户数据目录 的优先级确定密钥文件位置"""
    if path:
        return path
    env_path = os.environ.get(CREDENTIALS_PATH_ENV_VAR)
    if env_path:
        return env_path
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return str(Path(appdata) / APP_NAME / "credentials.toml")
    if sys.platform == "darwin":
        return str(Path.home() / "Library" / "Application Support" / APP_NAME / "credentials.toml")
    return str(Path.home() / ".config" / "llmtranslator" / "credentials.toml")


def load_credentials(path: str | None = None) -> dict[str, str]:
    """读取密钥表；文件不存在时返回空字典，格式错误时抛出 CredentialsError"""
    target = Path(resolve_credentials_path(path))
    if not target.exists():
        return {}
    try:
        with open(target, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise CredentialsError(f"密钥文件解析失败：{target}\n{e}") from e

    keys = data.get(PLATFORMS_TABLE, {})
    if not isinstance(keys, dict):
        raise CredentialsError(f"密钥文件的 [{PLATFORMS_TABLE}] 必须是键值表：{target}")
    for name, value in keys.items():
        if not isinstance(value, str):
            raise CredentialsError(f"平台 {name} 的密钥必须是字符串：{target}")
    return dict(keys)


def _serialize(keys: dict[str, str]) -> str:
    """把密钥表写成 TOML；键名含非字母数字时自动加引号"""
    lines = ["# LLMTranslator 密钥文件：请勿提交、上传或发给他人", f"[{PLATFORMS_TABLE}]"]
    for name, value in keys.items():
        bare = name and all(c.isascii() and (c.isalnum() or c in "-_") for c in name)
        key = name if bare else json.dumps(name, ensure_ascii=False)
        lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def save_credential(name: str, value: str, path: str | None = None) -> str:
    """新增或替换一个平台的密钥，返回密钥文件路径"""
    if not isinstance(name, str) or not name.strip():
        raise CredentialsError("平台名不能为空")
    if not isinstance(value, str):
        raise CredentialsError("密钥必须是字符串")

    target = Path(resolve_credentials_path(path))
    keys = load_credentials(path)
    keys[name.strip()] = value
    target.parent.mkdir(parents=True, exist_ok=True)

    # 先写临时文件再替换，避免写入中断留下半份密钥文件
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(_serialize(keys), encoding="utf-8")
    os.replace(temporary, target)
    return str(target)


def resolve_api_key(platform_name: str, legacy_key: str = "", path: str | None = None) -> str:
    """优先取独立密钥文件；未登记的平台回退到配置里的旧字段（兼容旧配置）。

    密钥文件中显式写空串表示「此平台不用密钥」，不会被旧字段重新填上。
    """
    keys = load_credentials(path)
    if platform_name in keys:
        return keys[platform_name]
    return legacy_key
