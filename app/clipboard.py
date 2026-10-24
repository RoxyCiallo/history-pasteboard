"""剪贴板监听：把系统剪贴板的变化规范化后写入数据库。

职责边界（docs/02 §2）：
- 读取由 :mod:`win32` 负责，保存由 :mod:`storage` 负责，本模块只做判断与编排。
- 监听线程不直接操作界面，变化通过 ``queue`` 通知主线程。

线程模型（docs/02 §3）：500ms 轮询 ``GetClipboardSequenceNumber``，序号变化才读取内容。
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from pathlib import Path

from PIL import Image, ImageGrab

import db
import storage
import win32

#: 轮询间隔（秒）。500ms 的延迟在体验上不可感知，见 docs/08 ADR-006。
LISTENER_INTERVAL_SECONDS = 0.5

#: 复制「文件」时，只接受这些扩展名（按图片读取）。
IMAGE_EXTENSIONS = frozenset(
    {".bmp", ".dib", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
)

_LOGGER = logging.getLogger("pasteboard.clipboard")


def normalize_text(raw: str | None) -> str | None:
    """清洗剪贴板文本：统一换行、去首尾空白、丢弃空内容与超长内容。

    返回 ``None`` 表示这条内容不该入库。
    """
    if raw is None:
        return None
    text = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None
    if storage.text_too_large(text):
        return None
    return text


def is_acceptable_image(image) -> bool:
    """图片尺寸是否在可记录范围内（字节上限在保存时判断）。"""
    try:
        width, height = image.size
    except (AttributeError, TypeError):
        return False
    if width <= 0 or height <= 0:
        return False
    return width <= storage.MAX_IMAGE_SIDE and height <= storage.MAX_IMAGE_SIDE


def _first_image_file(paths) -> Image.Image | None:
    """从剪贴板的文件列表里取第一张图片文件。"""
    for name in paths:
        if not isinstance(name, str):
            continue
        if os.path.splitext(name)[1].lower() not in IMAGE_EXTENSIONS:
            continue
        try:
            with Image.open(name) as image:
                return image.convert("RGB")
        except OSError:
            _LOGGER.warning("读取图片文件失败：%s", name)
    return None


class ClipboardReader:
    """系统剪贴板读取器。测试时可用同接口的假对象替换。"""

    def read_text(self) -> str | None:
        return win32.read_clipboard_text()

    def read_image(self) -> Image.Image | None:
        """读取剪贴板图片；支持 DIB 图像与复制的图片文件。"""
        try:
            content = ImageGrab.grabclipboard()
        except Exception:  # noqa: BLE001 - 剪贴板被占用属正常情况，交给下一轮轮询
            _LOGGER.debug("grabclipboard 失败", exc_info=True)
            return None
        if isinstance(content, Image.Image):
            return content
        if isinstance(content, list):
            return _first_image_file(content)
        return None

    def has_private_marker(self) -> bool:
        try:
            return win32.private_marker_present()
        except win32.ClipboardError:
            return False


def capture(
    database: db.Database,
    data_dir: Path,
    reader: ClipboardReader | None = None,
) -> dict | None:
    """读取一次剪贴板并入库，返回 ``{"kind", "id", "created", "private"}``。

    - 有文本时优先记文本（复制表格等场景同时带图与文本，文本更有用）。
    - 没有可用文本时尝试图片。
    - 都不可用时返回 ``None``。
    """
    reader = reader or ClipboardReader()
    private = reader.has_private_marker()

    text = normalize_text(reader.read_text())
    if text is not None:
        item_id, created = database.upsert_item(
            kind="text",
            content_hash=storage.sha256_text(text),
            text_content=text,
            is_private=private,
        )
        _LOGGER.info("剪贴板文字已%s，id=%s，%d 字符", "记录" if created else "刷新", item_id, len(text))
        return {"kind": "text", "id": item_id, "created": created, "private": private}

    image = reader.read_image()
    if image is None or not is_acceptable_image(image):
        return None
    payload = storage.save_image(image, data_dir)
    if payload is None:
        _LOGGER.info("剪贴板图片超出上限，跳过")
        return None
    item_id, created = database.upsert_item(
        kind="image",
        content_hash=payload["content_hash"],
        image_path=payload["image_path"],
        thumb_path=payload["thumb_path"],
        width=payload["width"],
        height=payload["height"],
        byte_size=payload["byte_size"],
        is_private=private,
    )
    _LOGGER.info(
        "剪贴板图片已%s，id=%s，%dx%d",
        "记录" if created else "刷新",
        item_id,
        payload["width"],
        payload["height"],
    )
    return {"kind": "image", "id": item_id, "created": created, "private": private}


def should_notify_ui(event: dict | None) -> bool:
    """这条记录是否需要让界面重绘。

    只有内容确实新增（``created``）才通知；重复内容只刷新时间戳，
    避免某些程序「选中文本」时写剪贴板导致列表整屏闪烁。
    """
    return bool(event and event.get("created"))


class ClipboardListener(threading.Thread):
    """后台监听线程：序号变化 → 记录 → 向队列投递事件。"""

    def __init__(
        self,
        database: db.Database,
        data_dir: Path,
        event_queue: "queue.Queue | None" = None,
        interval: float = LISTENER_INTERVAL_SECONDS,
        reader: ClipboardReader | None = None,
    ) -> None:
        super().__init__(name="clipboard-listener", daemon=True)
        # 注意：不要叫 ``_stop``，那是 threading.Thread 的内部方法名。
        self._stop_event = threading.Event()
        self._database = database
        self._data_dir = data_dir
        self._queue = event_queue
        self._interval = interval
        self._reader = reader
        # 程序自己写剪贴板（卡片点击复制）时，跳过下一次序号变化，避免回灌历史。
        self._suppress_lock = threading.Lock()
        self._suppress_until = 0.0

    def suppress_once(self, seconds: float = 1.0) -> None:
        """让监听线程忽略下一次剪贴板变化（程序主动写入时调用）。

        调用方应在写剪贴板**之前**调用；若写入失败、序号没有变化，
        抑制标记会在 ``seconds`` 秒后自动失效，不会误吞用户的下一次复制。
        """
        deadline = time.monotonic() + max(0.0, seconds)
        with self._suppress_lock:
            self._suppress_until = deadline

    def _consume_suppress(self) -> bool:
        """消费抑制标记：命中一次就清零，过期视为未命中。"""
        with self._suppress_lock:
            if self._suppress_until <= 0.0:
                return False
            hit = time.monotonic() < self._suppress_until
            self._suppress_until = 0.0
            return hit

    def stop(self, timeout: float = 2.0) -> None:
        """请求停止并等待线程收尾，最多等 ``timeout`` 秒。"""
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout)

    def run(self) -> None:  # pragma: no cover - 依赖真实剪贴板
        try:
            last = win32.clipboard_sequence_number()
            _LOGGER.info("剪贴板监听已启动，间隔 %.1fs", self._interval)
            while not self._stop_event.is_set():
                if self._stop_event.wait(self._interval):
                    break
                try:
                    sequence = win32.clipboard_sequence_number()
                except Exception:  # noqa: BLE001 - 系统调用异常不应终止监听
                    _LOGGER.exception("读取剪贴板序号失败")
                    continue
                if sequence == last:
                    continue
                last = sequence
                if self._consume_suppress():
                    _LOGGER.debug("跳过程序自身写入的剪贴板变化")
                    continue
                try:
                    event = capture(self._database, self._data_dir, self._reader)
                except win32.ClipboardError:
                    _LOGGER.debug("剪贴板被占用，本轮跳过", exc_info=True)
                    continue
                except Exception:  # noqa: BLE001 - 单次失败不终止监听
                    _LOGGER.exception("记录剪贴板内容失败")
                    continue
                if event is not None and self._queue is not None:
                    if should_notify_ui(event):
                        self._queue.put(("new", event))
                    else:
                        _LOGGER.debug(
                            "剪贴板内容未变化，仅更新时间戳，id=%s", event.get("id")
                        )
        finally:
            _LOGGER.info("剪贴板监听已停止")
