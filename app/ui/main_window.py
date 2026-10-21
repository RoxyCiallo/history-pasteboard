"""主窗口（M3 骨架版）：顶栏、卡片列表、状态栏。

M3 只负责把窗口搭起来、按时间倒序显示历史条目、支持搜索过滤；
卡片点击复制、置顶、删除等交互在 M4 实现。
"""

from __future__ import annotations

import queue
import re
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

import storage
from ui import theme

PLACEHOLDER = "搜索历史…"
POLL_INTERVAL_MS = 200
REFRESH_DEBOUNCE_MS = 80
SEARCH_DEBOUNCE_MS = 300
MAX_PREVIEW_LINES = 3
MAX_PREVIEW_CHARS = 80


def format_time(iso_text: str, now: datetime | None = None) -> str:
    """把库里的 ISO 时间转成「今天 14:32 / 昨天 09:10 / 2026-10-18 21:05」。"""
    try:
        moment = datetime.strptime(iso_text, "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return iso_text or ""
    now = now or datetime.now()
    today = now.date()
    if moment.date() == today:
        return f"今天 {moment:%H:%M}"
    if moment.date() == today - timedelta(days=1):
        return f"昨天 {moment:%H:%M}"
    return f"{moment:%Y-%m-%d %H:%M}"


def human_size(byte_size: int | None) -> str:
    """把字节数转成「236 KB」这样带空格的可读形式。"""
    size = int(byte_size or 0)
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def clip_text(text: str | None, max_lines: int = MAX_PREVIEW_LINES) -> str:
    """预览文本：最多 3 行，每行最多 80 字，超出加省略号；保留原有换行。"""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = raw.split("\n")
    clipped = [
        line if len(line) <= MAX_PREVIEW_CHARS else line[:MAX_PREVIEW_CHARS] + "…"
        for line in lines[:max_lines]
    ]
    if len(lines) > max_lines and clipped:
        clipped[-1] = clipped[-1] + "…"
    return "\n".join(clipped)


class MainWindow(tk.Tk):
    """主窗口：顶栏 + 滚动卡片列表 + 状态栏。"""

    def __init__(
        self,
        database,
        cfg,
        data_dir,
        event_queue: "queue.Queue | None" = None,
        on_quit=None,
    ) -> None:
        super().__init__()
        self._database = database
        self._config = cfg
        self._data_dir = data_dir
        self._queue = event_queue
        self._on_quit = on_quit
        self._closing = False
        self._keyword = ""
        self._search_job = None
        self._refresh_job = None
        self._placeholder_active = True
        self._text_labels: list[tk.Label] = []
        self._photos: list[ImageTk.PhotoImage] = []
        self._thumb_cache: dict[str, ImageTk.PhotoImage] = {}

        self._apply_scaling()
        self._fonts = theme.Fonts(self)

        self.title("历史粘贴板")
        self.configure(bg=theme.BG_ROOT)
        self.minsize(theme.WINDOW_MIN_WIDTH, theme.WINDOW_MIN_HEIGHT)
        theme.apply_root_style(self)
        self._restore_geometry()
        self.protocol("WM_DELETE_WINDOW", self.hide)

        self._build_header()
        self._build_status_bar()
        self._build_list_area()
        self._bind_events()

        self.refresh()
        if self._queue is not None:
            self.after(POLL_INTERVAL_MS, self._poll_events)

    # ---- 初始化辅助 -------------------------------------------------

    def _apply_scaling(self) -> None:
        """按屏幕实际 DPI 设置 tk scaling，保证 125%/150% 下字号正常。"""
        try:
            dpi = self.winfo_fpixels("1i")
            self.tk.call("tk", "scaling", dpi / 72.0)
        except tk.TclError:  # pragma: no cover - 取不到就保持默认
            pass

    def _restore_geometry(self) -> None:
        saved = ""
        if self._config is not None:
            try:
                saved = str(self._config.get("window_geometry") or "")
            except Exception:
                saved = ""
        if saved and self._geometry_visible(saved):
            try:
                self.geometry(saved)
                return
            except tk.TclError:
                pass
        self.geometry(theme.WINDOW_DEFAULT)
        self.after(10, self._center_on_screen)

    def _geometry_visible(self, geometry: str) -> bool:
        """校验保存的窗口位置是否还落在可见屏幕内（换显示器后可能越界）。"""
        match = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", geometry.strip())
        if not match:
            return False
        width, height, x, y = (int(part) for part in match.groups())
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        return (
            x + 80 < screen_w
            and y + 40 < screen_h
            and x > 40 - width
            and y >= -10
        )

    def _center_on_screen(self) -> None:
        self.update_idletasks()
        width = max(self.winfo_width(), theme.WINDOW_MIN_WIDTH)
        height = max(self.winfo_height(), theme.WINDOW_MIN_HEIGHT)
        x = max((self.winfo_screenwidth() - width) // 2, 0)
        y = max((self.winfo_screenheight() - height) // 3, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")

    # ---- 界面搭建 ---------------------------------------------------

    def _flat_button(self, parent, text, command, width=None) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            font=self._fonts.body(),
            bg=theme.BG_HEADER,
            fg=theme.TEXT_PRIMARY,
            activebackground=theme.PRIMARY_LIGHT,
            activeforeground=theme.TEXT_PRIMARY,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            width=width,
        )

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=theme.BG_HEADER, height=theme.H_HEADER)
        header.pack(side="top", fill="x")
        header.pack_propagate(False)
        self._header = header

        tk.Label(
            header,
            text="历史粘贴板",
            font=self._fonts.title(),
            bg=theme.BG_HEADER,
            fg=theme.TEXT_PRIMARY,
        ).pack(side="left", padx=(theme.PAD_WINDOW_X, 0))

        self._flat_button(header, "✕", self.hide, width=3).pack(
            side="right", padx=(0, theme.PAD_WINDOW_X)
        )
        self._flat_button(header, "—", self.iconify, width=3).pack(side="right")
        self._flat_button(header, "设置", self._show_settings_placeholder).pack(
            side="right", padx=(0, 10)
        )

        self.search_entry = tk.Entry(
            header,
            font=self._fonts.body(),
            width=24,
            relief="flat",
            bd=0,
            bg=theme.BG_INPUT,
            fg=theme.TEXT_SECONDARY,
            insertbackground=theme.TEXT_PRIMARY,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            highlightcolor=theme.BORDER_FOCUS,
        )
        self.search_entry.pack(side="right", padx=(0, 16), ipady=5)

        tk.Frame(header, bg=theme.BORDER, height=1).pack(side="bottom", fill="x")

    def _build_status_bar(self) -> None:
        status = tk.Frame(self, bg=theme.BG_HEADER, height=theme.H_STATUS)
        status.pack(side="bottom", fill="x")
        status.pack_propagate(False)

        tk.Frame(status, bg=theme.BORDER, height=1).pack(side="top", fill="x")
        self.status_label = tk.Label(
            status,
            text="共 0 条",
            font=self._fonts.small(),
            bg=theme.BG_HEADER,
            fg=theme.TEXT_SECONDARY,
        )
        self.status_label.pack(side="left", padx=theme.PAD_WINDOW_X)
        self._flat_button(status, "彻底退出", self._confirm_quit).pack(
            side="right", padx=(0, theme.PAD_WINDOW_X)
        )

    def _build_list_area(self) -> None:
        body = tk.Frame(self, bg=theme.BG_ROOT)
        body.pack(side="top", fill="both", expand=True)

        self.canvas = tk.Canvas(
            body, bg=theme.BG_ROOT, highlightthickness=0, bd=0, yscrollincrement=20
        )
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.list_frame = tk.Frame(self.canvas, bg=theme.BG_ROOT)
        self._window_id = self.canvas.create_window(
            (theme.PAD_WINDOW_X, 12), window=self.list_frame, anchor="nw"
        )
        self.list_frame.bind("<Configure>", self._on_content_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _bind_events(self) -> None:
        self.bind("<Escape>", lambda _event: self.hide())
        self.bind("<MouseWheel>", self._on_mousewheel)
        self.bind("<Control-f>", self._focus_search)
        self.bind("<Control-F>", self._focus_search)
        self.search_entry.bind("<KeyRelease>", self._on_search_changed)
        self.search_entry.bind("<FocusIn>", self._on_search_focus_in)
        self.search_entry.bind("<FocusOut>", self._on_search_focus_out)
        self.search_entry.insert(0, PLACEHOLDER)

    # ---- 列表渲染 ---------------------------------------------------

    def _on_content_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        content_width = max(event.width - 2 * theme.PAD_WINDOW_X - 8, 240)
        self.canvas.itemconfigure(self._window_id, width=content_width)
        wrap = self._wrap_length(content_width)
        for label in self._text_labels:
            try:
                label.configure(wraplength=wrap)
            except tk.TclError:
                pass

    @staticmethod
    def _wrap_length(content_width: int) -> int:
        """卡内文字可用宽度：列表宽 - 卡片内边距 - 左侧图标。"""
        return max(content_width - 2 * theme.PAD_CARD - 30, 200)

    def _current_content_width(self) -> int:
        width = self.canvas.winfo_width()
        if width <= 1:
            width = 900
        return max(width - 2 * theme.PAD_WINDOW_X - 8, 240)

    def _on_mousewheel(self, event) -> None:
        if self._closing:
            return
        step = -3 if event.delta > 0 else 3
        self.canvas.yview_scroll(step, "units")

    def refresh(self) -> None:
        """按当前关键字重新查询并重绘列表。"""
        if self._closing:
            return
        keyword = self._keyword or None
        if keyword:
            items = self._database.search(keyword, limit=theme.LIST_PAGE)
        else:
            items = self._database.list_items(limit=theme.LIST_PAGE)
        self._render(items)
        total = self._database.count(keyword)
        self.status_label.configure(
            text=f"共 {total} 条 · 保留 {self._retention_days()} 天"
        )

    def _retention_days(self) -> int:
        if self._config is None:
            return 3
        try:
            return int(self._config.retention_days)
        except Exception:
            return 3

    def _schedule_refresh(self) -> None:
        """把短时间内的多次刷新合并成一次，避免连续复制时列表闪烁。"""
        if self._refresh_job is not None:
            return
        self._refresh_job = self.after(REFRESH_DEBOUNCE_MS, self._do_scheduled_refresh)

    def _do_scheduled_refresh(self) -> None:
        self._refresh_job = None
        self.refresh()

    def _render(self, items: list[dict]) -> None:
        for child in self.list_frame.winfo_children():
            child.destroy()
        self._text_labels = []
        self._photos = []
        if not items:
            self._render_empty()
        else:
            for item in items:
                self._render_card(item)
        self._on_content_configure()

    def _render_empty(self) -> None:
        holder = tk.Frame(self.list_frame, bg=theme.BG_ROOT, pady=70)
        holder.pack(fill="x")
        if self._keyword:
            message = f"没有找到匹配「{self._keyword}」的内容"
        else:
            message = "还没有记录\n复制点什么，这里就会出现它的历史"
        tk.Label(
            holder,
            text=message,
            font=self._fonts.body(),
            bg=theme.BG_ROOT,
            fg=theme.TEXT_SECONDARY,
            justify="center",
        ).pack()

    def _render_card(self, item: dict) -> None:
        is_private = bool(item["is_private"])
        is_pinned = bool(item["pinned"])
        bg = theme.BG_PRIVATE if is_private else theme.BG_CARD

        card = tk.Frame(
            self.list_frame,
            bg=bg,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
        )
        card.pack(fill="x", pady=(0, theme.GAP_CARD))
        if is_pinned:
            tk.Frame(card, bg=theme.PRIMARY, width=3).pack(side="left", fill="y")

        inner = tk.Frame(card, bg=bg)
        inner.pack(side="left", fill="both", expand=True, padx=theme.PAD_CARD, pady=theme.PAD_CARD)

        top = tk.Frame(inner, bg=bg)
        top.pack(fill="x")

        icon = "🔒" if is_private else ("🖼" if item["kind"] == "image" else "📄")
        tk.Label(
            top, text=icon, font=self._fonts.body(), bg=bg, fg=theme.TEXT_PRIMARY
        ).pack(side="left", anchor="n", padx=(0, 10))

        preview = self._preview_text(item)
        label = tk.Label(
            top,
            text=preview,
            font=self._fonts.body(),
            bg=bg,
            fg=theme.TEXT_PRIMARY,
            justify="left",
            anchor="w",
            wraplength=self._wrap_length(self._current_content_width()),
        )
        label.pack(side="left", fill="x", expand=True)
        self._text_labels.append(label)

        if item["kind"] == "image" and not is_private:
            photo = self._load_thumbnail(item)
            if photo is not None:
                self._photos.append(photo)
                tk.Label(inner, image=photo, bg=bg, bd=0).pack(
                    anchor="w", pady=(8, 0)
                )

        bottom = tk.Frame(inner, bg=bg)
        bottom.pack(fill="x", pady=(8, 0))
        meta = self._meta_text(item)
        tk.Label(
            bottom, text=meta, font=self._fonts.small(), bg=bg, fg=theme.TEXT_SECONDARY
        ).pack(side="left")

    def _preview_text(self, item: dict) -> str:
        if item["is_private"]:
            return "•••••••••••• 受保护内容，需要密码查看"
        if item["kind"] == "image":
            # 尺寸与大小写在底部 meta 行，这里不再重复。
            return "图片"
        return clip_text(item["text_content"]) or "（空内容）"

    def _meta_text(self, item: dict) -> str:
        parts = [format_time(item["updated_at"])]
        if item["kind"] == "image":
            parts.append(f"{item['width'] or 0} × {item['height'] or 0}")
            parts.append(human_size(item["byte_size"]))
        if item["pinned"]:
            parts.append("已置顶")
        return " · ".join(part for part in parts if part)

    def _load_thumbnail(self, item: dict) -> "ImageTk.PhotoImage | None":
        relative = item["thumb_path"] or item["image_path"]
        if not relative:
            return None
        cached = self._thumb_cache.get(relative)
        if cached is not None:
            return cached
        path = storage.image_abs_path(self._data_dir, relative)
        if path is None or not path.exists():
            return None
        try:
            with Image.open(path) as source:
                image = source.convert("RGB")
            image.thumbnail((theme.THUMB_W, theme.THUMB_H), Image.Resampling.LANCZOS)
        except (OSError, ValueError):
            return None
        photo = ImageTk.PhotoImage(image)
        # 缓存到窗口生命周期结束，避免每次刷新重复读盘、重复解码。
        self._thumb_cache[relative] = photo
        return photo

    # ---- 搜索 -------------------------------------------------------

    def _focus_search(self, _event=None) -> str:
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")
        return "break"

    def _on_search_focus_in(self, _event=None) -> None:
        if self._placeholder_active:
            self._placeholder_active = False
            self.search_entry.delete(0, "end")
            self.search_entry.configure(fg=theme.TEXT_PRIMARY)

    def _on_search_focus_out(self, _event=None) -> None:
        if not self.search_entry.get().strip():
            self._placeholder_active = True
            self.search_entry.delete(0, "end")
            self.search_entry.insert(0, PLACEHOLDER)
            self.search_entry.configure(fg=theme.TEXT_SECONDARY)

    def _on_search_changed(self, _event=None) -> None:
        if self._search_job is not None:
            self.after_cancel(self._search_job)
        self._search_job = self.after(SEARCH_DEBOUNCE_MS, self._apply_search)

    def _apply_search(self) -> None:
        self._search_job = None
        if self._placeholder_active:
            self._keyword = ""
        else:
            self._keyword = self.search_entry.get().strip()
        self.refresh()

    # ---- 事件队列 ---------------------------------------------------

    def _poll_events(self) -> None:
        if self._closing:
            return
        try:
            while True:
                kind, _payload = self._queue.get_nowait()
                if kind == "new":
                    self._schedule_refresh()
                elif kind == "hotkey":
                    self.show()
                elif kind == "hotkey_failed":
                    self.status_label.configure(text="全局热键注册失败，可能被其他程序占用")
        except queue.Empty:
            pass
        self.after(POLL_INTERVAL_MS, self._poll_events)

    # ---- 窗口生命周期 -----------------------------------------------

    def hide(self) -> None:
        """关闭按钮 = 隐藏到后台，复制记录继续。"""
        if self._closing:
            return
        if self._config is not None:
            try:
                shown = bool(self._config.get("hide_hint_shown"))
            except Exception:
                shown = True
            if not shown:
                self._config.set("hide_hint_shown", True)
                messagebox.showinfo(
                    "仍在后台记录",
                    "窗口已隐藏，复制的内容仍会继续记录。\n按 Ctrl+Shift+V 可以再次打开。",
                    parent=self,
                )
        self.withdraw()

    def show(self) -> None:
        """从隐藏状态唤出并置于最前。"""
        if self._closing:
            return
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(80, lambda: self.attributes("-topmost", False))
        self.focus_force()
        self.refresh()

    def _show_settings_placeholder(self) -> None:
        messagebox.showinfo("设置", "设置面板将在后续版本提供。", parent=self)

    def _confirm_quit(self) -> None:
        if messagebox.askyesno(
            "彻底退出",
            "退出后将不再记录新的复制内容。\n确定要退出吗？",
            parent=self,
        ):
            self.quit_app()

    def quit_app(self) -> None:
        """彻底退出：保存窗口位置 → 通知入口清理 → 销毁窗口。"""
        if self._closing:
            return
        self._closing = True
        self._save_geometry()
        if self._on_quit is not None:
            self._on_quit()
        self.destroy()

    def _save_geometry(self) -> None:
        if self._config is None:
            return
        try:
            self._config.set("window_geometry", self.geometry())
        except Exception:
            pass
