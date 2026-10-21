#!/usr/bin/env python
"""开发日志自动记录工具。

用法：
    python tools/devlog.py done "完成剪贴板监听线程"
    python tools/devlog.py todo "补图片上限测试"
    python tools/devlog.py note "剪贴板在远程桌面下偶发失败"
    python tools/devlog.py status                 # 查看当天日志
    python tools/devlog.py path                   # 只输出当天日志路径

可选：--date 2026-10-20 指定日期（默认取本机当天）。
--date 也支持 yesterday / tomorrow。

行为：若当天日志不存在，则用 devlog/TEMPLATE.md 创建，再向对应小节末尾
追加一条 "- HH:MM 内容"。小节缺失时自动补齐。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEVLOG_DIR = ROOT / "devlog"
TEMPLATE = DEVLOG_DIR / "TEMPLATE.md"

SECTIONS = {
    "done": "完成",
    "todo": "待办",
    "note": "问题与风险",
    "plan": "明日计划",
    "goal": "今日目标",
}

DEFAULT_TEMPLATE = """# {date} 开发日志

## 今日目标

## 完成

## 待办

## 问题与风险

## 明日计划
"""


def _resolve_date(text: str | None) -> _dt.date:
    """把 --date 参数解析为日期；None 表示今天。"""
    if not text:
        return _dt.date.today()
    lowered = text.strip().lower()
    today = _dt.date.today()
    if lowered == "yesterday":
        return today - _dt.timedelta(days=1)
    if lowered == "tomorrow":
        return today + _dt.timedelta(days=1)
    return _dt.date.fromisoformat(lowered)


def _day_file(day: _dt.date) -> Path:
    """返回某天的日志文件路径。"""
    return DEVLOG_DIR / f"{day.isoformat()}.md"


def _read_template(day: _dt.date) -> str:
    """读取模板；模板缺失时用内置模板。"""
    if TEMPLATE.exists():
        text = TEMPLATE.read_text(encoding="utf-8")
    else:
        text = DEFAULT_TEMPLATE
    return text.replace("{date}", day.isoformat())


def ensure_file(day: _dt.date) -> Path:
    """确保当天日志存在，返回其路径。"""
    DEVLOG_DIR.mkdir(parents=True, exist_ok=True)
    path = _day_file(day)
    if not path.exists():
        path.write_text(_read_template(day), encoding="utf-8", newline="\n")
    return path


def append_entry(path: Path, section: str, content: str) -> None:
    """向指定小节的末尾追加一条带时间戳的条目。"""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    header = f"## {section}"

    start = next((i for i, line in enumerate(lines) if line.strip() == header), None)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([header, "", f"- {_stamp()} {content}"])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        return

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break

    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1

    entry = f"- {_stamp()} {content}"
    lines.insert(insert_at, entry)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _stamp() -> str:
    """当前时间 HH:MM。"""
    return _dt.datetime.now().strftime("%H:%M")


def _setup_stdout() -> None:
    """把标准输出切到 UTF-8，避免 Windows 管道/重定向下中文乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _print_safe(text: str) -> None:
    """在控制台编码不支持时也不崩溃地打印。"""
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8", "replace") + b"\n")


def main(argv: list[str] | None = None) -> int:
    _setup_stdout()
    parser = argparse.ArgumentParser(description="记录开发日志")
    parser.add_argument("--date", dest="date", default=None, help="日期 YYYY-MM-DD / yesterday / tomorrow")
    parser.add_argument(
        "action",
        choices=["done", "todo", "note", "plan", "goal", "status", "path"],
        help="done/todo/note/plan/goal 追加条目；status 显示当天日志；path 输出路径",
    )
    parser.add_argument("content", nargs="*", help="条目内容")
    args = parser.parse_args(argv)

    day = _resolve_date(args.date)
    path = ensure_file(day)

    if args.action == "path":
        _print_safe(str(path))
        return 0

    if args.action == "status":
        _print_safe(path.read_text(encoding="utf-8"))
        return 0

    content = " ".join(args.content).strip()
    if not content:
        _print_safe("内容为空，未记录。用法：python tools/devlog.py done \"做了什么\"")
        return 2

    append_entry(path, SECTIONS[args.action], content)
    _print_safe(f"已记录到 {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
