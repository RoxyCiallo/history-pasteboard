"""生成打包用图标 ``assets/app.ico``（开发期脚本，只依赖 Pillow）。

用法::

    python make_icon.py

图标：淡蓝圆角方块 + 白色剪贴板 + 三条主色横线，先按 4 倍超采样绘制再缩小，
避免 Pillow 画圆角时没有抗锯齿导致的锯齿边。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "assets" / "app.ico"

# ---- 与 docs/03-design-spec.md 的设计令牌保持一致 -------------------
COLOR_BG = "#4A90D9"       # PRIMARY
COLOR_BOARD = "#FFFFFF"    # BG_CARD
COLOR_LINE = "#4A90D9"     # PRIMARY
COLOR_CLIP = "#E3F0FC"     # BG_HEADER

SUPERSAMPLE = 4
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw_icon(size: int = 1024) -> Image.Image:
    """按给定画布尺寸绘制图标（坐标按比例换算）。"""
    canvas = size * SUPERSAMPLE
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def scaled(value: float) -> float:
        return value / 1024 * canvas

    # 背景圆角方块
    draw.rounded_rectangle(
        [scaled(32), scaled(32), scaled(992), scaled(992)],
        radius=scaled(220),
        fill=COLOR_BG,
    )
    # 剪贴板主体
    board = [scaled(268), scaled(236), scaled(756), scaled(848)]
    draw.rounded_rectangle(board, radius=scaled(64), fill=COLOR_BOARD)
    # 顶部夹子
    draw.rounded_rectangle(
        [scaled(392), scaled(168), scaled(632), scaled(304)],
        radius=scaled(48),
        fill=COLOR_CLIP,
        outline=COLOR_BOARD,
        width=int(scaled(18)),
    )
    # 三条内容横线
    line_left = scaled(376)
    line_width_base = scaled(272)
    for index, ratio in enumerate((1.0, 0.82, 0.62)):
        top = scaled(456 + index * 128)
        bottom = top + scaled(56)
        draw.rounded_rectangle(
            [line_left, top, line_left + line_width_base * ratio, bottom],
            radius=scaled(28),
            fill=COLOR_LINE,
        )

    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> int:
    if not OUTPUT.parent.exists():
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    # Pillow 保存 ICO 时以最大尺寸绘制，其余尺寸由它自行缩放。
    draw_icon(max(ICON_SIZES)).save(OUTPUT, format="ICO", sizes=[(s, s) for s in ICON_SIZES])
    print(f"已生成 {OUTPUT.relative_to(ROOT)}（{OUTPUT.stat().st_size} 字节，尺寸 {ICON_SIZES}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
