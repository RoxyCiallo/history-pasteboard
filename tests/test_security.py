"""security.py 与 db.delete_private_items 的单元测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import db  # noqa: E402
import security  # noqa: E402
import tmpdir  # noqa: E402

PASSWORD = "correct-horse"


class _Clock:
    """可推进的单调时钟，避免测试真的等 5 分钟。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class SecurityTestCase(unittest.TestCase):
    """每个用例一个独立临时库与独立的时钟。"""

    def setUp(self) -> None:
        self._tmp = tmpdir.new_dir()
        self.database = db.Database(self._tmp / "history.db")
        self.config = config.Config(self.database)
        self.clock = _Clock()
        self.security = security.Security(self.config, clock=self.clock)
        self._seq = 0

    def tearDown(self) -> None:
        self.database.close()
        tmpdir.remove_dir(self._tmp)

    def _add_item(self, is_private: bool) -> int:
        self._seq += 1
        item_id, _ = self.database.upsert_item(
            kind="text",
            content_hash=f"hash-{self._seq}",
            text_content="secret" if is_private else "plain",
            is_private=is_private,
        )
        return item_id

    # ---- 未设置密码 -------------------------------------------------

    def test_no_password_means_locked(self) -> None:
        self.assertFalse(self.security.is_password_set())
        self.assertFalse(self.security.unlocked)
        self.assertFalse(self.security.verify("anything"))

    # ---- 设置密码 ---------------------------------------------------

    def test_set_password_stores_salt_and_hash(self) -> None:
        self.security.set_password(PASSWORD)
        self.assertTrue(self.security.is_password_set())
        salt_hex = self.config.get("pwd_salt")
        hash_hex = self.config.get("pwd_hash")
        self.assertEqual(len(salt_hex), security.SALT_BYTES * 2)
        self.assertEqual(len(hash_hex), 64)  # sha256
        self.assertEqual(self.config.get("pwd_iterations"), config.DEFAULT_PBKDF2_ITERATIONS)
        self.assertTrue(self.config.get("pwd_set_at"))
        self.assertFalse(self.security.unlocked)

    def test_salt_is_random(self) -> None:
        self.security.set_password(PASSWORD)
        first = self.config.get("pwd_salt")
        self.security.set_password(PASSWORD)
        second = self.config.get("pwd_salt")
        self.assertNotEqual(first, second)
        self.assertTrue(self.security.verify(PASSWORD))

    def test_rejects_short_password(self) -> None:
        with self.assertRaises(ValueError):
            self.security.set_password("abc")

    def test_rejects_blank_password(self) -> None:
        with self.assertRaises(ValueError):
            self.security.set_password("     ")

    # ---- 校验 -------------------------------------------------------

    def test_correct_password_unlocks(self) -> None:
        self.security.set_password(PASSWORD)
        self.assertTrue(self.security.verify(PASSWORD))
        self.assertTrue(self.security.unlocked)

    def test_wrong_password_stays_locked(self) -> None:
        self.security.set_password(PASSWORD)
        self.assertFalse(self.security.verify("wrong"))
        self.assertFalse(self.security.unlocked)
        self.assertEqual(self.security.remaining_attempts(), security.MAX_ATTEMPTS - 1)

    def test_five_failures_lock_temporarily(self) -> None:
        self.security.set_password(PASSWORD)
        for _ in range(security.MAX_ATTEMPTS):
            self.assertFalse(self.security.verify("wrong"))
        self.assertGreater(self.security.remaining_lock_seconds(), 0)
        # 冷却期内即使密码正确也拒绝。
        self.assertFalse(self.security.verify(PASSWORD))

    def test_lock_expires_after_cooldown(self) -> None:
        self.security.set_password(PASSWORD)
        for _ in range(security.MAX_ATTEMPTS):
            self.security.verify("wrong")
        self.config.set("pwd_locked_until", "2000-01-01T00:00:00")
        self.assertEqual(self.security.remaining_lock_seconds(), 0)
        self.assertTrue(self.security.verify(PASSWORD))

    def test_success_resets_failure_counter(self) -> None:
        self.security.set_password(PASSWORD)
        self.security.verify("wrong")
        self.security.verify("wrong")
        self.assertTrue(self.security.verify(PASSWORD))
        self.assertEqual(self.security.remaining_attempts(), security.MAX_ATTEMPTS)
        self.assertEqual(self.config.get("pwd_fail_count"), 0)

    # ---- 会话状态 ---------------------------------------------------

    def test_lock_clears_unlocked(self) -> None:
        self.security.set_password(PASSWORD)
        self.security.verify(PASSWORD)
        self.security.lock()
        self.assertFalse(self.security.unlocked)

    def test_touch_extends_session(self) -> None:
        self.security.set_password(PASSWORD)
        self.security.verify(PASSWORD)
        self.clock.advance(security.SESSION_IDLE_SECONDS - 10)
        self.security.touch()
        self.clock.advance(security.SESSION_IDLE_SECONDS - 10)
        self.assertFalse(self.security.lock_if_idle())
        self.assertTrue(self.security.unlocked)

    def test_idle_session_locks(self) -> None:
        self.security.set_password(PASSWORD)
        self.security.verify(PASSWORD)
        self.clock.advance(security.SESSION_IDLE_SECONDS + 1)
        self.assertTrue(self.security.lock_if_idle())
        self.assertFalse(self.security.unlocked)

    def test_lock_if_idle_is_noop_when_locked(self) -> None:
        self.assertFalse(self.security.lock_if_idle())

    # ---- 重置 -------------------------------------------------------

    def test_reset_clears_password(self) -> None:
        self.security.set_password(PASSWORD)
        self.security.verify(PASSWORD)
        self.security.reset_password()
        self.assertFalse(self.security.is_password_set())
        self.assertFalse(self.security.unlocked)
        self.assertEqual(self.config.get("pwd_salt"), "")
        self.assertEqual(self.config.get("pwd_iterations"), config.DEFAULT_PBKDF2_ITERATIONS)

    # ---- 私密卡片删除 -----------------------------------------------

    def test_delete_private_items(self) -> None:
        private_ids = [self._add_item(True), self._add_item(True)]
        plain_id = self._add_item(False)

        deleted = self.database.delete_private_items()

        self.assertEqual(len(deleted), 2)
        self.assertEqual({row["id"] for row in deleted}, set(private_ids))
        self.assertEqual(self.database.count(), 1)
        self.assertIsNotNone(self.database.get_item(plain_id))

    def test_delete_private_items_when_none(self) -> None:
        self._add_item(False)
        self.assertEqual(self.database.delete_private_items(), [])
        self.assertEqual(self.database.count(), 1)


if __name__ == "__main__":
    unittest.main()
