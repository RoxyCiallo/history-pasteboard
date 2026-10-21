"""M2 手动验证脚本：启动剪贴板监听，实时打印入库结果。

用法：
    python tools/clipboard_watch.py               # 监听 60 秒，数据写到 build/watch/
    python tools/clipboard_watch.py --seconds 120
    python tools/clipboard_watch.py --real        # 写入真实数据目录（data/ 或 %LOCALAPPDATA%）

复制几段文字、一张截图、一个图片文件，观察是否逐条打印。
"""

from __future__ import annotations

import argparse
import logging
import queue
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import clipboard  # noqa: E402
import db  # noqa: E402
import storage  # noqa: E402


def _preview(item: dict) -> str:
    """一条记录的单行摘要。"""
    if item["kind"] == "image":
        return f"图片 {item['width']}x{item['height']} {item['byte_size'] or 0} 字节"
    text = (item["text_content"] or "").replace("\n", " ")
    return text if len(text) <= 40 else text[:40] + "…"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="剪贴板监听手动验证")
    parser.add_argument("--seconds", type=int, default=60, help="监听时长（默认 60 秒）")
    parser.add_argument("--real", action="store_true", help="写入真实数据目录而不是 build/watch")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

    if args.real:
        data_dir = storage.resolve_data_dir()
    else:
        data_dir = storage.ensure_layout(ROOT / "build" / "watch" / "data")
    database = db.Database(storage.db_path(data_dir))
    events: queue.Queue = queue.Queue()
    listener = clipboard.ClipboardListener(database, data_dir, events)
    listener.start()

    print(f"数据目录：{data_dir}")
    print(f"开始监听 {args.seconds} 秒，现在去复制文字 / 截图 / 图片文件（Ctrl+C 提前结束）\n")
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            try:
                _, event = events.get(timeout=0.5)
            except queue.Empty:
                continue
            item = database.get_item(event["id"])
            if item is None:
                continue
            flag = "新增" if event["created"] else "刷新"
            mark = "（敏感）" if item["is_private"] else ""
            print(f"  [{flag}] {_preview(item)}{mark}")
    except KeyboardInterrupt:
        print("\n已手动中断")
    finally:
        listener.stop()
        total = database.count()
        print(f"\n监听结束：当前共 {total} 条记录")
        for item in database.list_items(limit=5):
            print(f"  - {_preview(item)}")
        database.close()

    if not args.real:
        print(f"\n（本次数据在 {data_dir}，未写入真实目录）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
