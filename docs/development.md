# 开发说明

## 安装与运行

### 使用 pixi

```bash
pixi install
pixi run start     # 启动程序
pixi run test      # 跑测试
pixi run config show
```

### 不使用 pixi

需要 Python 3.11+（开发环境为 3.14）：

```bash
python -m venv .venv
.venv\Scripts\activate                 # Windows
# source .venv/bin/activate            # Linux/macOS

python -m pip install pyautogui pynput pyperclip requests pytest
python src/main.py                     # 启动
python -m pytest                       # 测试
python src/cli.py show                 # 命令行配置
```

## 项目结构

| 路径 | 职责 |
| --- | --- |
| `src/main.py` | 程序入口，组装各子系统、热键状态机与翻译主流程 |
| `src/config.py` | 配置文件定位、读取与校验 |
| `src/api.py` | 请求构造、重定向处理、token 统计提取与翻译调用 |
| `src/text.py` | 选中文本的清洗 |
| `src/clipboard.py` | 模拟 Ctrl+C 读取剪贴板 |
| `src/hotkeys.py` | 热键解析与按键匹配 |
| `src/ui.py` | Tkinter 弹窗、状态提示框、流式增量显示 |
| `src/logger.py` | 统一日志格式、计时与 token 用量统计 |
| `src/cli.py` | 命令行配置工具 |
| `data/config.example.toml` | 配置模板，用户配置 `config.toml` 不入库 |
| `tests/` | pytest 测试套件 |

## 测试

测试通过 `tests/conftest.py` 在导入 `main` 之前准备临时配置，因此不需要本机真实的 `config.toml`。改动核心逻辑后请运行：

```bash
pixi run test
```

## 平台支持

| 平台 | 支持情况 |
| --- | --- |
| Windows | 完全支持 |
| Linux | 部分支持，需要图形环境与 X11/Wayland |
| macOS | 未验证 |

Linux 下各依赖的注意事项：

| 库 | 说明 |
| --- | --- |
| `tkinter` | 需安装 `python3-tk`，并运行 X11 或 Wayland 图形环境 |
| `pyautogui` | 依赖 X11 或 `uinput`，可能需安装 `python3-xlib`、`scrot`；Wayland 下部分功能受限 |
| `pynput` | 同样依赖 X11 或 `uinput`，可能需要图形界面或 root 权限 |
