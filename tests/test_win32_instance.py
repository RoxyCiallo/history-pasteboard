"""win32.SingleInstance / ActivateWatcher 的测试：单实例判定与唤起通知。

互斥体与事件都是系统级对象，测试统一用 ``uuid4`` 生成一次性名字，
避免和真实运行中的程序（`Local\\PasteBoard.*`）互相干扰。
"""

from __future__ import annotations

import queue
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import win32  # noqa: E402


@unittest.skipUnless(win32.available(), "需要 Windows 才能测试互斥体与事件")
class SingleInstanceTests(unittest.TestCase):
    """单实例判定：第一个拿到、第二个被拒并通知对方。"""

    def setUp(self) -> None:
        token = uuid.uuid4().hex
        self.mutex_name = f"Local\\PasteBoardTest-{token}"
        self.event_name = f"Local\\PasteBoardTestEvt-{token}"
        self.instances: list[win32.SingleInstance] = []

    def tearDown(self) -> None:
        for instance in self.instances:
            instance.close()

    def _make(self) -> win32.SingleInstance:
        instance = win32.SingleInstance(self.mutex_name, self.event_name)
        self.instances.append(instance)
        return instance

    def test_first_instance_acquires(self) -> None:
        self.assertTrue(self._make().acquire())

    def test_second_instance_is_rejected(self) -> None:
        first = self._make()
        self.assertTrue(first.acquire())
        second = self._make()
        self.assertFalse(second.acquire())
        # 第二个实例不应该持有互斥体，close 也不应出错。
        second.close()

    def test_activate_event_wakes_waiter(self) -> None:
        first = self._make()
        self.assertTrue(first.acquire())
        events: "queue.Queue" = queue.Queue()
        watcher = win32.ActivateWatcher(first, events, poll_ms=50)
        watcher.start()
        try:
            second = self._make()
            self.assertFalse(second.acquire())
            kind, payload = events.get(timeout=3.0)
            self.assertEqual(kind, "activate")
            self.assertIsNone(payload)
        finally:
            watcher.stop()

    def test_wait_times_out_without_signal(self) -> None:
        first = self._make()
        self.assertTrue(first.acquire())
        self.assertFalse(first.wait(50))

    def test_close_is_idempotent(self) -> None:
        instance = self._make()
        self.assertTrue(instance.acquire())
        instance.close()
        instance.close()
        self.assertFalse(instance.wait(10))

    def test_names_are_isolated(self) -> None:
        """两个不同名字的实例互不影响。"""
        first = self._make()
        self.assertTrue(first.acquire())
        other_name = f"Local\\PasteBoardTest2-{uuid.uuid4().hex}"
        other = win32.SingleInstance(other_name, other_name + "-evt")
        self.instances.append(other)
        self.assertTrue(other.acquire())


if __name__ == "__main__":
    unittest.main()
