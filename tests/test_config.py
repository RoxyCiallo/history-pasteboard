"""config.py 的单元测试：默认值、类型转换、范围校验。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import db  # noqa: E402
import tmpdir  # noqa: E402


class ConfigTestCase(unittest.TestCase):
    """每个用例一个独立的临时库。"""

    def setUp(self) -> None:
        self._tmp = tmpdir.new_dir()
        self.database = db.Database(self._tmp / "history.db")
        self.config = config.Config(self.database)

    def tearDown(self) -> None:
        self.database.close()
        tmpdir.remove_dir(self._tmp)

    # ---- 默认值 -----------------------------------------------------

    def test_defaults(self) -> None:
        self.assertEqual(self.config.get("retention_days"), 3)
        self.assertEqual(self.config.get("hotkey"), "ctrl+shift+v")
        self.assertFalse(self.config.get("hide_hint_shown"))
        self.assertEqual(self.config.get("window_geometry"), "")
        self.assertEqual(self.config.get("pwd_hash"), "")
        self.assertEqual(self.config.get("pwd_iterations"), config.DEFAULT_PBKDF2_ITERATIONS)

    def test_get_all_covers_every_spec(self) -> None:
        self.assertEqual(set(self.config.get_all()), set(config.SPECS))

    # ---- 读写 -------------------------------------------------------

    def test_int_roundtrip(self) -> None:
        self.config.set("retention_days", 7)
        self.assertEqual(self.config.get("retention_days"), 7)
        self.assertEqual(self.database.get_setting("retention_days"), "7")

    def test_bool_roundtrip(self) -> None:
        self.config.set("hide_hint_shown", True)
        self.assertTrue(self.config.get("hide_hint_shown"))
        self.assertEqual(self.database.get_setting("hide_hint_shown"), "1")
        self.config.set("hide_hint_shown", False)
        self.assertFalse(self.config.get("hide_hint_shown"))

    def test_str_roundtrip(self) -> None:
        self.config.set("window_geometry", "900x680+100+50")
        self.assertEqual(self.config.get("window_geometry"), "900x680+100+50")

    # ---- 校验 -------------------------------------------------------

    def test_retention_bounds_accepted(self) -> None:
        for days in (config.MIN_RETENTION_DAYS, config.MAX_RETENTION_DAYS):
            self.config.set("retention_days", days)
            self.assertEqual(self.config.get("retention_days"), days)

    def test_retention_out_of_range_rejected(self) -> None:
        for days in (0, -1, config.MAX_RETENTION_DAYS + 1):
            with self.assertRaises(ValueError):
                self.config.set("retention_days", days)

    def test_retention_non_numeric_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.config.set("retention_days", "三天")
        with self.assertRaises(ValueError):
            self.config.set("retention_days", True)

    def test_unknown_key_rejected(self) -> None:
        with self.assertRaises(KeyError):
            self.config.get("no_such_key")
        with self.assertRaises(KeyError):
            self.config.set("no_such_key", 1)

    # ---- 脏数据回退 -------------------------------------------------

    def test_dirty_value_falls_back_to_default(self) -> None:
        self.database.set_setting("retention_days", "垃圾数据")
        self.assertEqual(self.config.get("retention_days"), config.DEFAULT_RETENTION_DAYS)
        self.database.set_setting("retention_days", "9999")
        self.assertEqual(self.config.get("retention_days"), config.DEFAULT_RETENTION_DAYS)

    # ---- 便捷属性 ---------------------------------------------------

    def test_retention_days_property(self) -> None:
        self.assertEqual(self.config.retention_days, 3)
        self.config.retention_days = 5
        self.assertEqual(self.config.retention_days, 5)


class ParseRetentionDaysTests(unittest.TestCase):
    """设置面板输入 → 保留天数的解析（CF 之外的纯函数）。"""

    def test_accepts_integer_text(self) -> None:
        self.assertEqual(config.parse_retention_days("3"), 3)
        self.assertEqual(config.parse_retention_days(" 7 "), 7)
        self.assertEqual(config.parse_retention_days(365), 365)

    def test_rejects_out_of_range(self) -> None:
        for value in ("0", "-1", "366", "9999"):
            with self.assertRaises(ValueError, msg=value):
                config.parse_retention_days(value)

    def test_rejects_non_integer(self) -> None:
        for value in ("", "三天", "3.5", None, True):
            with self.assertRaises(ValueError, msg=repr(value)):
                config.parse_retention_days(value)


if __name__ == "__main__":
    unittest.main()
