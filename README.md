# LLMTranslator

[配置](docs/configuration.md) | [模型与提示词](docs/models.md) | [Ollama 部署](docs/ollama.md) | [故障排查](docs/troubleshooting.md) | [开发](docs/development.md) | [更新日志](docs/CHANGELOG.md)

选中文本 → 按热键 → 光标旁弹出译文。支持本地 Ollama 与 OpenAI 兼容 API，提供流式输出、深浅主题、token 统计和命令行改配置。

<table>
  <tr>
    <td align="center"><img src="docs/assets/running_light.png" alt="浅色模式" width="400"><br>浅色模式</td>
    <td align="center"><img src="docs/assets/running_dark.png" alt="深色模式" width="400"><br>深色模式</td>
  </tr>
</table>

> 仅适用于「可选中文本」的场景，不支持图片内的文字。

## 快速开始

1. 准备 Python 3.11+（开发环境为 3.14），安装依赖：`pip install pyautogui pynput pyperclip requests`
2. 复制配置：`copy data\config.example.toml data\config.toml`（Linux/macOS 用 `cp`）
3. 在配置里至少填好一个平台的 `base_url` 和模型的 `model_name`
4. 启动：`python src/main.py`（若使用 pixi： `pixi run start`）
5. 选中文本按 `Ctrl+Shift+E` 查看译文，`Ctrl+Shift+Q` 退出

不用 pixi 的细节见 [安装与运行](docs/development.md)，本地模型部署见 [Ollama 部署](docs/ollama.md)。

## 功能

- 光标旁无边框弹窗，点击外部或 `Esc` 关闭，窗口内可选中文本、鼠标悬停滚动
- 流式 / 非流式输出，长译文随内容增长，到上限后内部滚动
- 深浅主题：浅色为便签黄弹窗 + 白底提示框，深色为深灰弹窗 + 深色提示框
- 多平台多模型，自动识别 OpenAI 兼容格式，支持模型级 `extra_body`
- 终端日志带时间戳与级别，每轮结束输出耗时和 token 统计
- 命令行查看与修改配置，修改会保留原注释并自动校验

## 配置速览

| 字段 | 说明 | 默认值 |
| :--- | :--- | :--- |
| `platforms` / `models` | 平台与模型列表，模型通过 `platform` 引用平台 | 见模板 |
| `active_model` | 当前使用的模型名，留空则用第一个 | `example-cloud` |
| `target_lang` | 目标语言 | `Chinese` |
| `prompt_template` | 默认提示词，可用 `{target_lang}` / `{input_text}` 占位符 | 见模板 |
| `theme` | `light` / `dark`，切换后需重启 | `light` |
| `stream` | 是否边翻译边显示 | `true` |
| `tooltip_font_family` / `tooltip_font_size` | 译文弹窗字体与字号（磅），切换后需重启 | `Microsoft YaHei` / `11` |
| `hotkey_translate` / `hotkey_quit` | 翻译 / 退出热键 | `<ctrl>+<shift>+e` / `<ctrl>+<shift>+q` |
| `restore_clipboard` | 是否恢复翻译前的剪贴板内容 | `false` |

完整字段、生成参数与配色说明见 [配置参考](docs/configuration.md)。

## 命令行配置

```bash
pixi run config show                     # 查看全部配置（密钥自动遮蔽）
pixi run config get target_lang          # 读取单个配置项
pixi run config set theme dark           # 修改配置项，重启后生效
```

不用 pixi 时把 `pixi run config` 换成 `python src/cli.py`。

## 许可证

MIT，详见 [LICENSE](LICENSE)。
