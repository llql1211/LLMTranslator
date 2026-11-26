"""密钥独立存储：路径、读写与运行时合并"""

from __future__ import annotations

import credentials
import pytest

CREDENTIALS_ENV_VAR = credentials.CREDENTIALS_PATH_ENV_VAR


# ===== 路径 =====


def test_env_var_overrides_default_path(tmp_path, monkeypatch):
    custom = tmp_path / "custom.toml"
    monkeypatch.setenv(CREDENTIALS_ENV_VAR, str(custom))

    assert credentials.resolve_credentials_path() == str(custom)
    assert credentials.resolve_credentials_path(str(tmp_path / "explicit.toml")) == str(
        tmp_path / "explicit.toml"
    )


def test_windows_default_path_uses_appdata(monkeypatch):
    monkeypatch.delenv(CREDENTIALS_ENV_VAR, raising=False)
    monkeypatch.setattr(credentials.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\tester\AppData\Roaming")

    assert credentials.resolve_credentials_path() == (
        r"C:\Users\tester\AppData\Roaming\LLMTranslator\credentials.toml"
    )


# ===== 读写 =====


def test_missing_file_returns_empty(tmp_path):
    assert credentials.load_credentials(tmp_path / "none.toml") == {}


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "secrets" / "credentials.toml"
    credentials.save_credential("cloud", "sk-abc", str(path))
    credentials.save_credential("my platform", 'sk-"quoted"', str(path))

    keys = credentials.load_credentials(str(path))
    assert keys == {"cloud": "sk-abc", "my platform": 'sk-"quoted"'}
    assert "sk-abc" not in path.read_text(encoding="utf-8").split("[platforms]")[0]


def test_save_overwrites_only_target_platform(tmp_path):
    path = str(tmp_path / "credentials.toml")
    credentials.save_credential("cloud", "sk-old", path)
    credentials.save_credential("local", "", path)
    credentials.save_credential("cloud", "sk-new", path)

    assert credentials.load_credentials(path) == {"cloud": "sk-new", "local": ""}


def test_invalid_format_raises(tmp_path):
    path = tmp_path / "credentials.toml"
    path.write_text("[platforms]\ncloud = 123\n", encoding="utf-8")

    with pytest.raises(credentials.CredentialsError):
        credentials.load_credentials(str(path))


def test_broken_toml_raises(tmp_path):
    path = tmp_path / "credentials.toml"
    path.write_text("[platforms\n", encoding="utf-8")

    with pytest.raises(credentials.CredentialsError):
        credentials.load_credentials(str(path))


# ===== 与配置合并 =====


def test_credentials_take_precedence_over_legacy_field(tmp_path):
    path = str(tmp_path / "credentials.toml")
    credentials.save_credential("cloud", "sk-file", path)

    assert credentials.resolve_api_key("cloud", "sk-legacy", path) == "sk-file"
    assert credentials.resolve_api_key("other", "sk-legacy", path) == "sk-legacy"


def test_empty_stored_key_is_not_replaced_by_legacy(tmp_path):
    path = str(tmp_path / "credentials.toml")
    credentials.save_credential("cloud", "", path)

    assert credentials.resolve_api_key("cloud", "sk-legacy", path) == ""


def test_main_takes_api_key_from_credentials(make_app, build_config, tmp_path, monkeypatch):
    monkeypatch.setenv(CREDENTIALS_ENV_VAR, str(tmp_path / "credentials.toml"))
    credentials.save_credential("cloud", "sk-from-file")
    text = build_config() + '''
active_model = "m1"

[[platforms]]
name = "cloud"
base_url = "https://example.com"

[[models]]
name = "m1"
platform = "cloud"
model_name = "demo-model"
'''

    app = make_app(text)

    assert app.API_KEY == "sk-from-file"
