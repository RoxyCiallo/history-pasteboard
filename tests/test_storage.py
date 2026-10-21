"""storage.py 的单元测试：路径解析、哈希、图片落盘、删除。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image  # noqa: E402

import storage  # noqa: E402
import tmpdir  # noqa: E402


class StorageTestCase(unittest.TestCase):
    """每个用例一个独立的临时数据目录。"""

    def setUp(self) -> None:
        self._tmp = tmpdir.new_dir()
        self.data_dir = storage.ensure_layout(self._tmp / "data")

    def tearDown(self) -> None:
        tmpdir.remove_dir(self._tmp)

    # ---- 哈希与上限 -------------------------------------------------

    def test_sha256_text_matches_bytes(self) -> None:
        text = "剪贴板历史"
        self.assertEqual(storage.sha256_text(text), storage.sha256_bytes(text.encode("utf-8")))
        self.assertEqual(len(storage.sha256_text(text)), 64)

    def test_text_bytes_limit(self) -> None:
        just_fits = "a" * storage.MAX_TEXT_BYTES
        too_big = just_fits + "a"
        self.assertFalse(storage.text_too_large(just_fits))
        self.assertTrue(storage.text_too_large(too_big))
        # 中文按 UTF-8 字节计算，不是字符数
        self.assertTrue(storage.text_too_large("中" * (storage.MAX_TEXT_BYTES // 3 + 1)))

    def test_image_side_limit(self) -> None:
        small = Image.new("RGB", (100, 100), "white")
        wide = Image.new("RGB", (storage.MAX_IMAGE_SIDE + 1, 1), "white")
        self.assertFalse(storage.image_too_large(small))
        self.assertTrue(storage.image_too_large(wide))

    # ---- 图片落盘 ---------------------------------------------------

    def test_save_image_creates_original_and_thumb(self) -> None:
        image = Image.new("RGB", (800, 600), (210, 230, 250))
        payload = storage.save_image(image, self.data_dir)
        assert payload is not None

        self.assertEqual(payload["kind"], "image")
        self.assertEqual((payload["width"], payload["height"]), (800, 600))
        self.assertGreater(payload["byte_size"], 0)

        original = self.data_dir / payload["image_path"]
        thumb = self.data_dir / payload["thumb_path"]
        self.assertTrue(original.is_file())
        self.assertTrue(thumb.is_file())
        with Image.open(thumb) as opened:
            self.assertLessEqual(max(opened.size), storage.THUMB_MAX_WIDTH)
        self.assertEqual(payload["content_hash"], storage.sha256_bytes(original.read_bytes()))

    def test_save_image_is_idempotent(self) -> None:
        image = Image.new("RGB", (120, 90), (255, 0, 0))
        first = storage.save_image(image, self.data_dir)
        second = storage.save_image(image, self.data_dir)
        assert first is not None and second is not None
        self.assertEqual(first["content_hash"], second["content_hash"])
        self.assertEqual(len(list((self.data_dir / storage.IMAGES_DIR_NAME).iterdir())), 1)

    def test_save_image_skips_oversized(self) -> None:
        huge = Image.new("RGB", (storage.MAX_IMAGE_SIDE + 5, 10), "white")
        self.assertIsNone(storage.save_image(huge, self.data_dir))
        self.assertEqual(len(list((self.data_dir / storage.IMAGES_DIR_NAME).iterdir())), 0)

    def test_make_thumbnail_keeps_source_untouched(self) -> None:
        image = Image.new("RGB", (1000, 500), "blue")
        thumb = storage.make_thumbnail(image)
        self.assertEqual(image.size, (1000, 500))
        self.assertEqual(thumb.size[0], storage.THUMB_MAX_WIDTH)

    # ---- 文件删除 ---------------------------------------------------

    def test_delete_files_ignores_missing(self) -> None:
        payload = storage.save_image(Image.new("RGB", (60, 40), "green"), self.data_dir)
        assert payload is not None
        removed = storage.delete_files(
            self.data_dir,
            [payload["image_path"], payload["thumb_path"], "images/不存在.png", None],
        )
        self.assertEqual(removed, 2)
        self.assertFalse((self.data_dir / payload["image_path"]).exists())

    def test_image_abs_path_blocks_escape(self) -> None:
        self.assertIsNone(storage.image_abs_path(self.data_dir, "../../evil.png"))
        self.assertIsNone(storage.image_abs_path(self.data_dir, ""))
        inside = storage.image_abs_path(self.data_dir, "images/a.png")
        assert inside is not None
        self.assertTrue(str(inside).endswith("a.png"))

    # ---- 目录解析 ---------------------------------------------------

    def test_resolve_data_dir_uses_env_override(self) -> None:
        target = self._tmp / "custom"
        with mock.patch.dict(os.environ, {storage.DATA_DIR_ENV: str(target)}):
            self.assertEqual(storage.resolve_data_dir(), target)

    def test_resolve_data_dir_prefers_program_dir(self) -> None:
        base = self._tmp / "app"
        fallback = self._tmp / "fallback"
        with mock.patch.dict(os.environ, {storage.DATA_DIR_ENV: ""}):
            resolved = storage.resolve_data_dir(base=base, fallback_root=fallback)
        self.assertEqual(resolved, base / "data")

    def test_resolve_data_dir_falls_back_when_unwritable(self) -> None:
        base = self._tmp / "app"
        fallback = self._tmp / "fallback"
        with mock.patch.dict(os.environ, {storage.DATA_DIR_ENV: ""}), mock.patch.object(
            storage, "_is_writable_dir", side_effect=[False, True]
        ):
            resolved = storage.resolve_data_dir(base=base, fallback_root=fallback)
        self.assertEqual(resolved, fallback / "PasteBoard" / "data")

    def test_ensure_layout_creates_subdirs(self) -> None:
        self.assertTrue((self.data_dir / storage.IMAGES_DIR_NAME).is_dir())
        self.assertTrue((self.data_dir / storage.THUMBS_DIR_NAME).is_dir())

    def test_db_and_log_paths(self) -> None:
        self.assertEqual(storage.db_path(self.data_dir).name, "history.db")
        self.assertEqual(storage.log_path(self.data_dir).name, "app.log")


if __name__ == "__main__":
    unittest.main()
