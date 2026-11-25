"""命令行查看与修改配置。

用法：

    python src/cli.py show
    python src/cli.py get target_lang
    python src/cli.py set target_lang Japanese
    python src/cli.py set platforms.example-ollama.api_key sk-xxx

修改采用逐行替换，保留原文件中的注释与排版；键不存在时自动补写。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib

import config

_HEADER_ARRAY = re.compile(r"^\s*\[\[([A-Za-z0-9_-]+)\]\]\s*$")
_HEADER_SINGLE = re.compile(r"^\s*\[([A-Za-z0-9_-]+)\]\s*$")
_KEY_LINE = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*=\s*(.*)$")
_LEADING_SPACE = re.compile(r"\s*")


def _format_value(value: object, key: str = "") -> str:
    """把配置值转成适合终端阅读的文本，密钥一律遮蔽"""
    if key == "api_key" and value:
        return "****** (已隐藏)"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _lookup(cfg: dict, dotted_key: str) -> object:
    """
    按 a.b.c 查找配置值

    平台与模型是表格数组，用其中各项的 name 字段作为索引，
    例如 platforms.my-ollama.api_key
    """
    current: object = cfg
    for part in dotted_key.split("."):
        if isinstance(current, list):
            match = next(
                (item for item in current if isinstance(item, dict) and item.get("name") == part),
                None,
            )
            if match is None:
                raise KeyError(f"找不到名为 {part} 的配置项")
            current = match
        elif isinstance(current, dict):
            if part not in current:
                raise KeyError(f"未知配置项：{dotted_key}")
            current = current[part]
        else:
            raise KeyError(f"无法继续查找：{dotted_key}")
    return current


def _split_value_comment(raw: str) -> tuple[str, str]:
    """拆出 TOML 值与行内注释，注释部分保留前置空格"""
    quote = ""
    for index, char in enumerate(raw):
        if quote:
            if char == quote and (index == 0 or raw[index - 1] != "\\"):
                quote = ""
        elif char in ('"', "'"):
            quote = char
        elif char == "#":
            return raw[:index], raw[index:]
    return raw, ""


def _parse_toml_value(raw: str) -> object:
    """解析配置行中的值，失败时按纯文本处理"""
    value_part, _ = _split_value_comment(raw)
    value_part = value_part.strip()
    if not value_part:
        return ""
    try:
        return tomllib.loads(f"v = {value_part}\n")["v"]
    except (tomllib.TOMLDecodeError, KeyError):
        return value_part


def _serialize_input(raw: str) -> str:
    """把命令行输入转成 TOML 字面量；未加引号的输入按字符串处理"""
    candidate = raw.strip()
    try:
        value = tomllib.loads(f"v = {candidate}\n")["v"]
    except (tomllib.TOMLDecodeError, KeyError):
        value = candidate
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (str, dict, list)):
        return json.dumps(value, ensure_ascii=False)
    raise ValueError(f"不支持的配置值类型：{type(value).__name__}")


def _key_line_match(line: str, key: str):
    match = _KEY_LINE.match(line)
    return match if match and match.group(1) == key else None


def _table_blocks(lines: list[str]) -> list[tuple[str, int, int]]:
    """扫描所有表头，返回 (表名, 内容起点, 内容终点)；每个表头对应一个块"""
    blocks = []
    for index, line in enumerate(lines):
        match = _HEADER_ARRAY.match(line) or _HEADER_SINGLE.match(line)
        if not match:
            continue
        end = len(lines)
        for later in range(index + 1, len(lines)):
            if _HEADER_ARRAY.match(lines[later]) or _HEADER_SINGLE.match(lines[later]):
                end = later
                break
        prefix = "array" if _HEADER_ARRAY.match(line) else "table"
        blocks.append((f"{prefix}:{match.group(1)}", index + 1, end))
    return blocks


def _locate(lines: list[str], dotted_key: str) -> tuple[str, int, str, bool]:
    """
    定位配置项，返回 (替换/插入, 行号, 键名, 是否嵌套)

    顶层键在第一个表头之前查找；表数组项按 name 找到对应块，再找其中的字段。
    """
    parts = dotted_key.split(".")
    if len(parts) == 1:
        table, target = "", parts[0]
    elif len(parts) == 3:
        table, entry_name, target = parts
    else:
        raise KeyError("只支持顶层键（target_lang）或表数组字段（models.xxx.model_name）")

    if table:
        blocks = [block for block in _table_blocks(lines) if block[0] == f"array:{table}"]
        if not blocks:
            raise KeyError(f"配置文件中没有 [[{table}]] 表数组")
        for _name, start, end in blocks:
            name_line = next((j for j in range(start, end) if _key_line_match(lines[j], "name")), None)
            if name_line is None:
                continue
            found_name = _parse_toml_value(_key_line_match(lines[name_line], "name").group(2))
            if found_name != entry_name:
                continue
            field_line = next((j for j in range(start, end) if _key_line_match(lines[j], target)), None)
            if field_line is not None:
                return "replace", field_line, target, True
            return "insert", end, target, True
        raise KeyError(f"找不到名为 {entry_name} 的配置项")

    first_header = next(
        (i for i, line in enumerate(lines) if _HEADER_ARRAY.match(line) or _HEADER_SINGLE.match(line)),
        len(lines),
    )
    found = next((i for i in range(first_header) if _key_line_match(lines[i], target)), None)
    if found is not None:
        return "replace", found, target, False
    return "insert", first_header, target, False


def _replace_value(line: str, serialized: str) -> str:
    equal = line.find("=")
    if equal < 0:
        raise ValueError("配置行格式异常，无法自动修改，请手动编辑")
    prefix, rest = line[:equal + 1], line[equal + 1:]
    value_part, comment = _split_value_comment(rest)
    leading = _LEADING_SPACE.match(rest).group()
    # 保留值后面的空格与换行，行内注释前的间隔也不会丢
    trailing = value_part[len(value_part.rstrip()):]
    return prefix + leading + serialized + trailing + comment


def set_value(path: str, dotted_key: str, raw_value: str) -> tuple[object, object]:
    """
    修改配置项，返回 (旧值, 新值)

    写入前做语法校验，写入后做语义校验；语义校验失败时回滚原文件。
    """
    with open(path, "r", encoding="utf-8", newline="") as file:
        original = file.read()
    lines = original.splitlines(keepends=True)
    if not lines:
        raise ValueError("配置文件为空")

    try:
        before = _lookup(config.load_config(path), dotted_key)
    except KeyError:
        before = None

    serialized = _serialize_input(raw_value)
    action, index, target, nested = _locate(lines, dotted_key)

    newline = "\r\n" if "\r\n" in original else "\n"
    if action == "replace":
        lines[index] = _replace_value(lines[index], serialized)
    else:
        if index > 0 and not lines[index - 1].endswith(("\n", "\r")):
            lines[index - 1] += newline
        indent = "  " if nested else ""
        lines.insert(index, f"{indent}{target} = {serialized}{newline}")

    updated = "".join(lines)
    tomllib.loads(updated)  # 语法不对就别落盘
    with open(path, "w", encoding="utf-8", newline="") as file:
        file.write(updated)
    try:
        config.load_config(path)  # 语义校验：必填项与类型约束
    except config.ConfigError:
        with open(path, "w", encoding="utf-8", newline="") as file:
            file.write(original)
        raise
    return before, _parse_toml_value(serialized)


def show_config(path: str) -> None:
    """打印全部配置项，并标出当前生效的模型"""
    cfg = config.load_config(path)
    print(f"配置文件：{path}\n")

    for key, value in cfg.items():
        if not isinstance(value, list):
            print(f"{key} = {_format_value(value, key)}")

    for key in ("platforms", "models"):
        if key not in cfg:
            continue
        print(f"\n[[{key}]]")
        for item in cfg[key]:
            for field, value in item.items():
                print(f"  {field} = {_format_value(value, field)}")
            print()

    active = config.resolve_active_model(cfg)
    print(
        f"当前生效：模型 {active['name']}"
        f"（平台 {active['platform']}，模型名 {active['model_name']}）"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="查看与修改 LLMTranslator 配置")
    parser.add_argument("-c", "--config", help="指定配置文件路径（默认同启动时一致）")
    sub = parser.add_subparsers(dest="command")
    show = sub.add_parser("show", help="显示当前配置（默认）")
    get = sub.add_parser("get", help="读取单个配置项")
    get.add_argument("key", help="配置键，如 target_lang 或 models.mymodel.model_name")
    set_parser = sub.add_parser("set", help="修改配置项")
    set_parser.add_argument("key", help="配置键")
    set_parser.add_argument("value", help="新值；未加引号的文本按字符串处理")
    # 子命令后也能写 -c，用 SUPPRESS 避免覆盖前面已解析出的值
    for command in (show, get, set_parser):
        command.add_argument("-c", "--config", default=argparse.SUPPRESS, help="指定配置文件路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = config.resolve_config_path(args.config)
    try:
        if args.command in (None, "show"):
            show_config(path)
        elif args.command == "get":
            value = _lookup(config.load_config(path), args.key)
            print(_format_value(value, args.key.split(".")[-1]))
        else:
            before, after = set_value(path, args.key, args.value)
            field = args.key.split(".")[-1]
            print(f"已修改 {args.key}：{_format_value(before, field)} → {_format_value(after, field)}")
    except (config.ConfigError, KeyError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
