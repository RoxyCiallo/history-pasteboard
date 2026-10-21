"""界面纯函数测试：时间格式、字节大小、圆角顶点、按像素断行。"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

APP_DIR = Path(__file__).resolve().parent.parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from ui import card  # noqa: E402
from ui.main_window import format_time, human_size  # noqa: E402


class RoundedPointsTests(unittest.TestCase):
    def test_four_corners_are_sampled(self) -> None:
        points = card.rounded_points(0, 0, 100, 50, radius=10, steps=4)
        # 每个角 steps+1 个点，每点两个坐标。
        self.assertEqual(len(points), 4 * 5 * 2)
        xs = points[0::2]
        ys = points[1::2]
        self.assertGreaterEqual(min(xs), 0)
        self.assertLessEqual(max(xs), 100)
        self.assertGreaterEqual(min(ys), 0)
        self.assertLessEqual(max(ys), 50)

    def test_radius_clamped_to_half_size(self) -> None:
        points = card.rounded_points(0, 0, 20, 10, radius=999, steps=2)
        for value in points:
            self.assertGreaterEqual(value, 0)
        self.assertLessEqual(max(points[0::2]), 20)

    def test_zero_radius_is_plain_rectangle(self) -> None:
        points = card.rounded_points(0, 0, 10, 10, radius=0)
        self.assertEqual(points, [0, 0, 10, 0, 10, 10, 0, 10])


class FormatTimeTests(unittest.TestCase):
    NOW = datetime(2026, 10, 21, 15, 30, 0)

    def test_today(self) -> None:
        self.assertEqual(format_time("2026-10-21T09:05:00", now=self.NOW), "今天 09:05")

    def test_yesterday(self) -> None:
        self.assertEqual(format_time("2026-10-20T23:59:00", now=self.NOW), "昨天 23:59")

    def test_older(self) -> None:
        self.assertEqual(
            format_time("2026-10-18T21:05:00", now=self.NOW), "2026-10-18 21:05"
        )

    def test_invalid_text_returned_as_is(self) -> None:
        self.assertEqual(format_time("not-a-time"), "not-a-time")
        self.assertEqual(format_time(""), "")


class HumanSizeTests(unittest.TestCase):
    def test_bytes(self) -> None:
        self.assertEqual(human_size(512), "512 B")

    def test_kilobytes(self) -> None:
        self.assertEqual(human_size(2048), "2 KB")

    def test_megabytes(self) -> None:
        self.assertEqual(human_size(3 * 1024 * 1024), "3.0 MB")

    def test_none(self) -> None:
        self.assertEqual(human_size(None), "0 B")


class ClipLinesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk

        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover - 无桌面环境
            raise unittest.SkipTest(f"没有可用的 Tk 显示：{exc}")
        cls.root.withdraw()
        import tkinter.font as tkfont

        cls.font = tkfont.Font(cls.root, font=("Microsoft YaHei UI", 10))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.root.destroy()

    def test_short_text_kept(self) -> None:
        self.assertEqual(card.clip_lines("你好", self.font, 500), "你好")

    def test_empty_text(self) -> None:
        self.assertEqual(card.clip_lines("", self.font, 500), "")

    def test_hard_line_break_respected(self) -> None:
        self.assertEqual(card.clip_lines("a\nb", self.font, 500), "a\nb")

    def test_long_line_is_wrapped_and_truncated(self) -> None:
        text = "很长的一段中文内容" * 30
        result = card.clip_lines(text, self.font, 120)
        lines = result.split("\n")
        self.assertLessEqual(len(lines), card.TEXT_MAX_LINES)
        self.assertTrue(lines[-1].endswith("…"))

    def test_line_count_limited(self) -> None:
        text = "\n".join(f"第{i}行" for i in range(10))
        result = card.clip_lines(text, self.font, 500)
        self.assertLessEqual(len(result.split("\n")), card.TEXT_MAX_LINES)


if __name__ == "__main__":
    unittest.main()
