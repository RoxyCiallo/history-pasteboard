"""程序入口：日志、数据层、剪贴板监听、全局热键、主窗口装配。

启动顺序（`docs/02` 线程模型）：
1. 开高 DPI 感知（必须在创建 Tk 之前）；
2. 解析数据目录 → 初始化日志；
3. 打开数据库、读取配置；
4. 启动剪贴板监听线程与热键线程；
5. 进入 tkinter 主循环；
6. 退出时按相反顺序收尾。
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

import clipboard
import config
import db
import storage
import win32
from ui.main_window import MainWindow

LOGGER = logging.getLogger("pasteboard")
LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
LOG_MAX_BYTES = 1_048_576
LOG_BACKUP_COUNT = 3


def setup_logging(log_file: Path) -> None:
    """文件 + 控制台双路日志；文件轮转 1 MB × 3，避免长期运行撑大磁盘。"""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(LOG_FORMAT)
    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        file_handler = None
    if file_handler is not None:
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)


def install_excepthooks() -> None:
    """把未捕获异常写进日志，避免 pythonw 下静默消失。"""

    def handle_main_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        LOGGER.error("未捕获异常", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_main_exception

    def handle_thread_exception(args):
        name = args.thread.name if args.thread is not None else "未知线程"
        LOGGER.error(
            "线程 %s 未捕获异常",
            name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = handle_thread_exception


def _report_startup_error(message: str) -> None:
    """pythonw 下没有 stderr，写不了就算了。"""
    if sys.stderr is not None:
        print(f"启动失败：{message}", file=sys.stderr)


def main() -> int:
    win32.set_dpi_awareness()

    try:
        data_dir = storage.ensure_layout(storage.resolve_data_dir())
    except OSError as error:
        _report_startup_error(str(error))
        return 1

    setup_logging(storage.log_path(data_dir))
    install_excepthooks()
    LOGGER.info("程序启动：数据目录 %s", data_dir)

    events: "queue.Queue" = queue.Queue()
    database = None
    listener = None
    hotkey = None
    try:
        database = db.Database(storage.db_path(data_dir))
        cfg = config.Config(database)

        listener = clipboard.ClipboardListener(database, data_dir, events)
        listener.start()

        hotkey = win32.HotkeyThread(events)
        hotkey.start()

        window = MainWindow(database, cfg, data_dir, events)
        window.mainloop()
        return 0
    except Exception:  # noqa: BLE001 - 启动失败要留下日志而不是闪退
        LOGGER.exception("程序异常退出")
        return 1
    finally:
        if listener is not None:
            listener.stop()
        if hotkey is not None:
            hotkey.stop()
        if database is not None:
            database.close()
        LOGGER.info("程序已退出")


if __name__ == "__main__":
    sys.exit(main())
