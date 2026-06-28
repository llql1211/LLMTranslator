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

所有配置集中在项目根目录的 `config.json` 中：

| 配置路径 | 字段 | 说明 | 默认值 |
| :---: | :--- | :--- | :--- |
| `api` | `base_url` | 翻译模型 API 地址 | `http://localhost:11434/api/generate` （Ollama） |
| | `api_key` | API 密钥（留空用 Ollama 原生格式，非空切换 OpenAI 兼容格式） | `""` |
| | `model_name` | 模型名称 | `HY-MT1.5-1.8B-Q8_0:latest` |
| `translation` | `target_lang` | 目标语言 | `Chinese` |
| | `prompt_template` | 发送给模型的 prompt 模板，可用 `{target_lang}` 和 `{input_text}` 占位符 | （见下方） |
| `hotkeys` | `translate` | 翻译热键（见下方注释） | `<ctrl>+<shift>+e` |
| | `quit` | 退出热键（见下方注释） | `<ctrl>+<shift>+q` |
| `tooltip` | `background_color` | 弹窗背景色 | `#FFFFE0` |
| | `offset_x` | 弹窗相对于鼠标光标的 X 偏移 | `20` |
| | `offset_y` | 弹窗相对于鼠标光标的 Y 偏移 | `20` |
| | `result_max_width` | 弹窗最大宽度（字符数） | `30` |
| | `result_max_height` | 弹窗最大行数 | `8` |
| | `duration_ms` | 错误提示弹窗的持续时间（毫秒） | `1500` |
| `restore_clipboard` | — | 是否在获取文本后恢复原始剪贴板内容 | `false` |

**注意**：

- 不建议大幅度修改热键。当前热键解析实现只支持**标准修饰键（`ctrl`、`shift`、`alt`、`cmd`）+ 单个可打印字符**的组合，不支持功能键（F1–F12）、方向键、`<ctrl>+<alt>+<delete>` 等多键组合。原因见 `parse_hotkey()` 与 `_matches_key()` 实现.

- 热键请勿与其他软件冲突（例如 VSCode 默认使用 `Ctrl+Shift+C` 打开终端）。

- 若 `restore_clipboard` 设为 `true`，翻译操作不会覆盖剪贴板原有内容。

- 若 `api_key` 非空，程序会自动将请求地址切换为 OpenAI 兼容格式。

### 默认 prompt_template

```text
你是一个翻译助手，专门将输入的文本翻译成{target_lang}。<｜hy_place▁holder▁no▁3｜><｜hy_User｜>{input_text}<｜hy_Assistant｜>
```

若使用的模型与默认模型 `HY-MT1.5-1.8B-Q8_0:latest` 不同，需要修改 `prompt_template`。

## 部署模型与配置 Ollama

1. **安装 Ollama**  

    访问 [Ollama 官网](https://ollama.com) 下载并安装对应系统的版本。

2. **下载翻译模型文件**  

    从模型仓库（如 [Hugging Face](https://huggingface.co/models) 或 [镜像站](https://hf-mirror.com/models)）下载翻译模型，推荐使用 **GGUF** 格式（轻量、适合个人电脑）或 **Safetensors** 格式。  

    **说明**：本代码使用模型 `HY-MT1.5-1.8B-Q8_0:latest`，并内置了**与之相配套的 prompt**，因此推荐下载该模型。

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

2. 如有需要，修改 `config.json` 中的配置项。

3. 运行 `python main.py`。

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
