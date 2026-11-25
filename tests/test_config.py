"""
配置加载与校验

注意：本文件一律通过 main.X 动态取属性，而不是 `from main import X`。
因为 make_app 夹具会 reload main，reload 会重建 ConfigError 等类对象，
模块导入时拿到的旧引用会与 reload 后抛出的异常类型不是同一个类，
导致 pytest.raises 匹配不上。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import main

EXAMPLE_CONFIG_PATH = Path(main.__file__).resolve().parents[1] / "data" / "config.example.toml"


def write(path: Path, text: str) -> Path:
    """写出配置文件并返回路径"""
    path.write_text(text, encoding="utf-8")
    return path


# ===== 正常读取 =====


def test_load_config_returns_all_keys(tmp_path, build_config):
    """正常配置应完整读出"""
    config = main.load_config(write(tmp_path / "config.toml", build_config()))

    assert config["base_url"] == "http://localhost:11434/api/generate"
    assert config["model_name"] == "test-model"
    assert config["restore_clipboard"] is False
    assert config["tooltip_offset_x"] == 20


def test_load_config_keeps_generation_params(tmp_path, build_config):
    """生成参数应按原值读出，类型不被改写"""
    path = write(
        tmp_path / "config.toml",
        build_config(temperature=0.7, max_tokens=4096, top_k=20),
    )
    config = main.load_config(path)

    assert config["temperature"] == 0.7
    assert config["max_tokens"] == 4096
    assert config["top_k"] == 20


# ===== 错误处理 =====


def test_missing_file_raises_with_hint(tmp_path):
    """配置文件不存在时提示复制模板"""
    missing = tmp_path / "nope.toml"

    with pytest.raises(main.ConfigError) as exc:
        main.load_config(missing)

    message = str(exc.value)
    assert "未找到配置文件" in message
    assert "config.example.toml" in message
    assert str(missing) in message


def test_missing_required_key_raises(tmp_path, build_config, missing):
    """缺少必要项时指出具体是哪些键"""
    path = write(tmp_path / "config.toml", build_config(model_name=missing))

    with pytest.raises(main.ConfigError) as exc:
        main.load_config(path)

    assert "缺少必要项" in str(exc.value)
    assert "model_name" in str(exc.value)


def test_empty_required_key_raises(tmp_path, build_config):
    """base_url / model_name 留空时报错，这正是模板的初始状态"""
    path = write(tmp_path / "config.toml", build_config(base_url="", model_name=""))

    with pytest.raises(main.ConfigError) as exc:
        main.load_config(path)

    message = str(exc.value)
    assert "不能为空" in message
    assert "base_url" in message
    assert "model_name" in message


def test_syntax_error_raises(tmp_path):
    """TOML 语法错误应有明确提示，而不是抛裸的 TOMLDecodeError"""
    path = write(tmp_path / "config.toml", 'base_url = "unterminated\n')

    with pytest.raises(main.ConfigError) as exc:
        main.load_config(path)

    assert "解析失败" in str(exc.value)


# ===== 路径解析优先级 =====


def test_explicit_path_wins_over_env(tmp_path, monkeypatch, build_config):
    """显式传入的路径优先级最高"""
    monkeypatch.setenv(main.CONFIG_PATH_ENV_VAR, str(tmp_path / "from-env.toml"))
    explicit = write(tmp_path / "explicit.toml", build_config(model_name="explicit-model"))

    assert main.load_config(explicit)["model_name"] == "explicit-model"


def test_env_var_wins_over_default(tmp_path, monkeypatch, build_config):
    """环境变量可覆盖默认路径"""
    env_path = write(tmp_path / "from-env.toml", build_config(model_name="env-model"))
    monkeypatch.setenv(main.CONFIG_PATH_ENV_VAR, str(env_path))

    assert main.resolve_config_path() == str(env_path)
    assert main.load_config()["model_name"] == "env-model"


def test_falls_back_to_default_path(monkeypatch):
    """未指定参数与环境变量时回到 data/config.toml"""
    monkeypatch.delenv(main.CONFIG_PATH_ENV_VAR, raising=False)

    assert main.resolve_config_path() == main.DEFAULT_CONFIG_PATH


def test_empty_env_var_falls_back_to_default(monkeypatch):
    """环境变量为空串时不应被当成有效路径"""
    monkeypatch.setenv(main.CONFIG_PATH_ENV_VAR, "")

    assert main.resolve_config_path() == main.DEFAULT_CONFIG_PATH


# ===== 模板与代码的一致性 =====


def test_example_config_covers_code_requirements():
    """
    配置模板必须包含代码要求的全部配置项

    防止新增配置项后忘记同步 data/config.example.toml
    """
    with open(EXAMPLE_CONFIG_PATH, "rb") as f:
        example = tomllib.load(f)

    assert set(main.REQUIRED_KEYS) <= set(example)
    assert set(main.GEN_PARAM_MAP) <= set(example)


def test_example_config_keeps_required_fields_blank():
    """模板中第一个平台的地址/密钥与第一个模型的名称应留空，由使用者填写"""
    with open(EXAMPLE_CONFIG_PATH, "rb") as f:
        example = tomllib.load(f)

    assert example["platforms"][0]["base_url"] == ""
    assert example["platforms"][0]["api_key"] == ""
    assert example["models"][0]["model_name"] == ""


def test_example_config_is_loadable_once_filled(tmp_path, build_config):
    """模板填上必填项后应能正常加载"""
    text = build_config() + '''
active_model = "demo"

[[platforms]]
name = "cloud"
base_url = "https://example.com"
api_key = "sk-test"

[[models]]
name = "demo"
platform = "cloud"
model_name = "demo-model"
'''
    path = write(tmp_path / "config.toml", text)

    config = main.load_config(path)
    assert main.resolve_active_model(config)["model_name"] == "demo-model"
