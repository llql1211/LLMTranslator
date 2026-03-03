# LLMTranslator

## 目录

- [简介](#简介)
- [平台支持](#平台支持)
- [部署模型与配置 Ollama](#部署模型与配置-ollama)
- [修改参数配置](#修改参数配置)

## 简介

LLMTranslator 利用 Ollama 的翻译模型，将选中的文本翻译为目标语言，并通过弹窗形式显示在鼠标光标右下角。  
程序通过 `pynput` 监听快捷键，触发翻译流程：模拟 `Ctrl+C` 复制选中文本，读取剪贴板内容，调用 Ollama API 翻译，最后使用 `tkinter` 显示结果。

**注意**：该工具依赖文本选中能力，因此仅适用于可选中文本的场景（不支持图片翻译）。

## 平台支持

- **Windows**：完全支持。
- **Linux**：部分支持，具体依赖项如下：

| 库 | 支持情况 | 详情 |
| :----: | :----: | :---- |
| `tkinter` | 需要图形界面 | Tkinter 是 Python 标准 GUI 库，在 Linux 上需安装 `python3-tk` 包，且系统需运行 X11 或 Wayland 图形环境（无图形界面的服务器无法使用） |
| `pyautogui` | 部分支持 | 用于模拟鼠标键盘操作。在 Linux 上依赖 X11 或 `uinput`，需安装 `python3-xlib`、`scrot` 等工具。若使用 Wayland，部分功能可能受限 |
| `pynput` | 部分支持 | 用于监听和控制输入设备。同样依赖 X11 或 `uinput`，可能需要图形界面或 root 权限 |

## 部署模型与配置 Ollama

1. **安装 Ollama**  
    访问 [Ollama 官网](https://ollama.com) 下载并安装对应系统的版本。

2. **下载翻译模型文件**  
    从模型仓库（如 [Hugging Face](https://huggingface.co/models) 或 [镜像站](https://hf-mirror.com/models)）下载翻译模型，推荐使用 **GGUF** 格式（轻量、适合个人电脑）或 **Safetensors** 格式。

3. **创建 Modelfile**  
    在模型文件所在目录（或任意方便的位置）创建一个名为 `Modelfile` 的文本文件（注意：**无扩展名**），写入以下内容：

    ```dockerfile
    FROM /绝对路径/你的模型文件.gguf
    ```

    > 请将 `/绝对路径/你的模型文件.gguf` 替换为实际的文件路径。

4. **构建模型**  
    打开终端（CMD 或 Shell），切换到包含 `Modelfile` 的目录，执行以下命令：

    ```bash
    ollama create 你的模型名称 -f Modelfile
    ```

   `你的模型名称` 可自定义，例如 `my-translator`。

5. **验证模型**  
    在终端中运行 `ollama list` 查看已安装模型，或使用 `ollama run 你的模型名称` 测试翻译功能。

## 修改参数配置

在 `LLMTranslator.py` 中可调整以下参数：

- **Ollama API 地址**  
  默认为 `http://localhost:11434`，通常无需修改。

- **模型名称**  
  填写上一步构建的模型名称，推荐加上 `:latest` 标签，如 `my-translator:latest`。

- **热键设置**  
  - 翻译热键：默认 `Ctrl+Shift+E`  
  - 退出热键：默认 `Ctrl+Shift+Q`  
  **注意**：请勿与其他软件热键冲突（例如 VSCode 默认使用 `Ctrl+Shift+C` 打开终端）。

- **目标语言**  
  默认 `Chinese`，可按需修改（如 `English`、`Japanese`）。

- **剪贴板恢复**  
  是否在获取选中文本后恢复原始剪贴板内容：默认 `False`。若设为 `True`，翻译操作不会覆盖剪贴板原有内容。

## 使用说明

1. 确保 Ollama 服务已运行（可通过 `ollama serve` 启动）。
2. 运行 `python LLMTranslator.py`。
3. 在任意应用中选中文本，按下翻译热键，即可看到翻译结果弹窗。
4. 使用退出热键可关闭程序。
