"""测试用临时目录工具。

为什么不用 ``tempfile.TemporaryDirectory``：
它创建目录后会 chmod 0o700；在本项目的 Windows 沙箱环境里，这样得到的
目录会变成「拒绝访问」，SQLite 无法在其中建库（``unable to open database
file``），清理时也会报 WinError 5。改为在 ``build/test-tmp`` 下用普通
``mkdir`` 建子目录（继承父目录的正常 ACL），并在收尾时整体删除。
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

_TMP_ROOT = Path(__file__).resolve().parents[1] / "build" / "test-tmp"


def new_dir() -> Path:
    """新建一个随机临时目录并返回路径。"""
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = _TMP_ROOT / f"case-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    return path


def remove_dir(path: Path) -> None:
    """删除临时目录；失败不抛异常，避免掩盖真正的测试失败。"""
    shutil.rmtree(path, ignore_errors=True)
