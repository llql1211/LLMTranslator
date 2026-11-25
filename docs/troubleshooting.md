# 故障排查

## 按热键没反应，或提示「未获取到文本」

- 确认按热键前**已经选中了文本**，且该场景支持复制（图片里的文字不行）。
- 热键只支持「标准修饰键 + 单个可打印字符」，不支持 F1–F12、方向键或多键组合。
- 检查是否与其他软件的快捷键冲突，例如 VSCode 的 `Ctrl+Shift+C`。
- 配置在启动时读取一次，改完热键要**重启程序**。

## 请求返回 405

多半是 http 地址被 301 重定向到 https，服务端只接受 POST。解决：

- 云端 API 的 `base_url` 直接填 `https://` 开头的根地址；
- `api_key` 非空时填服务根地址即可，程序会自动补全 `/v1/chat/completions`，不要填成带 `/v1` 的旧地址。

## token 统计显示「不可用」

- Ollama 原生格式、OpenAI 非流式请求都会返回统计；
- OpenAI 流式请求需要服务端支持 `stream_options`，部分兼容服务不支持。此时把 `stream_include_usage` 设为 `false`，日志仍会显示耗时。

## 译文弹窗颜色不对

显式设置了 `theme` 后，弹窗颜色只看 `*_light` / `*_dark` 两组主题字段，旧的 `tooltip_background_color` / `tooltip_text_color` 不再生效。详见 [配置参考](configuration.md#深浅模式)。

## 弹窗位置或大小不合适

- `tooltip_offset_x` / `tooltip_offset_y` 控制相对鼠标的偏移；
- `tooltip_result_max_width` / `tooltip_result_max_height` 控制宽度（字符数）与高度（行数），超出上限后弹窗内部可滚动。

## 翻译质量不理想

- 确认 `prompt_template` 与所用模型匹配，模型专用提示词会覆盖顶层默认值；推荐模型的模板见 [模型与提示词](models.md)。
- 生成参数（`temperature`、`top_p` 等）采用「写了才发送」策略，按需调整或注释掉，见 [配置参考](configuration.md#生成参数)。

## 其他

- 结果弹窗点击外部或按 `Esc` 关闭；翻译未结束就关闭会中断请求，已翻出的部分不再保留。
- `restore_clipboard = true` 可在翻译后恢复原剪贴板内容。
- 若 `api_key` 非空，程序会自动改用 OpenAI 兼容请求格式；Ollama 本地模式请留空 `api_key`。
