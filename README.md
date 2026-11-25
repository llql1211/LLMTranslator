# LLMTranslator

## 目录

- [简介](#简介)
- [工作流程](#工作流程)
- [配置参数](#配置参数)
- [部署模型与配置 Ollama](#部署模型与配置-ollama)
- [使用说明](#使用说明)
- [平台支持](#平台支持)

## 简介

LLMTranslator 利用模型（本地 Ollama 或云端 API），将选中的文本翻译为目标语言，并通过弹窗形式显示在鼠标光标右下角。

程序通过 `pynput` 监听快捷键，模拟 `Ctrl+C` 复制选中文本，读取剪贴板内容，再调用 LLM API 翻译，最后使用 `tkinter` 显示结果。

（注：也支持 OpenAI 兼容 API，配置 `api_key` 即可自动切换）

**注意**：该工具依赖文本选中能力，因此仅适用于可选中文本的场景（不包括图片）。

## 工作流程

1. 程序启动后，在屏幕右上角显示常驻提示框"等待快捷键..."，并使用 `pynput` 库在后台持续监听用户预设的热键。

2. 当检测到翻译热键被按下时，程序自动模拟 `Ctrl+C` 操作，复制当前选中的文本，并通过 `pyperclip` 读取剪贴板中的内容。同时右上角提示框显示"翻译中..."。

3. 对获取的文本进行预处理，例如去除从 PDF 等来源复制时可能产生的多余换行符，以提升翻译质量。

4. 将清洗后的文本发送至 LLM API，调用指定的翻译模型进行翻译。

5. 接收模型返回的翻译结果后，利用 `pyautogui` 获取当前鼠标指针的位置，并基于该坐标，使用 `tkinter` 创建一个位于鼠标右下方的小窗口，展示翻译内容。

6. 翻译窗口为非焦点模式，窗口始终保持置顶。支持以下关闭方式：

    - 点击窗口外部区域自动关闭
    - 按下 `Esc` 键关闭

    **注**：窗口内部可选中文本，鼠标悬停可滚动查看长内容。

7. 窗口关闭后，程序**返回步骤 2**，继续监听下一轮翻译请求。

8. 当监听到退出热键时，右上角提示框更新为"正在退出..."，程序正常退出。

## 配置参数

所有配置集中在 `data/config.toml` 中。

该文件**不纳入版本管理**（可能包含 `api_key`），首次使用请从模板复制：

```bash
copy data\config.example.toml data\config.toml   # Windows
cp data/config.example.toml data/config.toml     # Linux/macOS
```

模板 `data/config.example.toml` 中每一项都带有注释说明。平台（API 地址/密钥）与模型（模型名/提示词）分开配置，模型通过 `platform` 引用平台；其余各项均有可用默认值。各字段含义如下：

| 字段 | 说明 | 模板默认值 |
| :--- | :--- | :--- |
| `platforms` | **必填**。平台列表，每档含 `name`、`base_url`、`api_key`，见下方「平台与模型」 | 见模板 |
| `models` | **必填**。模型列表，每个含 `name`、`platform`、`model_name`，以及可选的 `prompt_template`、`extra_body` | 见模板 |
| `active_model` | 当前使用的模型名称；留空则用第一个模型 | `example-cloud` |
| `target_lang` | 目标语言 | `Chinese` |
| `prompt_template` | **默认提示词**：模型未写自己的提示词时用它兜底，可用 `{target_lang}` 和 `{input_text}` 占位符 | （见下方） |
| `stream` | 流式输出。为 `true` 时边翻译边显示，弹窗随内容增长；为 `false` 时等整段翻完再一次性显示 | `true` |
| `hotkey_translate` | 翻译热键（见下方注释） | `<ctrl>+<shift>+e` |
| `hotkey_quit` | 退出热键（见下方注释） | `<ctrl>+<shift>+q` |
| `tooltip_background_color` | 弹窗背景色 | `#FFFFE0` |
| `tooltip_text_color` | 弹窗文本颜色 | `#000000` |
| `tooltip_offset_x` | 弹窗相对于鼠标光标的 X 偏移（像素） | `20` |
| `tooltip_offset_y` | 弹窗相对于鼠标光标的 Y 偏移（像素） | `20` |
| `tooltip_result_max_width` | 翻译结果弹窗宽度（字符数） | `30` |
| `tooltip_result_max_height` | 翻译结果弹窗高度（行数） | `8` |
| `tooltip_duration_ms` | 错误提示弹窗的自动关闭时间（毫秒） | `1500` |
| `restore_clipboard` | 是否在获取文本后恢复原始剪贴板内容 | `false` |

### 平台与模型

平台负责「怎么连」，模型负责「用哪个、怎么问」。同一个平台下可以挂多个模型；切换模型需改配置后重启程序（暂无运行期切换热键）。

平台字段（`[[platforms]]`）：

- `name`：平台名，供模型引用，不可重复
- `base_url`：API 地址。`api_key` 为空时填 Ollama 的 `/api/generate` 地址；非空时填服务根地址即可，程序自动补全 `/v1/chat/completions`。建议直接用 `https`，避免 http→https 重定向导致 405
- `api_key`：API 密钥，留空则走 Ollama 原生格式

模型字段（`[[models]]`）：

- `name`：模型配置名，供 `active_model` 引用，不可重复
- `platform`：依赖的平台名，必须是上面已有的平台
- `model_name`：实际传给 API 的模型名称
- `prompt_template`（可选）：该模型专用提示词，不写则用顶层默认提示词
- `extra_body`（可选）：附加到 OpenAI 兼容请求体的字段，比如 `extra_body = { thinking = { type = "disabled" } }` 可关闭思考、缩短等待；Ollama 原生格式忽略此项。核心字段（`model`/`messages`/`stream`）不会被它覆盖

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

**注意**：`[[platforms]]` 与 `[[models]]` 属于 TOML 表格数组，必须放在配置文件末尾、先平台后模型且不能交叉，否则其后的配置项会被归入最后一个表格。

### 生成参数

| 字段 | 说明 | 默认值 |
| :--- | :--- | :--- |
| `temperature` | 采样温度，越高越随机 | `0.7` |
| `top_p` | 核采样阈值 | `0.6` |
| `top_k` | 采样时仅保留概率最高的 K 个词 | `20` |
| `repetition_penalty` | 重复惩罚系数，大于 1 可抑制重复 | `1.05` |
| `max_tokens` | 单次生成的最大 token 数 | `4096` |

这组参数采用**「写了才发送」**的策略：注释掉某一行，该参数就不会出现在请求中。

- 全部注释掉即完全使用服务端默认值。
- `top_k`、`repetition_penalty` 属于 Ollama 扩展参数，改用校验严格的云端 API 时建议注释掉，以免返回 400。
- 两种请求格式的字段名由程序自动转换：Ollama 原生格式下 `max_tokens` → `num_predict`、`repetition_penalty` → `repeat_penalty`，且统一放入 `options` 字段；OpenAI 兼容格式下则平铺在请求体顶层。

**注意**：

- 不建议大幅度修改热键。当前热键解析实现只支持**标准修饰键（`ctrl`、`shift`、`alt`、`cmd`）+ 单个可打印字符**的组合，不支持功能键（F1–F12）、方向键、`<ctrl>+<alt>+<delete>` 等多键组合。原因见 `parse_hotkey()` 与 `_matches_key()` 实现.

- 热键请勿与其他软件冲突（例如 VSCode 默认使用 `Ctrl+Shift+C` 打开终端）。

- 若 `restore_clipboard` 设为 `true`，翻译操作不会覆盖剪贴板原有内容。

- 若当前模型引用的平台 `api_key` 非空，程序会自动将请求格式切换为 OpenAI 兼容格式。

- 结果弹窗点击外部或按 `Esc` 关闭。若翻译尚未结束就关闭，会同时中断正在进行的请求，已翻出的部分不再保留。

### prompt_template

顶层的 `prompt_template` 是**默认提示词**，模型未单独写 `prompt_template` 时用它。模板中的 `{target_lang}` 和 `{input_text}` 会分别替换为目标语言与选中文本。示例文件给出的是通用模板，适用于大多数指令模型：

```text
将以下文本翻译为 {target_lang}，注意只需要输出翻译后的结果，不要额外解释：{input_text}
```

若使用下方推荐的 `Hy-MT2-1.8B-Q8_0:latest` 模型，则需改用与之配套的专用模板：

```text
<｜hy_begin▁of▁sentence｜>你是一个翻译助手，专门将输入的文本翻译成{target_lang}。<｜hy_place▁holder▁no▁3｜><｜hy_User｜>{input_text}<｜hy_Assistant｜>
```

**注意**：`prompt_template` 需与所用模型匹配，模板不匹配会明显影响翻译质量。若不同模型需要不同模板，在对应模型里单独写 `prompt_template` 覆盖默认值即可。

## 部署模型与配置 Ollama

1. **安装 Ollama**  

    访问 [Ollama 官网](https://ollama.com) 下载并安装对应系统的版本。

2. **下载翻译模型文件**  

    从模型仓库（如 [Hugging Face](https://huggingface.co/models) 或 [镜像站](https://hf-mirror.com/models)）下载翻译模型，推荐使用 **GGUF** 格式（轻量、适合个人电脑）或 **Safetensors** 格式。  

    **说明**：本代码推荐使用模型 `Hy-MT2-1.8B-Q8_0:latest`，[配置参数](#配置参数) 一节给出了**与之相配套的 prompt**，使用时请一并替换 `prompt_template`。

3. **创建 Modelfile**  

    在模型文件所在目录（或任意方便的位置）创建一个名为 `Modelfile` 的文本文件（注意：**无扩展名**），写入以下内容：

    ```dockerfile
    FROM /绝对路径/你的模型文件.gguf
    ```

    并将 `/绝对路径/你的模型文件.gguf` 替换为实际的文件路径。

4. **构建模型**  

    打开终端（CMD 或 Shell），切换到包含 `Modelfile` 的目录，执行以下命令：

    ```bash
    ollama create 你的模型名称 -f Modelfile
    ```

   `你的模型名称` 可自定义，例如 `my-translator`。

5. **验证模型**  

    在终端中运行 `ollama list` 查看已安装模型，或使用 `ollama run 你的模型名称` 测试翻译功能。

## 使用说明

1. 确保 Ollama 服务已运行（可通过 `ollama serve` 启动）。

2. 首次使用需将 `data/config.example.toml` 复制为 `data/config.toml`，随后按需修改配置项（详见[配置参数](#配置参数)）。

3. 运行 `python src/main.py`（或用 `pixi run start`）。

4. 在任意应用中选中文本，按下翻译热键（默认 `Ctrl+Shift+E`），即可看到翻译结果弹窗。

5. 使用退出热键（默认 `Ctrl+Shift+Q`）可关闭程序。

## 平台支持

- **Windows**：完全支持。
- **Linux**：部分支持，具体依赖项如下（由 DeepSeek 生成，请谨慎甄别）：

| 库 | 支持情况 | 详情 |
| :----: | :----: | --- |
| `tkinter` | 需要图形界面 | Tkinter 是 Python 标准 GUI 库，在 Linux 上需安装 `python3-tk` 包，且系统需运行 X11 或 Wayland 图形环境（无图形界面的服务器无法使用） |
| `pyautogui` | 部分支持 | 用于获取鼠标位置。在 Linux 上依赖 X11 或 `uinput`，需安装 `python3-xlib`、`scrot` 等工具。若使用 Wayland，部分功能可能受限 |
| `pynput` | 部分支持 | 用于监听和控制输入设备。同样依赖 X11 或 `uinput`，可能需要图形界面或 root 权限 |
