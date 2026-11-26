"""命令行查看与修改配置"""

from __future__ import annotations

from pathlib import Path

import pytest

import cli
import config
import credentials

CONFIG = '''# 配置注释
target_lang = "Chinese"  # 目标语言
prompt_template = "把 {input_text} 翻译成 {target_lang}"
stream = true
hotkey_translate = "<ctrl>+<shift>+e"
hotkey_quit = "<ctrl>+<shift>+q"
tooltip_background_color = "#FFFFE0"  # 背景色
tooltip_text_color = "#000000"
tooltip_offset_x = 20
tooltip_offset_y = 20
tooltip_result_max_width = 30
tooltip_result_max_height = 8
tooltip_duration_ms = 1500
restore_clipboard = false
active_model = "m1"

[[platforms]]
name = "cloud"
base_url = "https://cloud.example.com"
api_key = "sk-secret"

[[models]]
name = "m1"
platform = "cloud"
model_name = "model-a"
'''


@pytest.fixture
def config_path(tmp_path) -> str:
    path = tmp_path / "config.toml"
    path.write_text(CONFIG, encoding="utf-8")
    return str(path)


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


# ===== 查看 =====


def test_show_prints_config_and_masks_secret(config_path, capsys):
    assert cli.main(["-c", config_path, "show"]) == 0

    out = capsys.readouterr().out
    assert config_path in out
    assert "target_lang = Chinese" in out
    assert "stream = true" in out
    assert "当前生效：模型 m1" in out
    assert "sk-secret" not in out
    assert "****** (已隐藏)" in out


def test_show_is_the_default_command(config_path, capsys):
    assert cli.main(["-c", config_path]) == 0

    assert "target_lang = Chinese" in capsys.readouterr().out


def test_get_top_level_value(config_path, capsys):
    assert cli.main(["-c", config_path, "get", "target_lang"]) == 0

    assert capsys.readouterr().out.strip() == "Chinese"


def test_get_nested_value(config_path, capsys):
    assert cli.main(["-c", config_path, "get", "models.m1.model_name"]) == 0
    assert capsys.readouterr().out.strip() == "model-a"

    assert cli.main(["-c", config_path, "get", "platforms.cloud.api_key"]) == 0
    assert capsys.readouterr().out.strip() == "****** (已隐藏)"


def test_unknown_key_reports_error(config_path, capsys):
    assert cli.main(["-c", config_path, "get", "not_there"]) == 1

    assert "错误" in capsys.readouterr().err


def test_config_option_works_after_subcommand(config_path, capsys):
    assert cli.main(["get", "target_lang", "-c", config_path]) == 0

    assert capsys.readouterr().out.strip() == "Chinese"


def test_config_path_comes_from_env(monkeypatch, config_path, capsys):
    monkeypatch.setenv(config.CONFIG_PATH_ENV_VAR, config_path)

    assert cli.main(["get", "target_lang"]) == 0
    assert capsys.readouterr().out.strip() == "Chinese"


# ===== 修改 =====


def test_set_keeps_comments_and_inline_notes(config_path, capsys):
    assert cli.main(["-c", config_path, "set", "target_lang", "Japanese"]) == 0

    text = read(config_path)
    assert 'target_lang = "Japanese"  # 目标语言' in text
    assert "# 配置注释" in text
    assert config.load_config(config_path)["target_lang"] == "Japanese"
    assert "已修改 target_lang：Chinese → Japanese" in capsys.readouterr().out


def test_set_parses_bool_int_and_hash_string(config_path):
    for key, value in [("stream", "false"), ("tooltip_offset_x", "50"), ("tooltip_background_color", "#123456")]:
        assert cli.main(["-c", config_path, "set", key, value]) == 0

    cfg = config.load_config(config_path)
    assert cfg["stream"] is False
    assert cfg["tooltip_offset_x"] == 50
    assert cfg["tooltip_background_color"] == "#123456"


def test_set_quoted_string_is_accepted(config_path):
    assert cli.main(["-c", config_path, "set", "target_lang", '"Japanese"']) == 0

    assert config.load_config(config_path)["target_lang"] == "Japanese"


def test_set_nested_field_by_name(config_path):
    assert cli.main(["-c", config_path, "set", "models.m1.model_name", "new-model"]) == 0

    assert config.load_config(config_path)["models"][0]["model_name"] == "new-model"


def test_set_adds_missing_key_before_tables(config_path):
    assert cli.main(["-c", config_path, "set", "stream_include_usage", "false"]) == 0

    text = read(config_path)
    assert "stream_include_usage = false" in text
    assert text.index("stream_include_usage") < text.index("[[platforms]]")
    assert config.load_config(config_path)["stream_include_usage"] is False


def test_set_adds_missing_nested_field(config_path):
    assert cli.main(["-c", config_path, "set", "models.m1.extra_body", "{}"]) == 0

    text = read(config_path)
    assert "  extra_body = {}" in text
    assert config.load_config(config_path)["models"][0]["extra_body"] == {}


def test_set_theme_into_dark_mode(config_path):
    assert cli.main(["-c", config_path, "set", "theme", "dark"]) == 0

    assert config.load_config(config_path)["theme"] == "dark"


def test_invalid_theme_is_rolled_back(config_path, capsys):
    original = read(config_path)

    assert cli.main(["-c", config_path, "set", "theme", "pink"]) == 1

    assert read(config_path) == original
    assert "theme" in capsys.readouterr().err


def test_invalid_semantic_value_rolls_back(config_path, capsys):
    original = read(config_path)

    assert cli.main(["-c", config_path, "set", "platforms.cloud.base_url", '""']) == 1

    assert read(config_path) == original
    assert "错误" in capsys.readouterr().err


def test_unsupported_value_type_is_rejected(config_path, capsys):
    original = read(config_path)

    assert cli.main(["-c", config_path, "set", "target_lang", "2020-01-01"]) == 1

    assert read(config_path) == original
    assert "不支持的配置值类型" in capsys.readouterr().err


# ===== 密钥独立存储 =====


@pytest.fixture
def credentials_path(tmp_path, monkeypatch):
    path = tmp_path / "credentials.toml"
    monkeypatch.setenv(credentials.CREDENTIALS_PATH_ENV_VAR, str(path))
    return str(path)


def test_set_key_writes_credentials_file_only(config_path, credentials_path, capsys):
    original = read(config_path)

    assert cli.main(["set-key", "cloud", "sk-new"]) == 0

    out = capsys.readouterr().out
    assert "sk-new" not in out
    assert credentials.load_credentials(credentials_path) == {"cloud": "sk-new"}
    assert read(config_path) == original  # 配置文件不被改动


def test_set_key_reads_value_from_stdin(config_path, credentials_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("sk-from-stdin\n"))

    assert cli.main(["set-key", "cloud"]) == 0

    assert credentials.load_credentials(credentials_path) == {"cloud": "sk-from-stdin"}
    assert "sk-from-stdin" not in capsys.readouterr().out


def test_set_platform_api_key_redirects_to_credentials(config_path, credentials_path, capsys):
    original = read(config_path)

    assert cli.main(["-c", config_path, "set", "platforms.cloud.api_key", "sk-via-set"]) == 0

    assert "sk-via-set" not in capsys.readouterr().out
    assert credentials.load_credentials(credentials_path) == {"cloud": "sk-via-set"}
    assert read(config_path) == original


def test_get_api_key_masks_effective_value(config_path, credentials_path, capsys):
    credentials.save_credential("cloud", "sk-hidden", credentials_path)

    assert cli.main(["-c", config_path, "get", "platforms.cloud.api_key"]) == 0

    out = capsys.readouterr().out.strip()
    assert out == "****** (已隐藏)"
    assert "sk-hidden" not in out
    assert "sk-secret" not in out  # 配置里的旧值也不回显


def test_show_reports_credentials_file(config_path, credentials_path, capsys):
    credentials.save_credential("cloud", "sk-hidden", credentials_path)

    assert cli.main(["-c", config_path, "show"]) == 0

    out = capsys.readouterr().out
    assert credentials_path in out
    assert "cloud = ****** (已隐藏)" in out
    assert "sk-hidden" not in out
