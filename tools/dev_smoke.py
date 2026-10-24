"""M1 数据层冒烟脚本：造一批假数据，肉眼确认排序、置顶、搜索、图片。

用法：
    python tools/dev_smoke.py          # 造数据、打印、清理
    python tools/dev_smoke.py --keep   # 保留临时目录，便于事后查看文件

数据写进 ``build/smoke/``，不会碰真实 ``data/``。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import config  # noqa: E402
import db  # noqa: E402
import storage  # noqa: E402

SAMPLE_TEXTS = [
    "会议纪要：下周三下午三点评审界面初稿",
    "SELECT * FROM items WHERE pinned = 1 ORDER BY updated_at DESC;",
    "收货地址：北京市海淀区中关村大街 1 号",
    "https://example.com/docs/pasteboard",
    "客户反馈：搜索希望支持拼音首字母",
    "TODO: 补一张图片卡片的占位图",
    "版本号 v0.1.0 对应里程碑 M1",
    "这段文字比较长，用来检查卡片上的三行截断是否正常显示，后面的内容应该被省略号截掉。",
    "git commit -m \"M1: 数据层完成\"",
    "配色主色 #4A90D9，背景 #F5FAFF",
    "周报要点：完成数据层，开始系统能力层",
    "身份证号占位 110101199001011234",
    "临时密码示例 P@ssw0rd（模拟私密内容）",
    "复制这句话，然后在主界面搜索“数据层”应该能找到",
    f"路径：{storage.app_dir()}",
    "聊天记录：明天记得把合同发我",
    "命令：python -m unittest discover -s tests -v",
    "重复内容测试：重复内容测试",
]


def build_sample_image() -> "object":
    """画一张简单的示意图片（不依赖字体）。"""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (480, 300), (234, 244, 253))
    draw = ImageDraw.Draw(image)
    draw.rectangle([40, 50, 440, 250], fill=(74, 144, 217))
    draw.rectangle([70, 90, 410, 210], fill=(245, 250, 255))
    return image


def seed(database: db.Database, data_dir: Path, base_time: _dt.datetime) -> None:
    """写入示例数据：18 条文本 + 1 条置顶 + 1 张图片。"""
    for index, text in enumerate(SAMPLE_TEXTS):
        stamp = (base_time - _dt.timedelta(minutes=17 * (len(SAMPLE_TEXTS) - index))).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        database.upsert_item(
            kind="text",
            content_hash=storage.sha256_text(text),
            text_content=text,
            is_private="密码" in text,
            now=stamp,
        )

    pinned_text = "记得置顶：常用邮箱 someone@example.com"
    pinned_id, _ = database.upsert_item(
        kind="text",
        content_hash=storage.sha256_text(pinned_text),
        text_content=pinned_text,
        now=(base_time - _dt.timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%S"),
    )
    database.toggle_pin(pinned_id, now=(base_time - _dt.timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%S"))

    payload = storage.save_image(build_sample_image(), data_dir)
    if payload is not None:
        database.upsert_item(
            kind="image",
            content_hash=payload["content_hash"],
            image_path=payload["image_path"],
            thumb_path=payload["thumb_path"],
            width=payload["width"],
            height=payload["height"],
            byte_size=payload["byte_size"],
            now=(base_time - _dt.timedelta(minutes=8)).strftime("%Y-%m-%dT%H:%M:%S"),
        )


def describe(item: dict) -> str:
    """把一条记录压成一行便于阅读的文本。"""
    flags = []
    if item["pinned"]:
        flags.append("置顶")
    if item["is_private"]:
        flags.append("私密")
    flag_text = f"[{'/'.join(flags)}] " if flags else ""

    kind_name = {"text": "文字", "image": "图片"}.get(item["kind"], item["kind"])
    if item["kind"] == "image":
        body = f"图片 {item['width']}x{item['height']} {_human_size(item['byte_size'] or 0)}"
    else:
        text = (item["text_content"] or "").replace("\n", " ")
        body = text if len(text) <= 34 else text[:34] + "…"
    return f"{flag_text}[{kind_name}] {item['updated_at']}  {body}"


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def show(database: db.Database, config_obj: config.Config) -> None:
    """打印列表与搜索结果。"""
    total = database.count()
    items = database.list_items()
    print(f"记录总数：{total}（置顶 {sum(1 for row in items if row['pinned'])} 条）")
    print(f"保留期：{config_obj.retention_days} 天\n")
    print("--- 按「置顶 + 时间倒序」排列 ---")
    for index, item in enumerate(items, start=1):
        print(f"{index:>2}. {describe(item)}")

    keyword = "数据层"
    hits = database.search(keyword)
    print(f"\n--- 搜索「{keyword}」命中 {len(hits)} 条 ---")
    for item in hits:
        print(f"    {describe(item)}")

    wide_hits = database.search("%")
    print(f"--- 搜索「%」命中 {len(wide_hits)} 条（验证通配符已被转义）---")
    for item in wide_hits:
        print(f"    {describe(item)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M1 数据层冒烟")
    parser.add_argument("--keep", action="store_true", help="保留临时目录")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    work_dir = ROOT / "build" / "smoke"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    data_dir = storage.ensure_layout(work_dir / "data")
    database = db.Database(storage.db_path(data_dir))
    try:
        seed(database, data_dir, _dt.datetime.now())
        show(database, config.Config(database))
        print(f"\n数据目录：{data_dir}")
        print(f"图片文件：{len(list((data_dir / storage.IMAGES_DIR_NAME).glob('*.png')))} 张原图，"
              f"{len(list((data_dir / storage.THUMBS_DIR_NAME).glob('*.png')))} 张缩略图")
    finally:
        database.close()

    if args.keep:
        print(f"已保留：{work_dir}")
    else:
        shutil.rmtree(work_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
