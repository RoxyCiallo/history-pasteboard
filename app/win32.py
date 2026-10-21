"""Win32 API 封装：剪贴板读写、序列号、敏感标记检测、全局热键、高 DPI、单实例。

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

#: 热键候选表：(修饰键, 虚拟键, 展示名)。主键被占用时依次回退（docs/02 §7）。
HOTKEY_CANDIDATES = (
    (MOD_CONTROL | MOD_SHIFT, 0x56, "Ctrl+Shift+V"),
    (MOD_CONTROL | MOD_ALT, 0x56, "Ctrl+Alt+V"),
    (MOD_CONTROL | MOD_SHIFT, 0x48, "Ctrl+Shift+H"),
)

#: 单实例与「唤起已有实例」用到的常量（ADR-010）。
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
WAIT_OBJECT_0 = 0x00000000
MUTEX_NAME = "Local\\PasteBoard.SingleInstance"
ACTIVATE_EVENT_NAME = "Local\\PasteBoard.Activate"

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

    # 单实例与唤起（ADR-010）
    _kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.CreateMutexW.restype = wintypes.HANDLE
    _kernel32.CreateEventW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    _kernel32.CreateEventW.restype = wintypes.HANDLE
    _kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.OpenEventW.restype = wintypes.HANDLE
    _kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    _kernel32.SetEvent.restype = wintypes.BOOL
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL


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


# ---- 单实例与唤起 ------------------------------------------------

class SingleInstance:
    """用命名互斥体做单实例判定，用命名事件通知已有实例「把窗口唤出来」。

    用法（`app/main.py`）::

        instance = SingleInstance()
        if not instance.acquire():
            return 0          # 已有实例在跑，且已通知它唤出窗口
        ...
        instance.close()

    名字带 ``Local\\`` 前缀，只在当前登录会话内生效，不会和其他 Windows 用户互相干扰。
    """

    def __init__(
        self,
        mutex_name: str = MUTEX_NAME,
        event_name: str = ACTIVATE_EVENT_NAME,
    ) -> None:
        self._mutex_name = mutex_name
        self._event_name = event_name
        self._mutex = None
        self._event = None

    def acquire(self) -> bool:
        """尝试成为唯一实例。

        - 首个实例：返回 ``True``，并创建唤起事件；
        - 已有实例：返回 ``False``，同时 ``SetEvent`` 让已有实例把窗口唤到前台。
        """
        if not available():  # pragma: no cover - 非 Windows 不阻塞启动
            return True
        mutex = _kernel32.CreateMutexW(None, False, self._mutex_name)
        last_error = ctypes.get_last_error()
        if last_error == ERROR_ALREADY_EXISTS:
            if mutex:
                _kernel32.CloseHandle(mutex)
            self._notify_existing()
            return False
        self._mutex = mutex
        self._event = _kernel32.CreateEventW(None, False, False, self._event_name)
        if not self._event:  # pragma: no cover - 极端环境
            _LOGGER.warning("创建唤起事件失败（Win32 错误码 %s）", ctypes.get_last_error())
        return True

    def wait(self, timeout_ms: int = 250) -> bool:
        """等待唤起事件，收到返回 ``True``；超时返回 ``False``。"""
        if not self._event:
            return False
        return _kernel32.WaitForSingleObject(self._event, timeout_ms) == WAIT_OBJECT_0

    def close(self) -> None:
        """释放事件与互斥体句柄；进程退出时系统也会自动回收。"""
        for handle in (self._event, self._mutex):
            if handle:
                _kernel32.CloseHandle(handle)
        self._event = None
        self._mutex = None

    def _notify_existing(self) -> None:
        event = _kernel32.OpenEventW(EVENT_MODIFY_STATE, False, self._event_name)
        if not event:
            # 对方刚退出、事件已销毁时会出现，忽略即可。
            _LOGGER.warning("找不到已有实例的唤起事件，无法唤出窗口")
            return
        try:
            _kernel32.SetEvent(event)
        finally:
            _kernel32.CloseHandle(event)


class ActivateWatcher(threading.Thread):
    """后台等待唤起事件；收到后往队列投递 ``("activate", None)``。

    主线程收到事件后调用 ``MainWindow.show()``。用轮询超时的方式等待，
    以便 ``stop()`` 能在一轮内生效，不依赖销毁事件对象。
    """

    def __init__(self, instance: SingleInstance, event_queue=None, poll_ms: int = 250) -> None:
        super().__init__(name="activate-watcher", daemon=True)
        self._instance = instance
        self._queue = event_queue
        self._poll_ms = poll_ms
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            if self._instance.wait(self._poll_ms) and self._queue is not None:
                self._queue.put(("activate", None))

    def stop(self, timeout: float = 1.0) -> None:
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout)


# ---- 全局热键 ------------------------------------------------------


class HotkeyThread(threading.Thread):
    """在独立线程注册全局热键并等待，按下时把 ``("hotkey", None)`` 放进队列。

    Win32 的 ``RegisterHotKey(None, ...)`` 要求调用线程自己跑消息循环，
    因此热键必须有自己的线程，不能挂在 Tk 主线程上。
    按 ``candidates`` 依次尝试注册，全部被占用时把 ``("hotkey_failed", 错误码)``
    放进队列并结束线程；注册成功则投递 ``("hotkey_registered", 展示名)``。
    """

    def __init__(
        self,
        event_queue=None,
        candidates: tuple[tuple[int, int, str], ...] = HOTKEY_CANDIDATES,
        hotkey_id: int = HOTKEY_ID,
    ) -> None:
        super().__init__(name="hotkey", daemon=True)
        self._queue = event_queue
        self._candidates = candidates
        self._hotkey_id = hotkey_id
        self._thread_id = 0

    def run(self) -> None:
        if not available():  # pragma: no cover - 非 Windows
            self._emit("hotkey_failed", "当前系统不支持全局热键")
            return
        self._thread_id = int(_kernel32.GetCurrentThreadId())
        label = self._register()
        if label is None:
            self._emit("hotkey_failed", ctypes.get_last_error())
            return
        _LOGGER.info("全局热键已注册：%s", label)
        self._emit("hotkey_registered", label)
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

    def _register(self) -> str | None:
        """依次尝试候选热键，返回成功的展示名；全失败返回 ``None``。"""
        for modifiers, key, label in self._candidates:
            if _user32.RegisterHotKey(None, self._hotkey_id, modifiers, key):
                return label
            _LOGGER.warning(
                "全局热键 %s 注册失败（Win32 错误码 %s），可能被其他程序占用",
                label,
                ctypes.get_last_error(),
            )
        return None

    def stop(self, timeout: float = 1.0) -> None:
        """向热键线程投递 WM_QUIT，等它退出消息循环。"""
        if self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self.is_alive():
            self.join(timeout)

    def _emit(self, kind: str, payload) -> None:
        if self._queue is not None:
            self._queue.put((kind, payload))
