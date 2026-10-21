"""设计令牌：颜色、字体、尺寸的唯一来源。

对应 `docs/03-design-spec.md`。**其他模块禁止写裸色值或裸字号**，
要加新颜色先改规范文档，再在这里登记。
"""

from __future__ import annotations

# ---- 颜色 ----------------------------------------------------------
BG_ROOT = "#F5FAFF"
BG_HEADER = "#E3F0FC"
BG_CARD = "#FFFFFF"
BG_CARD_HOVER = "#F0F8FF"
BG_PRIVATE = "#FFF9EC"
BG_INPUT = "#FFFFFF"
BORDER = "#D6E6F5"
BORDER_FOCUS = "#4A90D9"
PRIMARY = "#4A90D9"
PRIMARY_HOVER = "#3B7CC0"
PRIMARY_LIGHT = "#EAF4FD"
TEXT_PRIMARY = "#24303C"
TEXT_SECONDARY = "#6B7C8F"
TEXT_ON_PRIMARY = "#FFFFFF"
DANGER = "#E5686A"
DANGER_HOVER = "#D2555A"
PIN_ACTIVE = "#F2B33D"
SUCCESS = "#3FA97B"

# ---- 字体 ----------------------------------------------------------
FONT_FAMILY_CANDIDATES = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI")
FONT_TITLE = 13
FONT_BODY = 10
FONT_BODY_BOLD = 10
FONT_SMALL = 9

# ---- 尺寸与间距 ----------------------------------------------------
RADIUS_CARD = 10
RADIUS_BTN = 6
PAD_WINDOW_X = 20
PAD_CARD = 14
GAP_CARD = 10
H_HEADER = 64
H_INPUT = 32
H_STATUS = 40
THUMB_W = 260
THUMB_H = 150
SEARCH_WIDTH = 260
WINDOW_DEFAULT = "900x680"
WINDOW_MIN_WIDTH = 720
WINDOW_MIN_HEIGHT = 520

#: 列表一次渲染的上限（分页见 docs/04）。
LIST_PAGE = 200


class Fonts:
    """按当前系统可用的字体族生成 tkinter 字体元组。

    tkinter 接受 ``(family, size, weight)`` 形式的字体描述，
    比创建 ``tkinter.font.Font`` 对象少一层引用管理，也不会被垃圾回收。
    """

    def __init__(self, root) -> None:
        import tkinter.font as tkfont

        available = set(tkfont.families(root))
        self.family = next(
            (name for name in FONT_FAMILY_CANDIDATES if name in available),
            "TkDefaultFont",
        )

    def _spec(self, size: int, bold: bool = False):
        return (self.family, size, "bold" if bold else "normal")

    def title(self):
        """窗口标题：13pt bold。"""
        return self._spec(FONT_TITLE, True)

    def body(self):
        """正文：10pt。"""
        return self._spec(FONT_BODY)

    def body_bold(self):
        """强调正文：10pt bold。"""
        return self._spec(FONT_BODY_BOLD, True)

    def small(self):
        """小字：9pt，用于时间与提示。"""
        return self._spec(FONT_SMALL)


def apply_root_style(root) -> None:
    """统一 ttk 控件外观（目前只有滚动条），避免系统默认灰。"""
    from tkinter import ttk

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:  # pragma: no cover - 主题缺失时保持默认
        pass
    style.configure(
        "Vertical.TScrollbar",
        background=BG_HEADER,
        troughcolor=BG_ROOT,
        bordercolor=BORDER,
        arrowcolor=TEXT_SECONDARY,
        gripcount=0,
        width=12,
    )
