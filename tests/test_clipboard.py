"""`app/clipboard.py` 的单元测试：内容规范化、上限判断、入库编排。

真实剪贴板读写依赖桌面会话，不在这里测（见 `docs/06` 手动验收清单）。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image  # noqa: E402

import clipboard  # noqa: E402
import db  # noqa: E402
import storage  # noqa: E402
import tmpdir  # noqa: E402


class FakeReader:
    """模拟剪贴板读取器。"""

    def __init__(self, text=None, image=None, private=False):
        self._text = text
        self._image = image
        self._private = private

    def read_text(self):
        return self._text

    def read_image(self):
        return self._image

    def has_private_marker(self):
        return self._private


class FakeImage:
    """只有 size 属性的假图片，用于尺寸判断。"""

    def __init__(self, width, height):
        self.size = (width, height)


class NormalizeTextTests(unittest.TestCase):
    """CB-01/02/03：文本清洗。"""

    def test_cb01_strips_and_normalizes_newlines(self):
        self.assertEqual(clipboard.normalize_text("  a\r\nb\rc  "), "a\nb\nc")

    def test_cb02_blank_text_is_dropped(self):
        for raw in ("", "   ", "\r\n\t ", None):
            with self.subTest(raw=raw):
                self.assertIsNone(clipboard.normalize_text(raw))

    def test_cb03_too_long_text_is_dropped(self):
        too_long = "字" * (storage.MAX_TEXT_BYTES // 3 + 2)
        self.assertTrue(storage.text_too_large(too_long))
        self.assertIsNone(clipboard.normalize_text(too_long))

    def test_cb04_hash_is_stable(self):
        first = storage.sha256_text("同一段文字")
        second = storage.sha256_text("同一段文字")
        self.assertEqual(first, second)
        self.assertNotEqual(first, storage.sha256_text("另一段文字"))


class IsAcceptableImageTests(unittest.TestCase):
    """CB-05/06/07：图片尺寸判断。"""

    def test_cb05_size_over_limit(self):
        self.assertFalse(clipboard.is_acceptable_image(FakeImage(storage.MAX_IMAGE_SIDE + 1, 10)))

    def test_cb05_zero_size(self):
        self.assertFalse(clipboard.is_acceptable_image(FakeImage(0, 0)))

    def test_cb06_not_an_image(self):
        self.assertFalse(clipboard.is_acceptable_image(object()))
        self.assertFalse(clipboard.is_acceptable_image(None))

    def test_cb07_normal_image(self):
        self.assertTrue(clipboard.is_acceptable_image(FakeImage(480, 300)))
        self.assertTrue(clipboard.is_acceptable_image(FakeImage(storage.MAX_IMAGE_SIDE, 10)))


class CaptureTestCase(unittest.TestCase):
    """入库编排：文本优先、私密标记、去重、图片落盘。"""

    def setUp(self):
        self._tmp = tmpdir.new_dir()
        self.data_dir = storage.ensure_layout(self._tmp / "data")
        self.database = db.Database(storage.db_path(self.data_dir))

    def tearDown(self):
        self.database.close()
        tmpdir.remove_dir(self._tmp)

    def test_capture_text(self):
        event = clipboard.capture(self.database, self.data_dir, FakeReader(text="  你好  "))
        self.assertEqual(event["kind"], "text")
        self.assertTrue(event["created"])
        self.assertEqual(self.database.count(), 1)
        self.assertEqual(self.database.list_items()[0]["text_content"], "你好")

    def test_capture_private_text(self):
        event = clipboard.capture(
            self.database, self.data_dir, FakeReader(text="密码 hunter2", private=True)
        )
        self.assertTrue(event["private"])
        self.assertTrue(self.database.list_items()[0]["is_private"])

    def test_capture_duplicate_refreshes_instead_of_inserting(self):
        first = clipboard.capture(self.database, self.data_dir, FakeReader(text="重复内容"))
        second = clipboard.capture(self.database, self.data_dir, FakeReader(text="重复内容"))
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.database.count(), 1)

    def test_capture_blank_clipboard_returns_none(self):
        self.assertIsNone(clipboard.capture(self.database, self.data_dir, FakeReader()))
        self.assertEqual(self.database.count(), 0)

    def test_capture_image(self):
        image = Image.new("RGB", (480, 300), (74, 144, 217))
        event = clipboard.capture(self.database, self.data_dir, FakeReader(image=image))
        self.assertEqual(event["kind"], "image")
        item = self.database.list_items()[0]
        self.assertEqual(item["kind"], "image")
        self.assertEqual((item["width"], item["height"]), (480, 300))
        self.assertGreater(item["byte_size"], 0)
        self.assertTrue((self.data_dir / item["image_path"]).is_file())
        self.assertTrue((self.data_dir / item["thumb_path"]).is_file())

    def test_capture_rejects_oversized_image(self):
        image = Image.new("RGB", (storage.MAX_IMAGE_SIDE + 1, 10))
        self.assertIsNone(clipboard.capture(self.database, self.data_dir, FakeReader(image=image)))
        self.assertEqual(self.database.count(), 0)

    def test_capture_prefers_text_over_image(self):
        image = Image.new("RGB", (480, 300))
        event = clipboard.capture(
            self.database, self.data_dir, FakeReader(text="优先级更高", image=image)
        )
        self.assertEqual(event["kind"], "text")
        self.assertEqual(self.database.count(), 1)

    def test_capture_falls_back_to_image_when_text_too_long(self):
        too_long = "x" * (storage.MAX_TEXT_BYTES + 1)
        image = Image.new("RGB", (320, 200))
        event = clipboard.capture(
            self.database, self.data_dir, FakeReader(text=too_long, image=image)
        )
        self.assertEqual(event["kind"], "image")


class ListenerSuppressTests(unittest.TestCase):
    """程序自身写入剪贴板时，监听线程应跳过这一次变化（CB-08）。"""

    def setUp(self):
        self._tmp = tmpdir.new_dir()
        self.data_dir = storage.ensure_layout(self._tmp / "data")
        self.database = db.Database(storage.db_path(self.data_dir))
        self.listener = clipboard.ClipboardListener(self.database, self.data_dir)

    def tearDown(self):
        self.listener.stop()
        self.database.close()
        tmpdir.remove_dir(self._tmp)

    def test_suppress_consumed_once(self):
        self.listener.suppress_once()
        self.assertTrue(self.listener._consume_suppress())
        self.assertFalse(self.listener._consume_suppress())

    def test_suppress_without_request_returns_false(self):
        self.assertFalse(self.listener._consume_suppress())

    def test_suppress_expires_after_timeout(self):
        self.listener.suppress_once(seconds=0.0)
        self.assertFalse(self.listener._consume_suppress())

    def test_suppress_does_not_swallow_user_copy_after_expiry(self):
        # 写剪贴板失败时抑制标记会过期，用户的真实复制必须照常记录。
        self.listener.suppress_once(seconds=0.0)
        event = clipboard.capture(self.database, self.data_dir, FakeReader(text="用户手动复制"))
        self.assertIsNotNone(event)
        self.assertEqual(self.database.count(), 1)


class NotifyUiTests(unittest.TestCase):
    """内容未变时不通知界面（CB-12），避免「选中文本」导致整屏闪烁。"""

    def test_new_item_notifies(self):
        self.assertTrue(clipboard.should_notify_ui({"id": 1, "created": True}))

    def test_duplicate_item_does_not_notify(self):
        self.assertFalse(clipboard.should_notify_ui({"id": 1, "created": False}))

    def test_missing_event_does_not_notify(self):
        self.assertFalse(clipboard.should_notify_ui(None))


if __name__ == "__main__":
    unittest.main()
