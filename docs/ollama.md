# Ollama 部署

本地跑翻译模型需要 Ollama 服务。

## 1. 安装 Ollama

访问 [Ollama 官网](https://ollama.com) 下载并安装对应系统的版本。

## 2. 下载模型文件

从 [Hugging Face](https://huggingface.co/models) 或[镜像站](https://hf-mirror.com/models)下载模型，推荐 **GGUF** 格式（轻量，适合个人电脑）或 Safetensors 格式。推荐模型与配套提示词见 [模型与提示词](models.md)。

## 3. 创建 Modelfile

在模型文件所在目录创建一个名为 `Modelfile` 的文件（无扩展名），内容：

```dockerfile
FROM /绝对路径/你的模型文件.gguf
```

把路径换成实际的文件路径。若模型是 Safetensors 目录，则写该目录的绝对路径。

## 4. 构建模型

在 `Modelfile` 所在目录执行：

```bash
ollama create 你的模型名称 -f Modelfile
```

例如 `ollama create my-translator -f Modelfile`。

## 5. 验证

```bash
ollama list                 # 查看已安装模型
ollama run 你的模型名称      # 终端里试一句翻译
```

## 6. 接入 LLMTranslator

1. 启动 Ollama 服务（`ollama serve`，桌面版通常常驻后台）。
2. 在 `data/config.toml` 里新增一个 `api_key = ""` 的平台，`base_url` 填 `http://localhost:11434/api/generate`。
3. 新增一个模型指向该平台，`model_name` 填第 4 步起的名字，并按模型设置 `prompt_template`。
4. 把 `active_model` 改成这个模型名，重启程序。

完整示例见 [配置参考](configuration.md#平台与模型)。
