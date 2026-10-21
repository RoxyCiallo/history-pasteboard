"""数据目录解析与图片文件存取。

职责（见 docs/02 §6）：

- 决定运行时数据放哪儿：优先程序同目录 ``data/``（绿色便携），
  不可写时回退到 ``%LOCALAPPDATA%\\PasteBoard\\data``；
- 图片原图与缩略图落盘，用内容 sha256 命名，天然去重；
- 提供内容哈希、大小上限判断、文件删除等小工具。

本模块不导入 tkinter，也不做任何 Win32 调用。
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
from pathlib import Path
from typing import Any

from PIL import Image

# 单条文本上限：1 MB（UTF-8 字节数）
MAX_TEXT_BYTES = 1_048_576
# 单张图片上限：20 MB（PNG 编码后）
MAX_IMAGE_BYTES = 20 * 1024 * 1024
# 图片单边像素上限
MAX_IMAGE_SIDE = 8000
# 缩略图最大宽度
THUMB_MAX_WIDTH = 320

# 测试或调试时可用它指定数据目录，优先级最高
DATA_DIR_ENV = "PASTEBOARD_DATA_DIR"

IMAGES_DIR_NAME = "images"
THUMBS_DIR_NAME = "thumbs"
DB_FILE_NAME = "history.db"
LOG_FILE_NAME = "app.log"


# ---- 路径解析 -----------------------------------------------------


def app_dir() -> Path:
    """程序所在目录：打包后是 exe 目录，源码运行时是项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def localappdata_dir() -> Path:
    """回退根目录：``%LOCALAPPDATA%``，取不到时用用户主目录下的同名目录。"""
    raw = os.environ.get("LOCALAPPDATA")
    if raw:
        return Path(raw)
    return Path.home() / "AppData" / "Local"


def resolve_data_dir(
    base: Path | None = None,
    fallback_root: Path | None = None,
) -> Path:
    """确定数据目录。

    顺序：环境变量 ``PASTEBOARD_DATA_DIR`` > ``<程序目录>/data`` > ``%LOCALAPPDATA%/PasteBoard/data``。

    前两级都需要实际可写，否则自动降级到下一级。
    """
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override).expanduser()

    primary = (base or app_dir()) / "data"
    if _is_writable_dir(primary):
        return primary

    fallback = (fallback_root or localappdata_dir()) / "PasteBoard" / "data"
    if _is_writable_dir(fallback):
        return fallback

    raise OSError(f"找不到可写的数据目录：{primary} 与 {fallback}")


def ensure_layout(data_dir: Path) -> Path:
    """创建数据目录及子目录，返回数据目录本身。"""
    data_dir = Path(data_dir)
    (data_dir / IMAGES_DIR_NAME).mkdir(parents=True, exist_ok=True)
    (data_dir / THUMBS_DIR_NAME).mkdir(parents=True, exist_ok=True)
    return data_dir


def db_path(data_dir: Path) -> Path:
    """数据库文件完整路径。"""
    return Path(data_dir) / DB_FILE_NAME


def log_path(data_dir: Path) -> Path:
    """日志文件完整路径。"""
    return Path(data_dir) / LOG_FILE_NAME


def image_abs_path(data_dir: Path, relative: str | None) -> Path | None:
    """把库里的相对路径还原成绝对路径；越界路径返回 None。"""
    if not relative:
        return None
    root = Path(data_dir).resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target


def _is_writable_dir(path: Path) -> bool:
    """尝试创建目录并写一个探针文件，判断是否真的可写。"""
    probe = None
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_bytes(b"probe")
        return True
    except OSError:
        return False
    finally:
        if probe is not None:
            try:
                probe.unlink()
            except OSError:
                pass


# ---- 内容哈希与上限 -----------------------------------------------


def sha256_bytes(data: bytes) -> str:
    """字节内容的 sha256 十六进制串。"""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """文本内容的 sha256（UTF-8 编码）。"""
    return sha256_bytes(text.encode("utf-8"))


def text_too_large(text: str) -> bool:
    """文本是否超过单条上限。"""
    return len(text.encode("utf-8")) > MAX_TEXT_BYTES


def image_too_large(image: Image.Image) -> bool:
    """图片尺寸是否超过上限（字节数在编码后另行判断）。"""
    width, height = image.size
    return width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE


# ---- 图片落盘 -----------------------------------------------------


def save_image(image: Image.Image, data_dir: Path) -> dict[str, Any] | None:
    """保存图片原图与缩略图，返回可直接写库的字段。

    超过尺寸或字节上限时返回 ``None``，由调用方跳过该内容。
    """
    if image_too_large(image):
        return None

    payload = _encode_png(image)
    if len(payload) > MAX_IMAGE_BYTES:
        return None

    digest = sha256_bytes(payload)
    images_root = Path(data_dir) / IMAGES_DIR_NAME
    thumbs_root = Path(data_dir) / THUMBS_DIR_NAME
    images_root.mkdir(parents=True, exist_ok=True)
    thumbs_root.mkdir(parents=True, exist_ok=True)

    image_file = images_root / f"{digest}.png"
    thumb_file = thumbs_root / f"{digest}.png"
    if not image_file.exists():
        _write_bytes_atomic(image_file, payload)
    if not thumb_file.exists():
        _write_bytes_atomic(thumb_file, _encode_png(make_thumbnail(image)))

    width, height = image.size
    return {
        "kind": "image",
        "content_hash": digest,
        "image_path": f"{IMAGES_DIR_NAME}/{digest}.png",
        "thumb_path": f"{THUMBS_DIR_NAME}/{digest}.png",
        "width": width,
        "height": height,
        "byte_size": len(payload),
    }


def make_thumbnail(image: Image.Image, max_width: int = THUMB_MAX_WIDTH) -> Image.Image:
    """生成等比缩略图（不修改传入对象）。"""
    thumb = image.copy()
    thumb.thumbnail((max_width, max_width), Image.Resampling.LANCZOS)
    return thumb


def delete_files(data_dir: Path, relative_paths: list[str | None]) -> int:
    """删除给定的相对路径文件，返回成功删除的数量；缺失文件忽略。"""
    removed = 0
    for relative in relative_paths:
        target = image_abs_path(data_dir, relative)
        if target is None:
            continue
        try:
            target.unlink()
            removed += 1
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return removed


def _encode_png(image: Image.Image) -> bytes:
    """编码为 PNG 字节。"""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _write_bytes_atomic(target: Path, payload: bytes) -> None:
    """先写临时文件再替换，避免留下半截文件。"""
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_bytes(payload)
    os.replace(temp, target)
