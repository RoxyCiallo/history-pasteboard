"""卡片「查看全文」入口的显示规则（VIEW-01…VIEW-07）。"""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from ui import card  # noqa: E402


class _FontsStub:
    """不依赖真实 Tk 字体系统的轻量替身。"""

    def body(self):
        return ("Microsoft YaHei UI", 10)

    def body_bold(self):
        return ("Microsoft YaHei UI", 10, "bold")

    def small(self):
        return ("Microsoft YaHei UI", 9)

    def title(self):
        return ("Microsoft YaHei UI", 13, "bold")


LONG_TEXT = "这是一段很长的文字，" * 40
SHORT_TEXT = "短文本"


def _item(text: str, *, kind: str = "text", is_private: int = 0) -> dict:
    return {
        "id": 1,
        "kind": kind,
        "text_content": text,
        "is_private": is_private,
        "pinned": 0,
        "image_path": None,
        "thumb_path": None,
        "width": None,
        "height": None,
        "byte_size": None,
        "created_at": "2026-10-21T10:00:00",
        "updated_at": "2026-10-21T10:00:00",
    }


class ViewButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover - 无显示环境时跳过
            raise unittest.SkipTest(f"无图形环境：{exc}")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:
            pass

    def _make(self, item: dict, *, on_view=lambda _item: None, unlocked: bool = False) -> card.ClipCard:
        return card.ClipCard(
            self.root,
            item,
            fonts=_FontsStub(),
            thumb_loader=lambda _item: None,
            width=600,
            on_copy=lambda _item: None,
            on_pin=lambda _item: None,
            on_delete=lambda _item: None,
            on_unlock=lambda _item: None,
            on_view=on_view,
            unlocked=unlocked,
        )

    def test_long_text_shows_view_button(self):
        widget = self._make(_item(LONG_TEXT))
        self.assertIsNotNone(widget._view_button)

    def test_short_text_hides_view_button(self):
        widget = self._make(_item(SHORT_TEXT))
        self.assertIsNone(widget._view_button)

    def test_missing_callback_hides_view_button(self):
        widget = self._make(_item(LONG_TEXT), on_view=None)
        self.assertIsNone(widget._view_button)

    def test_image_card_never_shows_view_button(self):
        widget = self._make(_item("", kind="image"))
        self.assertIsNone(widget._view_button)

    def test_locked_private_card_hides_view_button(self):
        widget = self._make(_item(LONG_TEXT, is_private=1))
        self.assertIsNone(widget._view_button)

    def test_unlocked_private_card_shows_view_button(self):
        widget = self._make(_item(LONG_TEXT, is_private=1), unlocked=True)
        self.assertIsNotNone(widget._view_button)

    def test_clicking_view_button_invokes_callback(self):
        seen: list[dict] = []
        widget = self._make(_item(LONG_TEXT), on_view=seen.append)
        self.assertTrue(widget._view_button.bind("<Button-1>"))
        widget._on_view_click()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["text_content"], LONG_TEXT)


if __name__ == "__main__":
    unittest.main()
