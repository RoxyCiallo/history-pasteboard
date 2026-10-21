"""db.py 的单元测试：schema、去重、排序、搜索、置顶、清理、分页。"""

from __future__ import annotations

import datetime as _dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402
import tmpdir  # noqa: E402


class DatabaseTestCase(unittest.TestCase):
    """每个用例一个独立的临时库。"""

    def setUp(self) -> None:
        self._tmp = tmpdir.new_dir()
        self.db_path = self._tmp / "history.db"
        self.database = db.Database(self.db_path)

    def tearDown(self) -> None:
        self.database.close()
        tmpdir.remove_dir(self._tmp)

    # ---- 辅助 -----------------------------------------------------

    def add_text(self, text: str, stamp: str, *, pinned: bool = False, private: bool = False) -> int:
        """插入一条文本记录，返回 id。"""
        item_id, _ = self.database.upsert_item(
            kind="text",
            content_hash=_hash(text),
            text_content=text,
            is_private=private,
            now=stamp,
        )
        if pinned:
            self.database.toggle_pin(item_id, now=stamp)
        return item_id

    # ---- schema ---------------------------------------------------

    def test_schema_version_is_current(self) -> None:
        row = self.database._conn.execute("SELECT version FROM schema_meta").fetchone()
        self.assertEqual(row["version"], db.SCHEMA_VERSION)

    def test_tables_exist(self) -> None:
        names = {
            row["name"]
            for row in self.database._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        self.assertTrue({"items", "settings", "schema_meta"} <= names)

    def test_reopen_keeps_data(self) -> None:
        self.add_text("持久化", "2026-10-21T09:00:00")
        self.database.close()
        reopened = db.Database(self.db_path)
        self.assertEqual(reopened.count(), 1)
        reopened.close()

    # ---- 写入与去重 -------------------------------------------------

    def test_insert_returns_created(self) -> None:
        item_id, created = self.database.upsert_item(
            kind="text", content_hash="abc", text_content="你好", now="2026-10-21T10:00:00"
        )
        self.assertTrue(created)
        self.assertGreater(item_id, 0)
        item = self.database.get_item(item_id)
        assert item is not None
        self.assertEqual(item["text_content"], "你好")
        self.assertFalse(item["pinned"])
        self.assertFalse(item["is_private"])

    def test_duplicate_hash_refreshes_time_only(self) -> None:
        first_id, created1 = self.database.upsert_item(
            kind="text", content_hash="same", text_content="重复", now="2026-10-20T10:00:00"
        )
        second_id, created2 = self.database.upsert_item(
            kind="text", content_hash="same", text_content="重复", now="2026-10-21T10:00:00"
        )
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(first_id, second_id)
        self.assertEqual(self.database.count(), 1)
        item = self.database.get_item(first_id)
        assert item is not None
        self.assertEqual(item["updated_at"], "2026-10-21T10:00:00")
        self.assertEqual(item["created_at"], "2026-10-20T10:00:00")

    def test_duplicate_can_upgrade_to_private(self) -> None:
        item_id, _ = self.database.upsert_item(
            kind="text", content_hash="p", text_content="密码", now="2026-10-21T10:00:00"
        )
        self.database.upsert_item(
            kind="text", content_hash="p", text_content="密码", is_private=True,
            now="2026-10-21T10:01:00",
        )
        item = self.database.get_item(item_id)
        assert item is not None
        self.assertTrue(item["is_private"])

    def test_invalid_kind_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.database.upsert_item(kind="file", content_hash="x")

    # ---- 排序与分页 -------------------------------------------------

    def test_order_pinned_first_then_time_desc(self) -> None:
        old = self.add_text("最旧", "2026-10-21T08:00:00")
        new = self.add_text("最新", "2026-10-21T12:00:00")
        pinned = self.add_text("置顶", "2026-10-20T08:00:00", pinned=True)

        ids = [row["id"] for row in self.database.list_items()]
        self.assertEqual(ids[0], pinned)
        self.assertEqual(ids[1:], [new, old])

    def test_pagination(self) -> None:
        for index in range(5):
            self.add_text(f"第{index}条", f"2026-10-21T1{index}:00:00")
        first_page = self.database.list_items(limit=2, offset=0)
        second_page = self.database.list_items(limit=2, offset=2)
        self.assertEqual(len(first_page), 2)
        self.assertEqual(len(second_page), 2)
        self.assertNotEqual(first_page[0]["id"], second_page[0]["id"])

    # ---- 置顶 -----------------------------------------------------

    def test_toggle_pin(self) -> None:
        item_id = self.add_text("可置顶", "2026-10-21T10:00:00")
        self.assertTrue(self.database.toggle_pin(item_id, now="2026-10-21T11:00:00"))
        item = self.database.get_item(item_id)
        assert item is not None
        self.assertTrue(item["pinned"])
        self.assertEqual(item["pinned_at"], "2026-10-21T11:00:00")

        self.assertFalse(self.database.toggle_pin(item_id, now="2026-10-21T12:00:00"))
        item = self.database.get_item(item_id)
        assert item is not None
        self.assertFalse(item["pinned"])
        self.assertIsNone(item["pinned_at"])

    def test_toggle_pin_missing_returns_none(self) -> None:
        self.assertIsNone(self.database.toggle_pin(999))

    # ---- 删除 -----------------------------------------------------

    def test_delete_item_returns_payload(self) -> None:
        item_id = self.add_text("待删除", "2026-10-21T10:00:00")
        payload = self.database.delete_item(item_id)
        assert payload is not None
        self.assertEqual(payload["text_content"], "待删除")
        self.assertIsNone(self.database.get_item(item_id))
        self.assertIsNone(self.database.delete_item(item_id))

    def test_clear_all_returns_rows(self) -> None:
        self.add_text("甲", "2026-10-21T10:00:00")
        self.add_text("乙", "2026-10-21T10:01:00")
        removed = self.database.clear_all()
        self.assertEqual(len(removed), 2)
        self.assertEqual(self.database.count(), 0)

    # ---- 搜索 -----------------------------------------------------

    def test_search_matches_substring(self) -> None:
        self.add_text("会议纪要 周三", "2026-10-21T10:00:00")
        self.add_text("购物清单", "2026-10-21T10:01:00")
        result = self.database.search("会议")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text_content"], "会议纪要 周三")

    def test_search_is_case_insensitive_for_ascii(self) -> None:
        self.add_text("Hello World", "2026-10-21T10:00:00")
        self.assertEqual(len(self.database.search("hello")), 1)

    def test_search_escapes_wildcards(self) -> None:
        self.add_text("进度 100% 完成", "2026-10-21T10:00:00")
        self.add_text("进度 1000 完成", "2026-10-21T10:01:00")
        result = self.database.search("%")
        self.assertEqual(len(result), 1)
        self.assertIn("100%", result[0]["text_content"])

    def test_search_escapes_underscore(self) -> None:
        self.add_text("变量 a_b", "2026-10-21T10:00:00")
        self.add_text("变量 aXb", "2026-10-21T10:01:00")
        result = self.database.search("_")
        self.assertEqual(len(result), 1)
        self.assertIn("a_b", result[0]["text_content"])

    def test_search_blank_returns_all(self) -> None:
        self.add_text("一", "2026-10-21T10:00:00")
        self.add_text("二", "2026-10-21T10:01:00")
        self.assertEqual(len(self.database.search("   ")), 2)

    # ---- 清理 -----------------------------------------------------

    def test_purge_removes_expired_but_keeps_pinned(self) -> None:
        expired = self.add_text("过期", "2026-10-17T10:00:00")
        fresh = self.add_text("未过期", "2026-10-20T10:00:00")
        pinned = self.add_text("置顶旧记录", "2026-01-01T10:00:00", pinned=True)

        removed = self.database.purge_expired(
            retention_days=3, now=_dt.datetime(2026, 10, 21, 12, 0, 0)
        )
        self.assertEqual([row["id"] for row in removed], [expired])
        remaining = {row["id"] for row in self.database.list_items()}
        self.assertEqual(remaining, {fresh, pinned})

    def test_purge_rejects_invalid_days(self) -> None:
        with self.assertRaises(ValueError):
            self.database.purge_expired(0)

    # ---- 时间刷新 -------------------------------------------------

    def test_touch_item(self) -> None:
        item_id, _ = self.database.upsert_item(
            kind="text", content_hash="t", text_content="再来一次", now="2026-10-21T10:00:00"
        )
        self.database.touch_item(item_id, now="2026-10-21T15:00:00")
        item = self.database.get_item(item_id)
        assert item is not None
        self.assertEqual(item["updated_at"], "2026-10-21T15:00:00")

    # ---- 设置读写 -------------------------------------------------

    def test_settings_roundtrip(self) -> None:
        self.assertIsNone(self.database.get_setting("retention_days"))
        self.database.set_setting("retention_days", "5")
        self.assertEqual(self.database.get_setting("retention_days"), "5")
        self.database.set_setting("retention_days", "7")
        self.assertEqual(self.database.get_setting("retention_days"), "7")
        self.database.delete_setting("retention_days")
        self.assertIsNone(self.database.get_setting("retention_days"))

    def test_count_with_keyword(self) -> None:
        self.add_text("苹果", "2026-10-21T10:00:00")
        self.add_text("香蕉", "2026-10-21T10:01:00")
        self.assertEqual(self.database.count(), 2)
        self.assertEqual(self.database.count("苹果"), 1)


def _hash(text: str) -> str:
    """测试用 sha256，避免依赖 storage 模块。"""
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    unittest.main()
