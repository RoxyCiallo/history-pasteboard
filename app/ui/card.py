"""单张历史卡片的绘制与交互。

一张卡片是一个 ``Canvas``：底部画一个圆角矩形当背景，内容用 ``create_window``
内嵌一个 ``Frame``。这样能同时满足「圆角」「悬停换底色」「整卡点击」三个要求，
而纯 ``Frame`` 做不到圆角。

卡片不直接访问数据库，所有动作通过构造时传入的回调交给主窗口处理。
"""

from __future__ import annotations

import logging
import math
import tkinter as tk
import tkinter.font as tkfont

from ui import theme

_LOGGER = logging.getLogger("pasteboard.ui.card")

CARD_RADIUS = theme.RADIUS_CARD
MIN_CARD_WIDTH = 240
#: 左侧类型图标的占位宽度（含间距）。
ICON_WIDTH = 26
#: 右上角按钮宽度（含间距）。
BUTTON_WIDTH = 30
#: 正文最多显示的行数。
TEXT_MAX_LINES = 3
#: 私密卡片的打码占位。
PRIVATE_MASK = "••••••••••••"

ICON_TEXT = "📄"
ICON_IMAGE = "🖼"
ICON_PRIVATE = "🔒"
ICON_PIN = "📌"
ICON_DELETE = "🗑"


def rounded_points(x1: float, y1: float, x2: float, y2: float, radius: float, steps: int = 4) -> list[float]:
    """返回圆角矩形的多边形顶点（四角用圆弧采样，直接多段线绘制）。

    早期用三个控制点 + ``smooth=True`` 让 Tk 自己磨角，视觉上只是极小倒角；
    显式采样圆弧才能得到接近设计稿的 10px 圆角。
    """
    r = max(0.0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    if r <= 0.5:
        return [x1, y1, x2, y1, x2, y2, x1, y2]
    points: list[float] = []
    corners = (
        (x2 - r, y1 + r, -90.0, 0.0),    # 右上
        (x2 - r, y2 - r, 0.0, 90.0),     # 右下
        (x1 + r, y2 - r, 90.0, 180.0),   # 左下
        (x1 + r, y1 + r, 180.0, 270.0),  # 左上
    )
    for cx, cy, start, end in corners:
        for index in range(steps + 1):
            angle = math.radians(start + (end - start) * index / steps)
            points.append(cx + r * math.cos(angle))
            points.append(cy + r * math.sin(angle))
    return points


def clip_lines(text: str, font, pixel_width: int, max_lines: int = TEXT_MAX_LINES) -> str:
    """按像素宽度把文本切成最多 ``max_lines`` 行，超出部分用省略号收尾。

    ``font`` 是 ``tkinter.font.Font``（有 ``measure`` 方法）。按字符逐个累加而不是
    用固定字数，中英文混排时不会一行显示半行空白。
    """
    if not text:
        return ""
    width = max(20, int(pixel_width))
    lines: list[str] = []
    current = ""
    truncated = False

    for char in text:
        if char == "\n":
            lines.append(current)
            current = ""
            if len(lines) >= max_lines:
                truncated = True
                break
            continue
        if font.measure(current + char) > width:
            lines.append(current)
            current = char
            if len(lines) >= max_lines:
                truncated = True
                break
        else:
            current += char
    else:
        lines.append(current)

    if truncated and lines:
        last = lines[-1]
        while last and font.measure(last + "…") > width:
            last = last[:-1]
        lines[-1] = last + "…"
    return "\n".join(lines)


class ClipCard(tk.Canvas):
    """一张历史卡片。

    :param item: 数据库记录（dict）
    :param fonts: ``ui.theme.Fonts`` 实例
    :param thumb_loader: ``callable(item) -> PhotoImage | None``，由主窗口提供缓存
    :param width: 卡片像素宽度（主窗口列表宽度）
    :param on_copy/on_pin/on_delete/on_unlock: 卡片动作回调，参数为 ``item``
    """

    def __init__(
        self,
        master,
        item: dict,
        *,
        fonts: theme.Fonts,
        thumb_loader,
        width: int,
        on_copy,
        on_pin,
        on_delete,
        on_unlock,
    ) -> None:
        super().__init__(
            master,
            bg=theme.BG_ROOT,
            highlightthickness=0,
            bd=0,
            height=1,
        )
        self.item = item
        self._fonts = fonts
        self._thumb_loader = thumb_loader
        self._on_copy = on_copy
        self._on_pin = on_pin
        self._on_delete = on_delete
        self._on_unlock = on_unlock

        self._kind = item.get("kind", "text")
        self._is_private = bool(item.get("is_private"))
        self._pinned = bool(item.get("pinned"))
        self._raw_text = item.get("text_content") or ""

        self._bg_normal = theme.BG_PRIVATE if self._is_private else theme.BG_CARD
        self._hover = False
        self._body_font = tkfont.Font(self, font=fonts.body())
        self._small_font = tkfont.Font(self, font=fonts.small())

        self._width = max(MIN_CARD_WIDTH, int(width))
        self._inner_width = self._width - 2 * theme.PAD_CARD
        self.configure(width=self._width)

        self._bg_item = self.create_polygon(
            0, 0, 0, 0,
            fill=self._bg_normal, outline=theme.BORDER, width=1,
        )
        self._pin_bar = self.create_rectangle(0, 0, 0, 0, fill=theme.PRIMARY, outline="")

        self._tint_widgets: list[tk.Widget] = []
        self._inner = tk.Frame(self, bg=self._bg_normal)
        self._tint_widgets.append(self._inner)
        self._window = self.create_window(
            (theme.PAD_CARD, theme.PAD_CARD),
            window=self._inner,
            anchor="nw",
            width=self._inner_width,
        )
        self._build_content()
        self._bind_hover()
        self.after_idle(self._relayout)

    # ---- 构建 -------------------------------------------------------

    def _text_width(self) -> int:
        """正文可用宽度：卡片内部减去图标与按钮列。"""
        return max(80, self._inner_width - ICON_WIDTH - 2 * BUTTON_WIDTH - 12)

    def _build_content(self) -> None:
        bg = self._bg_normal
        top = tk.Frame(self._inner, bg=bg)
        top.pack(fill="x")
        self._tint_widgets.append(top)

        icon = ICON_PRIVATE if self._is_private else (ICON_IMAGE if self._kind == "image" else ICON_TEXT)
        tk.Label(top, text=icon, font=self._fonts.body(), bg=bg, fg=theme.TEXT_PRIMARY).pack(
            side="left", anchor="n", padx=(0, 6)
        )

        buttons = tk.Frame(top, bg=bg)
        buttons.pack(side="right", anchor="n", padx=(6, 0))
        self._tint_widgets.append(buttons)
        self._pin_button = self._icon_button(
            buttons, ICON_PIN, self._on_pin_click, theme.PIN_ACTIVE if self._pinned else theme.TEXT_SECONDARY
        )
        self._pin_button.pack(side="left")
        self._delete_button = self._icon_button(buttons, ICON_DELETE, self._on_delete_click)
        self._delete_button.pack(side="left", padx=(2, 0))
        # 参与整卡换底色，否则悬停时按钮会留一块白色方块。
        self._tint_widgets.extend((self._pin_button, self._delete_button))

        self._text_label = tk.Label(
            top,
            text=self._preview_text(),
            font=self._fonts.body(),
            bg=bg,
            fg=theme.TEXT_PRIMARY,
            justify="left",
            anchor="nw",
            wraplength=self._text_width(),
        )
        self._text_label.pack(side="left", fill="x", expand=True)
        self._tint_widgets.append(self._text_label)

        if self._kind == "image" and not self._is_private:
            photo = self._thumb_loader(self.item) if self._thumb_loader else None
            if photo is not None:
                holder = tk.Frame(self._inner, bg=bg)
                holder.pack(anchor="w", pady=(8, 0))
                self._tint_widgets.append(holder)
                thumb = tk.Label(holder, image=photo, bg=bg, bd=0)
                thumb.image = photo  # 保住引用，防止被 GC 后图片消失
                thumb.pack()
                self._tint_widgets.append(thumb)

        meta_row = tk.Frame(self._inner, bg=bg)
        meta_row.pack(fill="x", pady=(8, 0))
        self._tint_widgets.append(meta_row)
        meta = tk.Label(
            meta_row,
            text=self._meta_text(),
            font=self._fonts.small(),
            bg=bg,
            fg=theme.TEXT_SECONDARY,
        )
        meta.pack(side="left")
        self._tint_widgets.append(meta)

        if self._pinned:
            tag = tk.Label(
                meta_row,
                text="  已置顶",
                font=self._fonts.small(),
                bg=bg,
                fg=theme.PRIMARY,
            )
            tag.pack(side="left")
            self._tint_widgets.append(tag)

    def _icon_button(self, master, text: str, command, color: str = theme.TEXT_SECONDARY) -> tk.Label:
        """卡片右上角的图标按钮：无边框，悬停加浅底并变色。"""
        label = tk.Label(
            master,
            text=text,
            font=self._fonts.small(),
            bg=self._bg_normal,
            fg=color,
            width=3,
            cursor="hand2",
        )
        label.base_color = color
        label.bind("<Enter>", lambda _e: label.configure(bg=theme.PRIMARY_LIGHT))
        label.bind("<Leave>", lambda _e: label.configure(bg=self._hover_bg()))
        label.bind("<Button-1>", lambda _e: self._invoke(command))
        return label

    # ---- 文本 -------------------------------------------------------

    def _preview_text(self) -> str:
        if self._is_private:
            return f"{PRIVATE_MASK}  受保护内容，点击输入密码查看"
        if self._kind == "image":
            return "图片"
        return clip_lines(self._raw_text, self._body_font, self._text_width())

    def _meta_text(self) -> str:
        from ui.main_window import format_time, human_size

        parts = [format_time(self.item.get("updated_at", ""))]
        if self._kind == "image":
            parts.append(f"{self.item.get('width') or 0} × {self.item.get('height') or 0}")
            parts.append(human_size(self.item.get("byte_size") or 0))
        return " · ".join(part for part in parts if part)

    # ---- 交互 -------------------------------------------------------

    def _invoke(self, callback) -> None:
        try:
            callback(self.item)
        except Exception:  # pragma: no cover - 回调异常不能打断界面
            _LOGGER.exception("卡片操作失败")

    def _on_pin_click(self, _event=None):
        self._invoke(self._on_pin)
        return "break"

    def _on_delete_click(self, _event=None):
        self._invoke(self._on_delete)
        return "break"

    def _handle_body_click(self, _event=None):
        if self._is_private:
            self._invoke(self._on_unlock)
        else:
            self._invoke(self._on_copy)

    def _bind_hover(self) -> None:
        """整卡参与点击与悬停：逐个子控件绑定（图钉/删除按钮除外）。"""
        self.bind("<Button-1>", self._handle_body_click)
        self.bind("<Enter>", self._on_pointer_enter)
        self.bind("<Leave>", self._on_pointer_leave)
        buttons = {self._pin_button, self._delete_button}
        for widget in self._descendants(self):
            if widget in buttons:
                continue
            widget.bind("<Button-1>", self._handle_body_click, add="+")
            widget.bind("<Enter>", self._on_pointer_enter, add="+")
            widget.bind("<Leave>", self._on_pointer_leave, add="+")

    def _descendants(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self._descendants(child)

    def _on_pointer_enter(self, _event=None) -> None:
        self._set_hover(True)

    def _on_pointer_leave(self, _event=None) -> None:
        # Tk 在指针移入子控件时也会给父控件发 Leave，延迟确认指针是否真的离开了卡片。
        self.after(40, self._check_pointer_left)

    def _check_pointer_left(self) -> None:
        if not self.winfo_exists():
            return
        if not self._pointer_inside():
            self._set_hover(False)

    def _pointer_inside(self) -> bool:
        try:
            x, y = self.winfo_pointerxy()
            widget = self.winfo_containing(x, y)
        except Exception:
            return False
        while widget is not None:
            if widget is self:
                return True
            widget = widget.master
        return False

    def _hover_bg(self) -> str:
        return theme.BG_CARD_HOVER if self._hover else self._bg_normal

    def _set_hover(self, active: bool) -> None:
        if active == self._hover:
            return
        self._hover = active
        bg = self._hover_bg()
        self.itemconfigure(
            self._bg_item,
            fill=bg,
            outline=theme.PRIMARY_LIGHT if active else theme.BORDER,
        )
        for widget in self._tint_widgets:
            try:
                widget.configure(bg=bg)
            except tk.TclError:  # pragma: no cover
                pass

    # ---- 布局 -------------------------------------------------------

    def _relayout(self) -> None:
        if not self.winfo_exists():
            return
        self.update_idletasks()
        inner_height = self._inner.winfo_reqheight()
        height = inner_height + 2 * theme.PAD_CARD
        self.configure(height=height)
        self.coords(
            self._bg_item,
            *rounded_points(1, 1, self._width - 1, height - 1, CARD_RADIUS),
        )
        if self._pinned:
            self.coords(self._pin_bar, 2, 14, 5, height - 14)
            self.itemconfigure(self._pin_bar, state="normal")
        else:
            self.itemconfigure(self._pin_bar, state="hidden")

    def set_width(self, width: int) -> None:
        """窗口变宽/变窄时更新卡片宽度与换行宽度。"""
        width = max(MIN_CARD_WIDTH, int(width))
        if width == self._width:
            return
        self._width = width
        self._inner_width = width - 2 * theme.PAD_CARD
        self.configure(width=width)
        self.itemconfigure(self._window, width=self._inner_width)
        self._text_label.configure(
            text=self._preview_text(),
            wraplength=self._text_width(),
        )
        self._relayout()
