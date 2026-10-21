"""SQLite 数据访问层：schema、迁移、CRUD、搜索、清理。

设计要点（见 docs/02 §5）：

- 单连接 + ``threading.RLock``，供 UI 线程与监听线程并发调用；
- 时间统一存本地时间 ISO8601（``YYYY-MM-DDTHH:MM:SS``），可直接字符串比较；
- ``content_hash`` 唯一，去重靠它：重复内容只刷新 ``updated_at``；
- 置顶记录（``pinned=1``）不受保留期清理；
- 本模块不导入 tkinter，也不进行任何 Win32 调用。
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
import threading
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT    NOT NULL CHECK (kind IN ('text','image')),
    text_content TEXT,
    image_path   TEXT,
    thumb_path   TEXT,
    width        INTEGER,
    height       INTEGER,
    byte_size    INTEGER,
    content_hash TEXT    NOT NULL UNIQUE,
    is_private   INTEGER NOT NULL DEFAULT 0,
    pinned       INTEGER NOT NULL DEFAULT 0,
    pinned_at    TEXT,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_order ON items(pinned DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_hash  ON items(content_hash);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);
"""

ORDER_BY = "ORDER BY pinned DESC, updated_at DESC, id DESC"
LIKE_ESCAPE = "\\"


def now_text() -> str:
    """当前本地时间，格式与入库格式一致。"""
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


class Database:
    """一个 SQLite 数据库连接及其上的全部数据操作。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(path),
            check_same_thread=False,
            isolation_level=None,  # 手动控制事务
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    # ---- 生命周期 -------------------------------------------------

    def close(self) -> None:
        """关闭连接；重复调用安全。"""
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.ProgrammingError:
                pass

    def _init_schema(self) -> None:
        """建表并校验/升级 schema 版本。"""
        with self._lock:
            self._conn.executescript(DDL)
            row = self._conn.execute("SELECT COUNT(*) AS n FROM schema_meta").fetchone()
            if not row["n"]:
                self._conn.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
                return

            version = self._conn.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()["version"]
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"数据库版本 {version} 高于程序支持的 {SCHEMA_VERSION}，请升级程序"
                )
            if version < SCHEMA_VERSION:
                self._migrate(int(version))

    def _migrate(self, from_version: int) -> None:
        """按顺序执行迁移；每个迁移负责把版本推进一级。

        当前只有 v1，没有实际迁移步骤。新增 schema 变更时：
        1. 提升 ``SCHEMA_VERSION``；
        2. 在 ``_MIGRATIONS`` 里注册 ``from_version -> 函数``；
        3. 更新 docs/02 §5 的迁移策略。
        """
        migrations: dict[int, Any] = {}
        version = from_version
        while version < SCHEMA_VERSION:
            step = migrations.get(version)
            if step is None:
                raise RuntimeError(f"缺少从 v{version} 到 v{version + 1} 的数据库迁移")
            step(self._conn)
            version += 1
            self._conn.execute("UPDATE schema_meta SET version = ?", (version,))

    # ---- 写入 -----------------------------------------------------

    def upsert_item(
        self,
        *,
        kind: str,
        content_hash: str,
        text_content: str | None = None,
        image_path: str | None = None,
        thumb_path: str | None = None,
        width: int | None = None,
        height: int | None = None,
        byte_size: int | None = None,
        is_private: bool = False,
        now: str | None = None,
    ) -> tuple[int, bool]:
        """插入或刷新一条记录。

        返回 ``(id, created)``：``created`` 为 False 表示命中去重、只刷新了时间。
        """
        if kind not in ("text", "image"):
            raise ValueError(f"kind 只能是 text 或 image，收到：{kind!r}")
        stamp = now or now_text()
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT id FROM items WHERE content_hash = ?", (content_hash,)
            ).fetchone()
            if row is not None:
                item_id = int(row["id"])
                self._conn.execute(
                    "UPDATE items SET updated_at = ?, is_private = MAX(is_private, ?) WHERE id = ?",
                    (stamp, int(is_private), item_id),
                )
                return item_id, False

            cursor = self._conn.execute(
                """
                INSERT INTO items (kind, text_content, image_path, thumb_path, width, height,
                                   byte_size, content_hash, is_private, pinned, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    kind,
                    text_content,
                    image_path,
                    thumb_path,
                    width,
                    height,
                    byte_size,
                    content_hash,
                    int(is_private),
                    stamp,
                    stamp,
                ),
            )
            return int(cursor.lastrowid), True

    def touch_item(self, item_id: int, now: str | None = None) -> None:
        """把一条记录的时间刷新到现在（用于点击卡片再次复制）。"""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE items SET updated_at = ? WHERE id = ?", (now or now_text(), item_id)
            )

    def toggle_pin(self, item_id: int, now: str | None = None) -> bool | None:
        """置顶/取消置顶，返回新状态；记录不存在返回 None。"""
        stamp = now or now_text()
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT pinned FROM items WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                return None
            new_state = 0 if row["pinned"] else 1
            self._conn.execute(
                "UPDATE items SET pinned = ?, pinned_at = ? WHERE id = ?",
                (new_state, stamp if new_state else None, item_id),
            )
            return bool(new_state)

    def delete_item(self, item_id: int) -> dict[str, Any] | None:
        """删除一条记录并返回被删数据（含图片路径，供调用方删文件）。"""
        with self._lock, self._conn:
            row = self._conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                return None
            self._conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
            return _row_to_dict(row)

    def clear_all(self) -> list[dict[str, Any]]:
        """清空全部记录，返回被删数据列表（供调用方删图片文件）。"""
        with self._lock, self._conn:
            rows = self._conn.execute("SELECT * FROM items").fetchall()
            self._conn.execute("DELETE FROM items")
            return [_row_to_dict(row) for row in rows]

    def delete_private_items(self) -> list[dict[str, Any]]:
        """删除所有私密记录（重置密码时使用），返回被删数据列表。"""
        with self._lock, self._conn:
            rows = self._conn.execute("SELECT * FROM items WHERE is_private = 1").fetchall()
            if rows:
                self._conn.execute("DELETE FROM items WHERE is_private = 1")
            return [_row_to_dict(row) for row in rows]

    def purge_expired(self, retention_days: int, now: _dt.datetime | None = None) -> list[dict[str, Any]]:
        """删除超过保留期的非置顶记录，返回被删数据列表。"""
        if retention_days < 1:
            raise ValueError("保留天数至少为 1")
        moment = now or _dt.datetime.now()
        cutoff = (moment - _dt.timedelta(days=retention_days)).strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT * FROM items WHERE pinned = 0 AND updated_at < ?", (cutoff,)
            ).fetchall()
            if rows:
                self._conn.execute("DELETE FROM items WHERE pinned = 0 AND updated_at < ?", (cutoff,))
            return [_row_to_dict(row) for row in rows]

    # ---- 读取 -----------------------------------------------------

    def get_item(self, item_id: int) -> dict[str, Any] | None:
        """按 id 取一条记录。"""
        with self._lock:
            row = self._conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            return _row_to_dict(row) if row else None

    def list_items(
        self,
        limit: int = 200,
        offset: int = 0,
        keyword: str | None = None,
    ) -> list[dict[str, Any]]:
        """按「置顶优先、时间倒序」返回记录，支持分页与关键字过滤。"""
        sql = "SELECT * FROM items"
        params: list[Any] = []
        where = _keyword_clause(keyword, params)
        if where:
            sql += f" WHERE {where}"
        sql += f" {ORDER_BY} LIMIT ? OFFSET ?"
        params.extend([max(1, int(limit)), max(0, int(offset))])
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            return [_row_to_dict(row) for row in rows]

    def search(self, keyword: str, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        """按关键字搜索（语义同 ``list_items(keyword=...)``）。"""
        return self.list_items(limit=limit, offset=offset, keyword=keyword)

    def count(self, keyword: str | None = None) -> int:
        """统计记录数；给 keyword 时统计匹配数。"""
        sql = "SELECT COUNT(*) AS n FROM items"
        params: list[Any] = []
        where = _keyword_clause(keyword, params)
        if where:
            sql += f" WHERE {where}"
        with self._lock:
            return int(self._conn.execute(sql, params).fetchone()["n"])

    # ---- 设置（供 config.py 使用）---------------------------------

    def get_setting(self, key: str) -> str | None:
        """读取一个设置项的原始字符串。"""
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return None if row is None else str(row["value"])

    def set_setting(self, key: str, value: str) -> None:
        """写入一个设置项（覆盖）。"""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def delete_setting(self, key: str) -> None:
        """删除一个设置项。"""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM settings WHERE key = ?", (key,))


# ---- 模块内工具 ---------------------------------------------------


def _keyword_clause(keyword: str | None, params: list[Any]) -> str:
    """生成 LIKE 条件；对 ``%``、``_``、``\\`` 做转义，避免通配符注入。"""
    if not keyword or not keyword.strip():
        return ""
    escaped = (
        keyword.strip()
        .replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", f"{LIKE_ESCAPE}%")
        .replace("_", f"{LIKE_ESCAPE}_")
    )
    params.append(f"%{escaped}%")
    return "text_content LIKE ? ESCAPE '\\'"


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """sqlite3.Row -> dict，并把 0/1 转成 bool。"""
    data = dict(row)
    data["pinned"] = bool(data.get("pinned"))
    data["is_private"] = bool(data.get("is_private"))
    return data
