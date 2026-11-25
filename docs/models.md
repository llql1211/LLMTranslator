# 模型与提示词

## 提示词模板

顶层的 `prompt_template` 是默认提示词，模型未单独写 `prompt_template` 时用它。`{target_lang}` 和 `{input_text}` 会分别替换为目标语言与选中文本。

通用模板，适用于大多数指令模型：

```text
将以下文本翻译为 {target_lang}，注意只需要输出翻译后的结果，不要额外解释：{input_text}
```

若不同模型需要不同模板，在对应模型里单独写 `prompt_template` 覆盖默认值即可。写法示例见 [配置参考](configuration.md#平台与模型)。

模板需与所用模型匹配，不匹配会明显影响翻译质量。本地模型的下载与导入步骤见 [Ollama 部署](ollama.md)。

## 推荐模型

可使用 `Hy-MT2-1.8B`。
