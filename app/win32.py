"""Win32 API 封装：剪贴板读写、序列号、敏感标记检测、全局热键、高 DPI。

按 `docs/02` §7 的约定，**所有 ctypes 调用集中在本模块**，其他模块不得直接 import ctypes。
本模块只做系统调用，不含业务判断；剪贴板失败一律抛 :class:`ClipboardError` 或返回 ``None``。
"""

from __future__ import annotations

import ctypes
import io
import logging
import threading
import time
from ctypes import wintypes
from contextlib import contextmanager

CF_UNICODETEXT = 13
CF_DIB = 8
CF_HDROP = 15

GMEM_MOVEABLE = 0x0002

#: 全局热键的修饰键与消息常量（docs/02 热键设计）。
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

#: 默认热键：Ctrl+Shift+V（V 的虚拟键码 0x56）。
HOTKEY_ID = 1
HOTKEY_MODIFIERS = MOD_CONTROL | MOD_SHIFT
HOTKEY_VK = 0x56

_LOGGER = logging.getLogger("pasteboard.win32")

#: 复制方声明「不要进剪贴板历史」的格式，出现即视为敏感内容（docs/01 FR-11）。
PRIVATE_FORMATS = (
    "ExcludeClipboardContentFromMonitorProcessing",
    "Clipboard Viewer Ignore",
    "Can Include In Clipboard History",
)

_OPEN_RETRIES = 3
_OPEN_RETRY_DELAY = 0.02


class ClipboardError(RuntimeError):
    """剪贴板被其他程序占用，或读写失败。"""


try:  # pragma: no cover - 依赖 Windows
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
except OSError:  # pragma: no cover - 非 Windows 环境下只保证可导入
    _user32 = None
    _kernel32 = None


if _user32 is not None:  # pragma: no cover - 依赖 Windows
    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.CloseClipboard.argtypes = []
    _user32.CloseClipboard.restype = wintypes.BOOL
    _user32.EmptyClipboard.argtypes = []
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    _user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    _user32.GetClipboardData.argtypes = [wintypes.UINT]
    _user32.GetClipboardData.restype = wintypes.HANDLE
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _user32.GetClipboardSequenceNumber.argtypes = []
    _user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    _user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    _user32.RegisterClipboardFormatW.restype = wintypes.UINT

    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HANDLE
    _kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
    _kernel32.GlobalFree.restype = wintypes.HANDLE
    _kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    _kernel32.GlobalLock.restype = wintypes.LPVOID
    _kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL

    # 高 DPI（docs/03 §7）
    _user32.SetProcessDPIAware.argtypes = []
    _user32.SetProcessDPIAware.restype = wintypes.BOOL

    # 全局热键（M3 提前实现；线程消息循环在 HotkeyThread 里）
    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.UnregisterHotKey.restype = wintypes.BOOL
    _user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    ]
    _user32.GetMessageW.restype = ctypes.c_int
    _user32.PostThreadMessageW.argtypes = [
        wintypes.DWORD,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    _user32.PostThreadMessageW.restype = wintypes.BOOL
    _kernel32.GetCurrentThreadId.argtypes = []
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def available() -> bool:
    """当前环境是否可用 Win32 剪贴板接口。"""
    return _user32 is not None and _kernel32 is not None


def _require_available() -> None:
    if not available():  # pragma: no cover - 非 Windows
        raise ClipboardError("当前系统不支持 Win32 剪贴板接口")


@contextmanager
def open_clipboard(retries: int = _OPEN_RETRIES, delay: float = _OPEN_RETRY_DELAY):
    """打开剪贴板（带重试），离开作用域时必定关闭。

    剪贴板同一时刻只能被一个进程打开，Office/远程桌面等会短暂占用，因此需要重试。
    """
    _require_available()
    last_error = 0
    for _ in range(max(1, retries)):
        if _user32.OpenClipboard(None):
            break
        last_error = ctypes.get_last_error()
        time.sleep(delay)
    else:
        raise ClipboardError(f"打开剪贴板失败（Win32 错误码 {last_error}）")
    try:
        yield
    finally:
        _user32.CloseClipboard()


def clipboard_sequence_number() -> int:
    """剪贴板内容序号：内容变化即递增，用于轮询判断是否要读取。"""
    if not available():  # pragma: no cover - 非 Windows
        return 0
    return int(_user32.GetClipboardSequenceNumber())


def has_format(fmt: int) -> bool:
    """剪贴板当前是否包含指定格式。"""
    _require_available()
    return bool(_user32.IsClipboardFormatAvailable(fmt))


def read_clipboard_text() -> str | None:
    """读取剪贴板文本；没有文本格式时返回 ``None``。"""
    _require_available()
    if not has_format(CF_UNICODETEXT):
        return None
    with open_clipboard():
        handle = _user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        pointer = _kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.wstring_at(pointer)
        finally:
            _kernel32.GlobalUnlock(handle)


def private_marker_present() -> bool:
    """复制方是否标记了「不要记录」，有则按敏感内容处理。"""
    _require_available()
    for name in PRIVATE_FORMATS:
        fmt = _user32.RegisterClipboardFormatW(name)
        if fmt and _user32.IsClipboardFormatAvailable(fmt):
            return True
    return False


def _set_clipboard_bytes(fmt: int, data: bytes) -> bool:
    """把一段字节写入剪贴板指定格式，失败返回 ``False``。"""
    with open_clipboard():
        if not _user32.EmptyClipboard():
            return False
        handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        pointer = _kernel32.GlobalLock(handle)
        if not pointer:
            _kernel32.GlobalFree(handle)
            return False
        try:
            ctypes.memmove(pointer, data, len(data))
        finally:
            _kernel32.GlobalUnlock(handle)
        if not _user32.SetClipboardData(fmt, handle):
            _kernel32.GlobalFree(handle)
            return False
    return True


def set_clipboard_text(text: str) -> bool:
    """把文本写入剪贴板（供卡片点击复制使用）。"""
    _require_available()
    payload = text.encode("utf-16-le") + b"\x00\x00"
    return _set_clipboard_bytes(CF_UNICODETEXT, payload)


def set_clipboard_image(image) -> bool:
    """把 PIL 图片写入剪贴板（CF_DIB，供图片卡片点击复制使用）。"""
    _require_available()
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "BMP")
    # BMP 文件头有 14 字节，CF_DIB 只需要后面的 DIB 部分（BITMAPINFOHEADER + 像素）。
    return _set_clipboard_bytes(CF_DIB, buffer.getvalue()[14:])


# ---- 高 DPI --------------------------------------------------------


def set_dpi_awareness() -> bool:
    """开启高 DPI 感知，避免界面发虚。**必须在创建 Tk 窗口之前调用**。

    优先用 Win8.1+ 的 ``SetProcessDpiAwareness(2)``（per-monitor），
    系统没有 shcore.dll 时退回 ``SetProcessDPIAware()``（system DPI aware）。
    """
    if not available():  # pragma: no cover - 非 Windows
        return False
    try:
        shcore = ctypes.WinDLL("shcore")
        shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
        shcore.SetProcessDpiAwareness.restype = ctypes.c_long
        if shcore.SetProcessDpiAwareness(2) == 0:
            return True
    except OSError:
        pass
    try:
        return bool(_user32.SetProcessDPIAware())
    except Exception:  # pragma: no cover - 极端环境
        return False


# ---- 全局热键 ------------------------------------------------------


class HotkeyThread(threading.Thread):
    """在独立线程注册全局热键并等待，按下时把 ``("hotkey", None)`` 放进队列。

    Win32 的 ``RegisterHotKey(None, ...)`` 要求调用线程自己跑消息循环，
    因此热键必须有自己的线程，不能挂在 Tk 主线程上。
    注册失败（被占用）时把 ``("hotkey_failed", 错误码)`` 放进队列并结束线程。
    """

    def __init__(
        self,
        event_queue=None,
        modifiers: int = HOTKEY_MODIFIERS,
        key: int = HOTKEY_VK,
        hotkey_id: int = HOTKEY_ID,
    ) -> None:
        super().__init__(name="hotkey", daemon=True)
        self._queue = event_queue
        self._modifiers = modifiers
        self._key = key
        self._hotkey_id = hotkey_id
        self._thread_id = 0

    def run(self) -> None:
        if not available():  # pragma: no cover - 非 Windows
            self._emit("hotkey_failed", "当前系统不支持全局热键")
            return
        self._thread_id = int(_kernel32.GetCurrentThreadId())
        if not _user32.RegisterHotKey(None, self._hotkey_id, self._modifiers, self._key):
            error = ctypes.get_last_error()
            _LOGGER.warning("全局热键注册失败（Win32 错误码 %s），可能被其他程序占用", error)
            self._emit("hotkey_failed", error)
            return
        _LOGGER.info("全局热键已注册")
        message = wintypes.MSG()
        try:
            while True:
                result = _user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == 0 or result == -1:
                    break
                if message.message == WM_HOTKEY and int(message.wParam) == self._hotkey_id:
                    self._emit("hotkey", None)
        finally:
            _user32.UnregisterHotKey(None, self._hotkey_id)
            _LOGGER.info("全局热键已注销")

    def stop(self, timeout: float = 1.0) -> None:
        """向热键线程投递 WM_QUIT，等它退出消息循环。"""
        if self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self.is_alive():
            self.join(timeout)

    def _emit(self, kind: str, payload) -> None:
        if self._queue is not None:
            self._queue.put((kind, payload))
