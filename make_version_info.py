"""生成 PyInstaller 用到的版本资源文件（开发期脚本，不入库）。

从 ``app/config.py`` 的 ``APP_VERSION`` 读取版本号，写出
``build/version_info.txt``，让 exe 属性里显示产品名与版本。

用法::

    python make_version_info.py           # 生成 build/version_info.txt
    python make_version_info.py --check   # 只检查版本号格式，不写文件
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "app" / "config.py"
OUT_FILE = ROOT / "build" / "version_info.txt"

VERSION_PATTERN = re.compile(r'^APP_VERSION\s*=\s*"([0-9]+)\.([0-9]+)\.([0-9]+)"\s*$', re.MULTILINE)

FILE_DESCRIPTION = "历史粘贴板"
PRODUCT_NAME = "历史粘贴板"
COMPANY_NAME = ""
COPYRIGHT = ""


def read_version() -> tuple[int, int, int]:
    """从 config.py 解析 ``APP_VERSION``，返回三元组。"""
    text = CONFIG_FILE.read_text(encoding="utf-8")
    match = VERSION_PATTERN.search(text)
    if match is None:
        raise SystemExit(f"没有在 {CONFIG_FILE} 找到形如 APP_VERSION = \"1.2.3\" 的版本号")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def render(version: tuple[int, int, int]) -> str:
    major, minor, patch = version
    version_text = f"{major}.{minor}.{patch}"
    quad = f"({major}, {minor}, {patch}, 0)"
    return f"""# UTF-8
# 由 make_version_info.py 自动生成，请勿手工修改。
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={quad},
    prodvers={quad},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '080404b0',
          [
            StringStruct('CompanyName', '{COMPANY_NAME}'),
            StringStruct('FileDescription', '{FILE_DESCRIPTION}'),
            StringStruct('FileVersion', '{version_text}'),
            StringStruct('InternalName', 'PasteBoard'),
            StringStruct('LegalCopyright', '{COPYRIGHT}'),
            StringStruct('OriginalFilename', 'PasteBoard.exe'),
            StringStruct('ProductName', '{PRODUCT_NAME}'),
            StringStruct('ProductVersion', '{version_text}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""


def main(argv: list[str]) -> int:
    version = read_version()
    if "--check" in argv:
        print(f"版本号 OK：{'.'.join(map(str, version))}")
        return 0
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(render(version), encoding="utf-8")
    print(f"已生成 {OUT_FILE}（版本 {'.'.join(map(str, version))}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
