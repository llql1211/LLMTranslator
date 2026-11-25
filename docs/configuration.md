# 配置参考

所有配置集中在 `data/config.toml`。该文件含 API 密钥，不纳入版本管理；首次使用请复制模板：

```bash
copy data\config.example.toml data\config.toml   # Windows
cp data/config.example.toml data/config.toml     # Linux/macOS
```

模板中每一项都有简要注释。平台与模型分开配置，模型通过 `platform` 引用平台。也可以用命令行修改，见 [README 的命令行配置](../README.md#命令行配置)。

## 完整字段

| 字段 | 说明 | 模板默认值 |
| :--- | :--- | :--- |
| `platforms` | **必填**。平台列表，每项含 `name`、`base_url`、`api_key` | 见模板 |
| `models` | **必填**。模型列表，每项含 `name`、`platform`、`model_name`，可选 `prompt_template`、`extra_body` | 见模板 |
| `active_model` | 当前模型名，留空则用第一个模型 | `example-cloud` |
| `target_lang` | 目标语言 | `Chinese` |
| `prompt_template` | 默认提示词，模型未单独写时用它兜底 | 见模板 |
| `theme` | `light` / `dark` | `light` |
| `stream` | 是否边翻译边显示 | `true` |
| `stream_include_usage` | OpenAI 流式请求是否请求末帧返回 token 统计；服务端不支持 `stream_options` 时设为 `false` | `true` |
| `hotkey_translate` | 翻译热键 | `<ctrl>+<shift>+e` |
| `hotkey_quit` | 退出热键 | `<ctrl>+<shift>+q` |
| `tooltip_background_color` | 旧字段：仅未设置 `theme` 时生效 | `#FFFFE0` |
| `tooltip_text_color` | 旧字段：仅未设置 `theme` 时生效 | `#000000` |
| `tooltip_background_color_light` | 主题模式下浅色弹窗背景 | `#FFFFE0` |
| `tooltip_text_color_light` | 主题模式下浅色弹窗文字 | `#000000` |
| `tooltip_background_color_dark` | 深色弹窗背景 | `#2B2B2B` |
| `tooltip_text_color_dark` | 深色弹窗文字 | `#EAEAEA` |
| `tooltip_offset_x` / `tooltip_offset_y` | 弹窗相对鼠标的偏移（像素） | `20` / `20` |
| `tooltip_result_max_width` | 结果弹窗宽度（字符数） | `30` |
| `tooltip_result_max_height` | 结果弹窗高度（行数），超出后内部滚动 | `8` |
| `tooltip_duration_ms` | 错误提示弹窗自动关闭时间（毫秒） | `1500` |
| `tooltip_font_family` | 译文弹窗字体名（本机已安装的字体） | `Microsoft YaHei` |
| `tooltip_font_size` | 译文弹窗字号（磅），须为 6~72 的整数 | `11` |
| `restore_clipboard` | 是否恢复翻译前的剪贴板内容 | `false` |

## 译文字体与字号

- `tooltip_font_family` 填字体名，例如 `"Microsoft YaHei"`、`"Consolas"`、`"Noto Sans CJK SC"`；本机没有该字体时由 Tk 回退，换字体需重启程序。
- `tooltip_font_size` 填整数磅值，允许 6~72，默认 11；同样需重启后生效。
- 只对译文弹窗生效，右上角状态提示框的字体不受影响。旧配置没写这两项时沿用内置默认值。

## 深浅模式

- `theme = "light"`：译文弹窗便签黄底深字，右上角提示框白底深字；提示框左侧强调条用绿（等待）、蓝（翻译中）、红（出错）、灰（退出）区分状态。
- `theme = "dark"`：两者都换成深色配色。
- **显式写了 `theme` 后**，弹窗颜色由 `*_light` / `*_dark` 两组字段决定，旧的 `tooltip_background_color` / `tooltip_text_color` 不再生效（仅为未设置 `theme` 的旧配置保留）。
- 切换主题需重启程序。

## 平台与模型

平台负责「怎么连」，模型负责「用哪个、怎么问」。同一个平台下可以挂多个模型；切换模型需改配置后重启。

平台字段（`[[platforms]]`）：

- `name`：平台名，供模型引用，不可重复
- `base_url`：API 地址。`api_key` 为空时填 Ollama 的 `/api/generate` 地址；非空时填服务根地址即可，程序自动补全 `/v1/chat/completions`。建议用 `https`，避免 http→https 重定向导致 405
- `api_key`：密钥，留空则走 Ollama 原生格式

模型字段（`[[models]]`）：

- `name`：模型配置名，供 `active_model` 引用，不可重复
- `platform`：依赖的平台名，必须是上面已有的平台
- `model_name`：实际传给 API 的模型名称
- `prompt_template`（可选）：该模型专用提示词，不写则用顶层默认提示词
- `extra_body`（可选）：原样合并进 OpenAI 兼容请求体，例如 `extra_body = { thinking = { type = "disabled" } }` 可关闭思考；Ollama 原生格式忽略此项，且核心字段不会被覆盖

```toml
active_model = "cloud"

[[platforms]]
name = "paratera"
base_url = "https://api.example.com"
api_key = "sk-xxx"

[[platforms]]
name = "ollama"
base_url = "http://localhost:11434/api/generate"
api_key = ""

[[models]]
name = "cloud"
platform = "paratera"
model_name = "my-model"
extra_body = { thinking = { type = "disabled" } }

[[models]]
name = "local"
platform = "ollama"
model_name = "hy-mt"
prompt_template = "专用提示词：{input_text}"
```

> `[[platforms]]` 与 `[[models]]` 是 TOML 表格数组，必须放在文件末尾、先平台后模型且不能交叉，否则其后的配置项会被归入最后一个表格。

## 生成参数

| 字段 | 说明 | 默认值 |
| :--- | :--- | :--- |
| `temperature` | 采样温度，越高越随机 | `0.7` |
| `top_p` | 核采样阈值 | `0.6` |
| `top_k` | 采样时仅保留概率最高的 K 个词 | `20` |
| `repetition_penalty` | 重复惩罚，大于 1 可抑制重复 | `1.05` |
| `max_tokens` | 单次生成的最大 token 数 | `4096` |

这组参数采用「写了才发送」策略：注释掉某一行，该参数就不会出现在请求里；全部注释掉即完全使用服务端默认值。

- `top_k`、`repetition_penalty` 属于 Ollama 扩展参数，改用严格校验的云端 API 时建议注释掉，以免返回 400。
- 字段名由程序自动转换：Ollama 原生格式下 `max_tokens` → `num_predict`、`repetition_penalty` → `repeat_penalty`，统一放入 `options`；OpenAI 兼容格式下平铺在请求体顶层。

## 其他注意事项

- 热键解析只支持**标准修饰键（`ctrl`、`shift`、`alt`、`cmd`）+ 单个可打印字符**，不支持功能键、方向键或多键组合；详见 `parse_hotkey()` 与 `_matches_key()`。
- 热键请勿与其他软件冲突，例如 VSCode 默认用 `Ctrl+Shift+C` 打开终端。
- 若当前模型引用的平台 `api_key` 非空，请求会自动切换为 OpenAI 兼容格式。
- 结果弹窗点击外部或按 `Esc` 关闭。若翻译未结束就关闭，会中断请求，已翻出的部分不再保留。

提示词模板的写法与模型配套选择见 [模型与提示词](models.md)。
