"""设置面板与二级密码对话框。

只做界面与交互，数据写入交给 ``config``；清空历史、重置密码等动作通过回调
交回主窗口执行，避免界面层直接操作数据库。
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

import config
import security
from ui import theme

_LOGGER = logging.getLogger("pasteboard.ui.dialogs")

RETENTION_PRESETS = (1, 3, 5, 7)
CUSTOM = "custom"

DIALOG_WIDTH = 560
DIALOG_PAD = 20

PASSWORD_DIALOG_WIDTH = 380

TEXT_DIALOG_WIDTH = 620
TEXT_DIALOG_HEIGHT = 480


class SettingsDialog(tk.Toplevel):
    """模态设置面板：保留期、当前热键、数据目录、清空历史、版本。"""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Fonts,
        cfg: config.Config,
        data_dir,
        on_clear: Callable[[], int] | None = None,
        on_saved: Callable[[], None] | None = None,
        on_reset_password: Callable[[], int] | None = None,
        on_set_password: Callable[[], None] | None = None,
        password_set: bool = False,
        hotkey_label: str = "Ctrl+Shift+V",
    ) -> None:
        super().__init__(master)
        self._fonts = fonts
        self._config = cfg
        self._data_dir = data_dir
        self._on_clear = on_clear
        self._on_saved = on_saved
        self._on_reset_password = on_reset_password
        self._on_set_password = on_set_password
        self._password_set = bool(password_set)
        self._hotkey_label = hotkey_label or "Ctrl+Shift+V"

        current = int(cfg.retention_days)
        self._use_custom = current not in RETENTION_PRESETS
        self._preset_var = tk.IntVar(self, value=0 if self._use_custom else current)
        self._custom_var = tk.StringVar(
            self, value=str(current) if self._use_custom else ""
        )

        self.title("设置")
        self.configure(bg=theme.BG_ROOT)
        self.resizable(False, False)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self._build()
        self._place_on_parent(master)
        self.grab_set()
        self.bind("<Escape>", lambda _event: self.destroy())
        self.focus_set()

    # ---- 界面 -------------------------------------------------------

    def _build(self) -> None:
        body = tk.Frame(self, bg=theme.BG_ROOT, padx=DIALOG_PAD, pady=DIALOG_PAD)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text="设置",
            font=self._fonts.title(),
            bg=theme.BG_ROOT,
            fg=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x")
        self._separator(body)

        # 保留期
        tk.Label(
            body,
            text="保留期",
            font=self._fonts.body_bold(),
            bg=theme.BG_ROOT,
            fg=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        presets = tk.Frame(body, bg=theme.BG_ROOT)
        presets.pack(fill="x")
        for days in RETENTION_PRESETS:
            tk.Radiobutton(
                presets,
                text=f"{days} 天",
                value=days,
                variable=self._preset_var,
                command=self._on_preset_changed,
                font=self._fonts.body(),
                bg=theme.BG_ROOT,
                fg=theme.TEXT_PRIMARY,
                activebackground=theme.BG_ROOT,
                activeforeground=theme.TEXT_PRIMARY,
                selectcolor=theme.BG_CARD,
                highlightthickness=0,
                bd=0,
                cursor="hand2",
            ).pack(side="left")

        custom = tk.Frame(presets, bg=theme.BG_ROOT)
        custom.pack(side="left", padx=(12, 0))
        tk.Radiobutton(
            custom,
            text="自定义",
            value=0,
            variable=self._preset_var,
            command=self._on_preset_changed,
            font=self._fonts.body(),
            bg=theme.BG_ROOT,
            fg=theme.TEXT_PRIMARY,
            activebackground=theme.BG_ROOT,
            activeforeground=theme.TEXT_PRIMARY,
            selectcolor=theme.BG_CARD,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        ).pack(side="left")
        self._custom_entry = tk.Entry(
            custom,
            textvariable=self._custom_var,
            font=self._fonts.body(),
            width=5,
            justify="center",
            bg=theme.BG_INPUT,
            fg=theme.TEXT_PRIMARY,
            insertbackground=theme.TEXT_PRIMARY,
            relief="flat",
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            highlightcolor=theme.BORDER_FOCUS,
            disabledbackground=theme.BG_ROOT,
            disabledforeground=theme.TEXT_SECONDARY,
        )
        self._custom_entry.pack(side="left", padx=4, ipady=3)
        tk.Label(
            custom,
            text="天",
            font=self._fonts.body(),
            bg=theme.BG_ROOT,
            fg=theme.TEXT_PRIMARY,
        ).pack(side="left")

        self._retention_hint = tk.Label(
            body,
            text="",
            font=self._fonts.small(),
            bg=theme.BG_ROOT,
            fg=theme.TEXT_SECONDARY,
            anchor="w",
        )
        self._retention_hint.pack(fill="x", pady=(6, 0))
        self._update_retention_hint()
        self._update_custom_state()

        self._separator(body)

        # 热键
        self._info_row(body, "唤出热键", self._hotkey_text())
        tk.Label(
            body,
            text="更改热键需要重启程序，本期暂不支持。",
            font=self._fonts.small(),
            bg=theme.BG_ROOT,
            fg=theme.TEXT_SECONDARY,
            anchor="w",
        ).pack(fill="x", pady=(4, 0))

        # 数据目录
        directory = tk.Frame(body, bg=theme.BG_ROOT)
        directory.pack(fill="x", pady=(10, 0))
        tk.Label(
            directory,
            text="数据目录",
            font=self._fonts.body(),
            bg=theme.BG_ROOT,
            fg=theme.TEXT_SECONDARY,
            width=8,
            anchor="w",
        ).pack(side="left")
        path_entry = tk.Entry(
            directory,
            font=self._fonts.small(),
            bg=theme.BG_CARD,
            fg=theme.TEXT_PRIMARY,
            relief="flat",
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            readonlybackground=theme.BG_CARD,
        )
        path_entry.insert(0, str(self._data_dir))
        path_entry.configure(state="readonly")
        path_entry.pack(side="left", fill="x", expand=True, ipady=3)
        self._action_button(
            directory,
            "打开",
            self._open_data_dir,
            bg=theme.BG_CARD,
            fg=theme.TEXT_PRIMARY,
            hover=theme.PRIMARY_LIGHT,
            border=True,
        ).pack(side="left", padx=(8, 0))

        self._separator(body)

        # 二级密码
        password_row = tk.Frame(body, bg=theme.BG_ROOT)
        password_row.pack(fill="x")
        tk.Label(
            password_row,
            text="二级密码",
            font=self._fonts.body(),
            bg=theme.BG_ROOT,
            fg=theme.TEXT_SECONDARY,
            width=8,
            anchor="w",
        ).pack(side="left")
        self._password_state_label = tk.Label(
            password_row,
            font=self._fonts.body_bold(),
            bg=theme.BG_ROOT,
            anchor="w",
        )
        self._password_state_label.pack(side="left")
        self._password_button = self._action_button(
            password_row,
            "重置密码" if self._password_set else "设置密码",
            self._password_action,
            bg=theme.BG_CARD,
            fg=theme.DANGER if self._password_set else theme.PRIMARY,
            hover=theme.PRIMARY_LIGHT,
            border=True,
        )
        self._password_button.pack(side="right")
        self._sync_password_row()

        # 清空历史
        self._action_button(
            body,
            "清空全部历史",
            self._clear_history,
            bg=theme.DANGER,
            fg=theme.TEXT_ON_PRIMARY,
            hover=theme.DANGER_HOVER,
        ).pack(anchor="w")

        # 底部
        footer = tk.Frame(body, bg=theme.BG_ROOT)
        footer.pack(fill="x", pady=(DIALOG_PAD, 0))
        tk.Label(
            footer,
            text=f"历史粘贴板 v{config.APP_VERSION}",
            font=self._fonts.small(),
            bg=theme.BG_ROOT,
            fg=theme.TEXT_SECONDARY,
        ).pack(side="left")
        self._action_button(
            footer,
            "保存",
            self._save,
            bg=theme.PRIMARY,
            fg=theme.TEXT_ON_PRIMARY,
            hover=theme.PRIMARY_HOVER,
        ).pack(side="right")
        self._action_button(
            footer,
            "取消",
            self.destroy,
            bg=theme.BG_CARD,
            fg=theme.TEXT_PRIMARY,
            hover=theme.PRIMARY_LIGHT,
            border=True,
        ).pack(side="right", padx=(0, 8))

    def _separator(self, parent: tk.Misc) -> None:
        tk.Frame(parent, bg=theme.BORDER, height=1).pack(fill="x", pady=(12, 12))

    def _info_row(self, parent: tk.Misc, label: str, value: str) -> None:
        row = tk.Frame(parent, bg=theme.BG_ROOT)
        row.pack(fill="x")
        tk.Label(
            row,
            text=label,
            font=self._fonts.body(),
            bg=theme.BG_ROOT,
            fg=theme.TEXT_SECONDARY,
            width=8,
            anchor="w",
        ).pack(side="left")
        tk.Label(
            row,
            text=value,
            font=self._fonts.body_bold(),
            bg=theme.BG_ROOT,
            fg=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(side="left")

    def _action_button(
        self,
        parent: tk.Misc,
        text: str,
        command,
        *,
        bg: str,
        fg: str,
        hover: str,
        border: bool = False,
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            font=self._fonts.body(),
            bg=bg,
            fg=fg,
            activebackground=hover,
            activeforeground=fg,
            relief="flat",
            bd=0,
            padx=14,
            pady=5,
            cursor="hand2",
        )
        if border:
            button.configure(
                highlightthickness=1,
                highlightbackground=theme.BORDER,
                highlightcolor=theme.BORDER_FOCUS,
            )
        return button

    # ---- 交互 -------------------------------------------------------

    def _hotkey_text(self) -> str:
        return self._hotkey_label

    def _update_retention_hint(self) -> None:
        try:
            days = self._preset_var.get()
        except tk.TclError:
            days = 0
        hint = "置顶的记录不受保留期影响。" if days else "请输入 1–365 之间的整数。"
        self._retention_hint.configure(text=hint)

    def _update_custom_state(self) -> None:
        state = "normal" if self._preset_var.get() == 0 else "disabled"
        try:
            self._custom_entry.configure(state=state)
        except tk.TclError:
            pass

    def _on_preset_changed(self) -> None:
        self._update_custom_state()
        self._update_retention_hint()
        if self._preset_var.get() == 0:
            self._custom_entry.focus_set()

    def _save(self) -> None:
        if self._preset_var.get() == 0:
            try:
                days = config.parse_retention_days(self._custom_var.get())
            except ValueError as exc:
                messagebox.showwarning("保留期无效", str(exc), parent=self)
                self._custom_entry.focus_set()
                return
        else:
            days = self._preset_var.get()
        try:
            self._config.retention_days = days
        except Exception as exc:  # 写库失败时不让面板悄无声息地关掉
            _LOGGER.exception("保存保留期失败")
            messagebox.showerror("保存失败", f"写入设置时出错：\n{exc}", parent=self)
            return
        if self._on_saved is not None:
            self._on_saved()
        self.destroy()

    def _clear_history(self) -> None:
        if self._on_clear is None:
            return
        if not messagebox.askyesno(
            "清空全部历史",
            "将删除全部记录与图片，且无法恢复。\n确定要继续吗？",
            icon="warning",
            parent=self,
        ):
            return
        try:
            count = int(self._on_clear())
        except Exception as exc:
            _LOGGER.exception("清空历史失败")
            messagebox.showerror("清空失败", f"清空历史时出错：\n{exc}", parent=self)
            return
        messagebox.showinfo("已清空", f"已删除 {count} 条记录。", parent=self)

    def _password_action(self) -> None:
        """未设置时进入设置流程，已设置时进入重置流程。"""
        if self._password_set:
            self._reset_password()
        else:
            self._request_set_password()

    def _request_set_password(self) -> None:
        if self._on_set_password is None:
            messagebox.showwarning("暂不可用", "当前无法打开密码设置。", parent=self)
            return
        self._on_set_password()

    def _sync_password_row(self) -> None:
        """按 ``_password_set`` 刷新状态文字与按钮外观。"""
        self._password_state_label.configure(
            text="已设置" if self._password_set else "未设置",
            fg=theme.TEXT_PRIMARY if self._password_set else theme.TEXT_SECONDARY,
        )
        self._password_button.configure(
            text="重置密码" if self._password_set else "设置密码",
            fg=theme.DANGER if self._password_set else theme.PRIMARY,
            state="normal",
            cursor="hand2",
        )

    def mark_password_set(self) -> None:
        """密码在本面板打开期间被设置成功：当场切换为「已设置」。"""
        self._password_set = True
        self._sync_password_row()

    def mark_password_unset(self) -> None:
        """密码被清除后：切换为「未设置 / 设置密码」。"""
        self._password_set = False
        self._sync_password_row()

    def _reset_password(self) -> None:
        if self._on_reset_password is None:
            return
        if not messagebox.askyesno(
            "重置二级密码",
            "重置密码会同时删除所有私密记录，且无法恢复。\n确定要继续吗？",
            icon="warning",
            parent=self,
        ):
            return
        try:
            count = int(self._on_reset_password())
        except Exception as exc:
            _LOGGER.exception("重置密码失败")
            messagebox.showerror("重置失败", f"重置密码时出错：\n{exc}", parent=self)
            return
        self.mark_password_unset()
        messagebox.showinfo(
            "已重置",
            f"二级密码已清除，同时删除了 {count} 条私密记录。",
            parent=self,
        )

    def _open_data_dir(self) -> None:
        try:
            os.startfile(str(self._data_dir))  # noqa: S606 - Windows 专用，打开资源管理器
        except OSError as exc:
            _LOGGER.warning("打开数据目录失败：%s", exc)
            messagebox.showwarning(
                "无法打开",
                f"打不开数据目录：\n{self._data_dir}\n\n{exc}",
                parent=self,
            )

    # ---- 定位 -------------------------------------------------------

    def _place_on_parent(self, master: tk.Misc) -> None:
        self.update_idletasks()
        width = max(self.winfo_reqwidth(), DIALOG_WIDTH)
        height = self.winfo_reqheight()
        try:
            root_x = master.winfo_rootx()
            root_y = master.winfo_rooty()
            root_w = master.winfo_width()
            root_h = master.winfo_height()
        except tk.TclError:
            root_x = root_y = 0
            root_w = root_h = 0
        x = root_x + max((root_w - width) // 2, 0)
        y = root_y + max((root_h - height) // 3, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")


class PasswordDialog(tk.Toplevel):
    """二级密码对话框。

    ``mode="set"`` 让用户设置密码（两次输入），``mode="unlock"`` 输入密码解锁。
    校验与状态变更通过 ``on_submit(password)`` 交回主窗口：返回 ``None`` 表示
    成功并关闭对话框，返回字符串则作为错误提示显示。
    """

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Fonts,
        *,
        mode: str = "unlock",
        on_submit: Callable[[str], str | None],
        hint: str = "",
    ) -> None:
        super().__init__(master)
        self._fonts = fonts
        self._mode = "set" if mode == "set" else "unlock"
        self._on_submit = on_submit
        self._hint = hint
        self._password_var = tk.StringVar(self)
        self._confirm_var = tk.StringVar(self)
        self._confirm_entry: tk.Entry | None = None

        self.title("设置二级密码" if self._mode == "set" else "输入二级密码")
        self.configure(bg=theme.BG_ROOT)
        self.resizable(False, False)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self._build()
        self._place_centered(master)
        self.grab_set()
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self._submit())
        self.after(30, self._focus_first)

    # ---- 界面 -------------------------------------------------------

    def _build(self) -> None:
        body = tk.Frame(self, bg=theme.BG_ROOT, padx=DIALOG_PAD, pady=DIALOG_PAD)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text=self.title(),
            font=self._fonts.title(),
            bg=theme.BG_ROOT,
            fg=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x")

        if self._mode == "set":
            description = f"首次使用私密内容，请设置一个密码（至少 {security.MIN_PASSWORD_LENGTH} 位）。"
        else:
            description = "私密内容需要密码才能查看与复制。"
        tk.Label(
            body,
            text=description,
            font=self._fonts.small(),
            bg=theme.BG_ROOT,
            fg=theme.TEXT_SECONDARY,
            anchor="w",
            justify="left",
            wraplength=PASSWORD_DIALOG_WIDTH - 2 * DIALOG_PAD,
        ).pack(fill="x", pady=(6, 0))
        if self._hint:
            tk.Label(
                body,
                text=self._hint,
                font=self._fonts.small(),
                bg=theme.BG_ROOT,
                fg=theme.TEXT_SECONDARY,
                anchor="w",
                justify="left",
                wraplength=PASSWORD_DIALOG_WIDTH - 2 * DIALOG_PAD,
            ).pack(fill="x", pady=(4, 0))

        tk.Label(
            body,
            text="密码",
            font=self._fonts.body(),
            bg=theme.BG_ROOT,
            fg=theme.TEXT_SECONDARY,
            anchor="w",
        ).pack(fill="x", pady=(12, 4))
        self._password_entry = self._password_entry_widget(body, self._password_var)
        self._password_entry.pack(fill="x", ipady=4)

        if self._mode == "set":
            tk.Label(
                body,
                text="确认密码",
                font=self._fonts.body(),
                bg=theme.BG_ROOT,
                fg=theme.TEXT_SECONDARY,
                anchor="w",
            ).pack(fill="x", pady=(10, 4))
            self._confirm_entry = self._password_entry_widget(body, self._confirm_var)
            self._confirm_entry.pack(fill="x", ipady=4)

        self._error_label = tk.Label(
            body,
            text="",
            font=self._fonts.small(),
            bg=theme.BG_ROOT,
            fg=theme.DANGER,
            anchor="w",
            justify="left",
            wraplength=PASSWORD_DIALOG_WIDTH - 2 * DIALOG_PAD,
        )
        self._error_label.pack(fill="x", pady=(8, 0))

        footer = tk.Frame(body, bg=theme.BG_ROOT)
        footer.pack(fill="x", pady=(DIALOG_PAD, 0))
        self._button(
            footer,
            "解锁" if self._mode == "unlock" else "保存",
            self._submit,
            bg=theme.PRIMARY,
            fg=theme.TEXT_ON_PRIMARY,
            hover=theme.PRIMARY_HOVER,
        ).pack(side="right")
        self._button(
            footer,
            "取消",
            self.destroy,
            bg=theme.BG_CARD,
            fg=theme.TEXT_PRIMARY,
            hover=theme.PRIMARY_LIGHT,
            border=True,
        ).pack(side="right", padx=(0, 8))

    def _password_entry_widget(self, parent: tk.Misc, variable: tk.StringVar) -> tk.Entry:
        return tk.Entry(
            parent,
            textvariable=variable,
            show="*",
            font=self._fonts.body(),
            bg=theme.BG_INPUT,
            fg=theme.TEXT_PRIMARY,
            insertbackground=theme.TEXT_PRIMARY,
            relief="flat",
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            highlightcolor=theme.BORDER_FOCUS,
        )

    def _button(
        self,
        parent: tk.Misc,
        text: str,
        command,
        *,
        bg: str,
        fg: str,
        hover: str,
        border: bool = False,
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            font=self._fonts.body(),
            bg=bg,
            fg=fg,
            activebackground=hover,
            activeforeground=fg,
            relief="flat",
            bd=0,
            padx=14,
            pady=5,
            cursor="hand2",
        )
        if border:
            button.configure(
                highlightthickness=1,
                highlightbackground=theme.BORDER,
                highlightcolor=theme.BORDER_FOCUS,
            )
        return button

    # ---- 交互 -------------------------------------------------------

    def _focus_first(self) -> None:
        try:
            self._password_entry.focus_set()
        except tk.TclError:
            pass

    def _show_error(self, text: str) -> None:
        try:
            self._error_label.configure(text=text)
        except tk.TclError:
            pass

    def _submit(self) -> None:
        password = self._password_var.get()
        if not password:
            self._show_error("请输入密码")
            return
        if self._mode == "set":
            if len(password) < security.MIN_PASSWORD_LENGTH:
                self._show_error(f"密码至少需要 {security.MIN_PASSWORD_LENGTH} 位")
                return
            if password != self._confirm_var.get():
                self._show_error("两次输入的密码不一致")
                return
        try:
            error = self._on_submit(password)
        except Exception as exc:  # 回调异常不能让对话框无声消失
            _LOGGER.exception("密码提交失败")
            self._show_error(f"操作失败：{exc}")
            return
        if error:
            self._show_error(str(error))
            self._password_var.set("")
            if self._confirm_entry is not None:
                self._confirm_var.set("")
                self._confirm_entry.focus_set()
            self._password_entry.focus_set()
            return
        self.destroy()

    # ---- 定位 -------------------------------------------------------

    def _place_centered(self, master: tk.Misc) -> None:
        self.update_idletasks()
        width = max(self.winfo_reqwidth(), PASSWORD_DIALOG_WIDTH)
        height = self.winfo_reqheight()
        try:
            root_x = master.winfo_rootx()
            root_y = master.winfo_rooty()
            root_w = master.winfo_width()
            root_h = master.winfo_height()
        except tk.TclError:
            root_x = root_y = 0
            root_w = root_h = 0
        x = root_x + max((root_w - width) // 2, 0)
        y = root_y + max((root_h - height) // 3, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")


class TextDetailDialog(tk.Toplevel):
    """「查看全文」对话框：只读展示完整文本，可一键复制。"""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Fonts,
        text: str,
        *,
        on_copy: Callable[[], None] | None = None,
        title: str = "查看全文",
    ) -> None:
        super().__init__(master)
        self._fonts = fonts
        self._text = text
        self._on_copy = on_copy
        self._copy_button: tk.Button | None = None
        self._count_label: tk.Label | None = None

        self.title(title)
        self.configure(bg=theme.BG_ROOT)
        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _e: self.destroy())
        self._build()
        self._place_centered(master)

    def _build(self) -> None:
        body = tk.Frame(self, bg=theme.BG_ROOT, padx=DIALOG_PAD, pady=DIALOG_PAD)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text="查看全文",
            font=self._fonts.title(),
            bg=theme.BG_ROOT,
            fg=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x")

        text_area = tk.Frame(body, bg=theme.BG_ROOT)
        text_area.pack(fill="both", expand=True, pady=(12, 0))

        scrollbar = ttk.Scrollbar(text_area, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        viewer = tk.Text(
            text_area,
            wrap="word",
            width=40,
            height=10,
            font=self._fonts.body(),
            bg=theme.BG_CARD,
            fg=theme.TEXT_PRIMARY,
            insertbackground=theme.TEXT_PRIMARY,
            relief="flat",
            bd=0,
            padx=12,
            pady=10,
            spacing1=2,
            spacing3=2,
            yscrollcommand=scrollbar.set,
        )
        viewer.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=viewer.yview)
        viewer.insert("1.0", self._text)
        viewer.configure(state="disabled")

        footer = tk.Frame(body, bg=theme.BG_ROOT)
        footer.pack(fill="x", pady=(12, 0))

        self._count_label = tk.Label(
            footer,
            text=f"共 {len(self._text)} 字",
            font=self._fonts.small(),
            bg=theme.BG_ROOT,
            fg=theme.TEXT_SECONDARY,
        )
        self._count_label.pack(side="left")

        self._button(
            footer,
            "关闭",
            self.destroy,
            bg=theme.BG_CARD,
            fg=theme.TEXT_PRIMARY,
            hover=theme.PRIMARY_LIGHT,
            border=True,
        ).pack(side="right")
        if self._on_copy is not None:
            self._copy_button = self._button(
                footer,
                "复制全文",
                self._copy_all,
                bg=theme.PRIMARY,
                fg=theme.TEXT_ON_PRIMARY,
                hover=theme.PRIMARY_HOVER,
            )
            self._copy_button.pack(side="right", padx=(0, 8))

    def _button(self, parent, text, command, *, bg, fg, hover, border=False) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            font=self._fonts.body(),
            bg=bg,
            fg=fg,
            activebackground=hover,
            activeforeground=fg,
            relief="flat",
            bd=0,
            padx=14,
            pady=5,
            cursor="hand2",
        )
        if border:
            button.configure(
                highlightthickness=1,
                highlightbackground=theme.BORDER,
                highlightcolor=theme.BORDER_FOCUS,
            )
        return button

    def _copy_all(self) -> None:
        if self._on_copy is None:
            return
        try:
            self._on_copy()
        except Exception:  # pragma: no cover - 复制失败只影响提示
            _LOGGER.exception("复制全文失败")
            if self._count_label is not None:
                self._count_label.configure(text="复制失败，请重试")
            return
        if self._copy_button is not None:
            self._copy_button.configure(text="已复制 ✓")
            self.after(1500, self._restore_copy_button)

    def _restore_copy_button(self) -> None:
        if self._copy_button is not None and self._copy_button.winfo_exists():
            self._copy_button.configure(text="复制全文")

    def _place_centered(self, master: tk.Misc) -> None:
        self.update_idletasks()
        width = max(self.winfo_reqwidth(), TEXT_DIALOG_WIDTH)
        height = max(self.winfo_reqheight(), TEXT_DIALOG_HEIGHT)
        try:
            root_x = master.winfo_rootx()
            root_y = master.winfo_rooty()
            root_w = master.winfo_width()
            root_h = master.winfo_height()
        except tk.TclError:
            root_x = root_y = 0
            root_w = root_h = 0
        x = root_x + max((root_w - width) // 2, 0)
        y = root_y + max((root_h - height) // 3, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")
