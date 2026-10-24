"""设置面板测试：保留期取值、保存与清空历史回调。

面板依赖 tkinter；无图形环境时整组跳过。
"""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

APP_DIR = Path(__file__).resolve().parent.parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import config  # noqa: E402
from ui import dialogs  # noqa: E402


class _ConfigStub:
    """只实现设置面板用到的接口。"""

    APP_VERSION = "0.5.0"

    def __init__(self, retention_days: int = 3) -> None:
        self.retention_days = retention_days
        self.saved: list[int] = []

    def set(self, key: str, value) -> None:  # pragma: no cover - 面板不直接调用
        self.saved.append(int(value))


def _new_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - 无图形环境
        raise unittest.SkipTest(f"没有可用的图形环境：{exc}")
    root.withdraw()
    return root


class SettingsDialogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = _new_root()
        self.addCleanup(self.root.destroy)

    def _make(self, retention_days: int = 3, **kwargs) -> dialogs.SettingsDialog:
        cfg = kwargs.pop("cfg", _ConfigStub(retention_days))
        dialog = dialogs.SettingsDialog(
            self.root,
            _fonts_stub(),
            cfg,
            "C:/data",
            **kwargs,
        )
        self.addCleanup(dialog.destroy)
        return dialog

    def test_preset_selected_when_value_is_preset(self) -> None:
        dialog = self._make(3)
        self.assertEqual(dialog._preset_var.get(), 3)
        self.assertFalse(dialog._use_custom)
        self.assertEqual(str(dialog._custom_entry.cget("state")), "disabled")

    def test_custom_selected_when_value_not_preset(self) -> None:
        dialog = self._make(10)
        self.assertEqual(dialog._preset_var.get(), 0)
        self.assertTrue(dialog._use_custom)
        self.assertEqual(dialog._custom_var.get(), "10")
        self.assertEqual(str(dialog._custom_entry.cget("state")), "normal")

    def test_save_preset_writes_config(self) -> None:
        cfg = _ConfigStub(3)
        calls: list[int] = []
        dialog = self._make(cfg=cfg, on_saved=lambda: calls.append(1))
        dialog._preset_var.set(7)
        dialog._save()
        self.assertEqual(cfg.retention_days, 7)
        self.assertEqual(calls, [1])

    def test_save_custom_value(self) -> None:
        cfg = _ConfigStub(3)
        dialog = self._make(cfg=cfg)
        dialog._preset_var.set(0)
        dialog._custom_var.set(" 30 ")
        dialog._save()
        self.assertEqual(cfg.retention_days, 30)

    def test_invalid_custom_value_is_rejected(self) -> None:
        cfg = _ConfigStub(10)
        dialog = self._make(cfg=cfg)
        dialog._preset_var.set(0)
        dialog._custom_var.set("0")
        with mock.patch.object(dialogs.messagebox, "showwarning") as warning:
            dialog._save()
        warning.assert_called_once()
        self.assertEqual(cfg.retention_days, 10)
        self.assertTrue(dialog.winfo_exists())

    def test_clear_history_calls_callback_and_reports_count(self) -> None:
        dialog = self._make(on_clear=lambda: 5)
        with mock.patch.object(dialogs.messagebox, "askyesno", return_value=True), \
                mock.patch.object(dialogs.messagebox, "showinfo") as info:
            dialog._clear_history()
        info.assert_called_once()
        self.assertIn("5", info.call_args[0][1])

    def test_clear_history_cancelled_does_nothing(self) -> None:
        calls: list[int] = []
        dialog = self._make(on_clear=lambda: calls.append(1) or 0)
        with mock.patch.object(dialogs.messagebox, "askyesno", return_value=False):
            dialog._clear_history()
        self.assertEqual(calls, [])

    def test_hotkey_label_is_shown(self) -> None:
        dialog = self._make(hotkey_label="Ctrl+Alt+V")
        self.assertEqual(dialog._hotkey_text(), "Ctrl+Alt+V")

    def test_password_row_unset_offers_set_button(self) -> None:
        """0.3.0：未设置密码时按钮必须是「设置密码」且可点。"""
        dialog = self._make(password_set=False)
        self.assertEqual(dialog._password_state_label.cget("text"), "未设置")
        self.assertEqual(dialog._password_button.cget("text"), "设置密码")
        self.assertEqual(str(dialog._password_button.cget("state")), "normal")

    def test_password_row_set_offers_reset_button(self) -> None:
        dialog = self._make(password_set=True)
        self.assertEqual(dialog._password_state_label.cget("text"), "已设置")
        self.assertEqual(dialog._password_button.cget("text"), "重置密码")
        self.assertEqual(str(dialog._password_button.cget("state")), "normal")

    def test_set_password_action_calls_callback(self) -> None:
        calls: list[int] = []
        dialog = self._make(password_set=False, on_set_password=lambda: calls.append(1))
        dialog._password_action()
        self.assertEqual(calls, [1])

    def test_mark_password_set_updates_row(self) -> None:
        dialog = self._make(password_set=False)
        dialog.mark_password_set()
        self.assertEqual(dialog._password_state_label.cget("text"), "已设置")
        self.assertEqual(dialog._password_button.cget("text"), "重置密码")

    def test_mark_password_unset_restores_set_button(self) -> None:
        dialog = self._make(password_set=True)
        dialog.mark_password_unset()
        self.assertEqual(dialog._password_state_label.cget("text"), "未设置")
        self.assertEqual(dialog._password_button.cget("text"), "设置密码")


def _fonts_stub():
    """返回最小可用的字体工厂，避免真正查询系统字体。"""

    class _Fonts:
        def title(self):
            return ("Microsoft YaHei UI", 13, "bold")

        def body(self):
            return ("Microsoft YaHei UI", 10)

        def body_bold(self):
            return ("Microsoft YaHei UI", 10, "bold")

        def small(self):
            return ("Microsoft YaHei UI", 9)

    return _Fonts()


if __name__ == "__main__":
    unittest.main()
