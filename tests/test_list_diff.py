"""列表差异判断（UI-11…UI-18）：决定是否需要重绘，直接关系到会不会闪屏。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from ui.main_window import items_changed  # noqa: E402


def _item(item_id: int, updated_at: str = "2026-10-24T10:00:00", **extra):
    data = {"id": item_id, "updated_at": updated_at, "pinned": 0, "is_private": 0}
    data.update(extra)
    return data


class ItemsChangedTests(unittest.TestCase):
    def test_both_empty(self) -> None:
        self.assertFalse(items_changed([], []))

    def test_identical_lists(self) -> None:
        old = [_item(1), _item(2)]
        new = [_item(1), _item(2)]
        self.assertFalse(items_changed(old, new))

    def test_new_item_added(self) -> None:
        self.assertTrue(items_changed([_item(1)], [_item(2), _item(1)]))

    def test_item_removed(self) -> None:
        self.assertTrue(items_changed([_item(1), _item(2)], [_item(1)]))

    def test_order_changed(self) -> None:
        self.assertTrue(items_changed([_item(1), _item(2)], [_item(2), _item(1)]))

    def test_updated_at_changed(self) -> None:
        old = [_item(1, "2026-10-24T10:00:00")]
        new = [_item(1, "2026-10-24T10:00:05")]
        self.assertTrue(items_changed(old, new))

    def test_pinned_changed(self) -> None:
        self.assertTrue(items_changed([_item(1, pinned=0)], [_item(1, pinned=1)]))

    def test_private_changed(self) -> None:
        self.assertTrue(items_changed([_item(1, is_private=0)], [_item(1, is_private=1)]))

    def test_irrelevant_field_ignored(self) -> None:
        old = [_item(1, text_content="旧内容")]
        new = [_item(1, text_content="新内容")]
        self.assertFalse(items_changed(old, new))


if __name__ == "__main__":
    unittest.main()
