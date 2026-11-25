"""平台与模型分离：模型引用平台、提示词兜底与配置校验"""

from __future__ import annotations

import pytest

PLATFORMS = '''
[[platforms]]
name = "paratera"
base_url = "https://cloud.example.com"
api_key = "sk-test"

[[platforms]]
name = "ollama"
base_url = "http://localhost:11434/api/generate"
api_key = ""
'''

MODELS = '''
[[models]]
name = "cloud"
platform = "paratera"
model_name = "cloud-model"

[[models]]
name = "local"
platform = "ollama"
model_name = "local-model"
prompt_template = "本地专用：{input_text}"
'''


def test_active_model_gets_api_fields_from_its_platform(make_app, build_config):
    """当前模型从其引用的平台取得 API 地址与密钥"""
    app = make_app(build_config() + '\nactive_model = "cloud"\n' + PLATFORMS + MODELS)

    assert app.ACTIVE_MODEL_NAME == "cloud"
    assert app.ACTIVE_PLATFORM_NAME == "paratera"
    assert app.API_BASE_URL == "https://cloud.example.com"
    assert app.API_KEY == "sk-test"
    assert app.MODEL_NAME == "cloud-model"


def test_default_prompt_used_when_model_omits_it(make_app, build_config):
    """模型未写提示词时，用顶层默认提示词兜底"""
    app = make_app(build_config() + '\nactive_model = "cloud"\n' + PLATFORMS + MODELS)

    assert app.PROMPT_TEMPLATE == "把 {input_text} 翻译成 {target_lang}"

    url, payload, _ = app.build_request("hello", stream=False)
    assert url == "https://cloud.example.com/v1/chat/completions"
    assert payload["messages"][0]["content"] == "把 hello 翻译成 Chinese"


def test_model_prompt_overrides_default(make_app, build_config):
    """模型写了提示词时覆盖顶层默认值"""
    app = make_app(
        build_config()
        + '''
[[platforms]]
name = "ollama"
base_url = "http://localhost:11434/api/generate"
api_key = ""

[[models]]
name = "local"
platform = "ollama"
model_name = "local-model"
prompt_template = "本地专用：{input_text}"
'''
    )

    assert app.PROMPT_TEMPLATE == "本地专用：{input_text}"
    assert app.build_request("hi", stream=False)[1]["prompt"] == "本地专用：hi"


def test_first_model_used_when_active_not_set(make_app, build_config):
    """未指定 active_model 时用第一个模型"""
    app = make_app(build_config() + PLATFORMS + MODELS)

    assert app.ACTIVE_MODEL_NAME == "cloud"
    assert app.MODEL_NAME == "cloud-model"


def test_active_model_selects_second_model(make_app, build_config):
    """active_model 指向第二个模型时应选中它，并使用它依赖的平台"""
    app = make_app(build_config() + '\nactive_model = "local"\n' + PLATFORMS + MODELS)

    assert app.ACTIVE_MODEL_NAME == "local"
    assert app.ACTIVE_PLATFORM_NAME == "ollama"
    assert app.API_BASE_URL == "http://localhost:11434/api/generate"
    assert app.API_KEY == ""
    assert app.MODEL_NAME == "local-model"


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ('active_model = "nope"\n' + PLATFORMS + MODELS, "不存在的模型"),
        ("platforms = []\n" + MODELS, "platforms 至少要包含一项"),
        (PLATFORMS + "\nmodels = []\n", "models 至少要包含一项"),
        ('[[platforms]]\nname = "p"\n' + MODELS, "缺少必要项"),
        (
            PLATFORMS
            + '\n[[models]]\nname = "m"\nplatform = "paratera"\nmodel_name = ""\n',
            "不能为空",
        ),
        (
            PLATFORMS
            + '\n[[models]]\nname = "m"\nplatform = "nope"\nmodel_name = "x"\n',
            "不存在的平台",
        ),
        (PLATFORMS + MODELS + '\n[[models]]\nname = "cloud"\nplatform = "paratera"\nmodel_name = "x"\n', "名称重复"),
    ],
)
def test_invalid_platforms_or_models_raise(tmp_path, build_config, extra, message):
    """平台/模型配置非法时给出明确错误"""
    import main

    path = tmp_path / "config.toml"
    path.write_text(build_config() + extra, encoding="utf-8")

    with pytest.raises(main.ConfigError, match=message):
        main.load_config(path)


def test_legacy_flat_config_still_works(make_app, build_config):
    """旧的扁平配置仍可加载，等价一个默认平台上的默认模型"""
    app = make_app(build_config())

    assert app.ACTIVE_MODEL_NAME == "default"
    assert app.ACTIVE_PLATFORM_NAME == "default"
    assert app.API_BASE_URL == "http://localhost:11434/api/generate"
    assert app.MODEL_NAME == "test-model"
