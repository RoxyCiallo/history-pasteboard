"""主窗口：顶栏、圆角卡片列表、状态栏。

职责：
- 列表按「置顶优先、时间倒序」渲染，支持关键字搜索与滚动分页；
- 卡片点击复制回剪贴板并隐藏窗口，支持置顶、删除、私密内容占位提示；
- 监听线程通过队列投递事件，窗口用 ``after`` 轮询，不跨线程操作控件。
"""

from __future__ import annotations

import logging
import queue
import re
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

import storage
import win32
from ui import card, dialogs, theme

_LOGGER = logging.getLogger("pasteboard.ui.main_window")

PLACEHOLDER = "搜索历史…"
POLL_INTERVAL_MS = 200
REFRESH_DEBOUNCE_MS = 80
SEARCH_DEBOUNCE_MS = 300
RESIZE_DEBOUNCE_MS = 120
#: 保留期清理：启动后 2 秒跑一次，之后每 10 分钟一次（docs/02 §7）。
PURGE_INTERVAL_MS = 600_000
PURGE_START_DELAY_MS = 2_000
#: 状态栏临时提示的显示时长。
STATUS_FLASH_MS = 6_000
DEFAULT_HOTKEY_LABEL = "Ctrl+Shift+V"


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
        self._resize_job = None
        self._placeholder_active = True
        self._cards: list[card.ClipCard] = []
        self._has_more = False
        self._loading_more = False
        self._thumb_cache: dict[str, ImageTk.PhotoImage] = {}
        self._purge_job = None
        self._status_job = None
        self._base_status = "共 0 条"
        self._status_flash = ""
        self._hotkey_label = DEFAULT_HOTKEY_LABEL
        self._settings_dialog: "dialogs.SettingsDialog | None" = None

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
        self._purge_job = self.after(PURGE_START_DELAY_MS, self._purge_expired)
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
        self._flat_button(header, "设置", self._show_settings).pack(
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

    # ---- 状态栏 -------------------------------------------------------

    def _set_base_status(self, text: str) -> None:
        """设置状态栏的常驻文本（条数、保留天数）。"""
        self._base_status = text
        self._render_status()

    def _flash_status(self, text: str, timeout_ms: int = STATUS_FLASH_MS) -> None:
        """临时提示（复制失败、热键回退等），到时自动恢复常驻文本。"""
        self._status_flash = text
        self._render_status()
        if self._status_job is not None:
            try:
                self.after_cancel(self._status_job)
            except tk.TclError:
                pass
        self._status_job = self.after(timeout_ms, self._clear_flash)

    def _clear_flash(self) -> None:
        self._status_job = None
        self._status_flash = ""
        self._render_status()

    def _render_status(self) -> None:
        if self._closing:
            return
        text = self._status_flash or self._base_status
        try:
            self.status_label.configure(text=text)
        except tk.TclError:
            pass

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
        bbox = self.canvas.bbox("all")
        if not bbox:
            return
        # scrollregion 必须从 (0,0) 开始：若直接用 bbox（左边距 20），
        # Canvas 会把内容整体左移 20px，卡片看起来贴到了窗口边缘。
        width = max(bbox[2], self.canvas.winfo_width())
        self.canvas.configure(scrollregion=(0, 0, width, bbox[3] + 12))

    def _on_canvas_configure(self, event) -> None:
        content_width = max(event.width - 2 * theme.PAD_WINDOW_X - 8, card.MIN_CARD_WIDTH)
        self.canvas.itemconfigure(self._window_id, width=content_width)
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(RESIZE_DEBOUNCE_MS, lambda: self._resize_cards(content_width))

    def _resize_cards(self, content_width: int) -> None:
        """窗口宽度变化后统一更新卡片宽度（防抖，避免逐像素重排）。"""
        self._resize_job = None
        for clip in self._cards:
            try:
                clip.set_width(content_width)
            except tk.TclError:  # pragma: no cover - 卡片可能已被销毁
                pass

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
        # 等这一帧滚动生效后再判断是否到底，避免用上一帧的 yview。
        self.after(120, self._maybe_load_more)

    def refresh(self) -> None:
        """按当前关键字重新查询并重绘列表（第一页）。"""
        if self._closing:
            return
        keyword = self._keyword or None
        if keyword:
            items = self._database.search(keyword, limit=theme.LIST_PAGE)
        else:
            items = self._database.list_items(limit=theme.LIST_PAGE)
        self._render(items)
        self._has_more = len(items) >= theme.LIST_PAGE
        total = self._database.count(keyword)
        self._set_base_status(f"共 {total} 条 · 保留 {self._retention_days()} 天")

    def _retention_days(self) -> int:
        if self._config is None:
            return 3
        try:
            return int(self._config.retention_days)
        except Exception:
            return 3

    def _purge_expired(self) -> None:
        """按保留期清理过期记录（置顶除外）：启动后一次 + 每 10 分钟一次。"""
        self._purge_job = None
        if self._closing or self._database is None:
            return
        days = self._retention_days()
        try:
            removed = self._database.purge_expired(days)
        except Exception:
            _LOGGER.exception("保留期清理失败")
            removed = []
        if removed:
            paths = []
            for row in removed:
                paths.append(row.get("image_path"))
                paths.append(row.get("thumb_path"))
                thumb = row.get("thumb_path")
                if thumb:
                    self._thumb_cache.pop(thumb, None)
            storage.delete_files(self._data_dir, paths)
            _LOGGER.info("保留期清理：删除 %s 条过期记录（保留 %s 天）", len(removed), days)
            self._schedule_refresh()
        if self._config is not None:
            try:
                self._config.set(
                    "last_purge_at", datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                )
            except Exception:
                _LOGGER.exception("写入 last_purge_at 失败")
        self._purge_job = self.after(PURGE_INTERVAL_MS, self._purge_expired)

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
        self._cards = []
        if not items:
            self._render_empty()
        else:
            self._append_items(items)
        self._on_content_configure()

    def _append_items(self, items: list[dict]) -> None:
        width = self._current_content_width()
        for item in items:
            clip = card.ClipCard(
                self.list_frame,
                item,
                fonts=self._fonts,
                thumb_loader=self._load_thumbnail,
                width=width,
                on_copy=self._copy_item,
                on_pin=self._toggle_pin,
                on_delete=self._delete_item,
                on_unlock=self._unlock_item,
            )
            clip.pack(fill="x", pady=(0, theme.GAP_CARD))
            self._cards.append(clip)

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

    # ---- 分页加载 ---------------------------------------------------

    def _maybe_load_more(self) -> None:
        if self._closing or self._loading_more or not self._has_more:
            return
        try:
            _, last = self.canvas.yview()
        except tk.TclError:  # pragma: no cover
            return
        if last >= 0.998:
            self._load_more()

    def _load_more(self) -> None:
        self._loading_more = True
        offset = len(self._cards)
        try:
            keyword = self._keyword or None
            if keyword:
                items = self._database.search(keyword, limit=theme.LIST_PAGE, offset=offset)
            else:
                items = self._database.list_items(limit=theme.LIST_PAGE, offset=offset)
            if items:
                self._append_items(items)
                self._on_content_configure()
            self._has_more = len(items) >= theme.LIST_PAGE
        finally:
            self._loading_more = False

    # ---- 卡片动作 ---------------------------------------------------

    def _copy_item(self, item: dict) -> None:
        """把卡片内容写回系统剪贴板，然后隐藏窗口，方便直接 Ctrl+V。"""
        if bool(item.get("is_private")):
            self._unlock_item(item)
            return
        ok = False
        if item.get("kind") == "text":
            ok = win32.set_clipboard_text(item.get("text_content") or "")
        else:
            path = storage.image_abs_path(self._data_dir, item.get("image_path"))
            if path is not None and path.exists():
                try:
                    with Image.open(path) as source:
                        ok = win32.set_clipboard_image(source.copy())
                except (OSError, ValueError):
                    _LOGGER.exception("读取图片失败，id=%s", item.get("id"))
        if not ok:
            self._flash_status("复制失败：剪贴板被占用，请稍后重试")
            return
        _LOGGER.info("已复制回剪贴板，id=%s", item.get("id"))
        # 复制后的隐藏不弹首次提示，用户正在连用，不需要教学文案。
        self.withdraw()

    def _toggle_pin(self, item: dict) -> None:
        self._database.toggle_pin(item.get("id"))
        self.refresh()

    def _delete_item(self, item: dict) -> None:
        if not messagebox.askyesno(
            "删除记录",
            "删除后无法恢复，确定要删除这条记录吗？\n图片文件会一并删除。",
            parent=self,
        ):
            return
        deleted = self._database.delete_item(item.get("id"))
        if deleted:
            storage.delete_files(
                self._data_dir,
                [deleted.get("image_path"), deleted.get("thumb_path")],
            )
            for key in (deleted.get("thumb_path"), deleted.get("image_path")):
                if key:
                    self._thumb_cache.pop(key, None)
        self.refresh()

    def _unlock_item(self, item: dict) -> None:
        # 二级密码在 M6 实现，这里先给出明确提示，避免用户以为点击坏了。
        messagebox.showinfo(
            "私密内容",
            "这条内容带有敏感标记。\n查看与复制需要先设置二级密码，该功能将在后续版本提供。",
            parent=self,
        )

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
                kind, payload = self._queue.get_nowait()
                if kind == "new":
                    self._schedule_refresh()
                elif kind == "hotkey":
                    self.show()
                elif kind == "activate":
                    self.show()
                elif kind == "hotkey_registered":
                    self._hotkey_label = str(payload or DEFAULT_HOTKEY_LABEL)
                    if self._hotkey_label != DEFAULT_HOTKEY_LABEL:
                        self._flash_status(
                            f"{DEFAULT_HOTKEY_LABEL} 被占用，已改用 {self._hotkey_label}",
                            timeout_ms=10_000,
                        )
                elif kind == "hotkey_failed":
                    self._flash_status(
                        "全局热键注册失败，可能被其他程序占用，请用设置面板检查",
                        timeout_ms=10_000,
                    )
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

    def _show_settings(self) -> None:
        """打开设置面板；已经打开时只把它提到前面，不重复创建。"""
        existing = self._settings_dialog
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.lift()
                    existing.focus_set()
                    return
            except tk.TclError:
                pass
        if self._config is None:
            messagebox.showinfo("设置", "当前没有可用的配置存储。", parent=self)
            return
        dialog = dialogs.SettingsDialog(
            self,
            self._fonts,
            self._config,
            self._data_dir,
            on_clear=self._clear_history,
            on_saved=self.refresh,
            hotkey_label=self._hotkey_label,
        )
        self._settings_dialog = dialog

    def _clear_history(self) -> int:
        """清空全部历史：删记录、删图片文件、清缩略图缓存，返回删除条数。"""
        records = self._database.clear_all()
        paths: list[str | None] = []
        for record in records:
            paths.append(record.get("image_path"))
            paths.append(record.get("thumb_path"))
        storage.delete_files(self._data_dir, paths)
        self._thumb_cache.clear()
        self.refresh()
        _LOGGER.info("已清空全部历史，共 %s 条", len(records))
        return len(records)

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
        for job in (self._purge_job, self._status_job, self._search_job, self._refresh_job):
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
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
