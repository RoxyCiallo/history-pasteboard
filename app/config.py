"""设置项读写：默认值、类型转换与范围校验。

设置统一存放在 SQLite 的 ``settings`` 表里（键和值都是 TEXT）。本模块负责：

1. 定义每个设置键的默认值、类型与取值范围；
2. 读取时把字符串还原成 int/bool，存了脏数据则回退默认值；
3. 写入前做校验，越界直接抛 ``ValueError``，避免脏数据落库。

依赖方向：``config`` -> ``db``（``db`` 不反向依赖 ``config``）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期使用
    import db as db_module

# 保留期默认值与允许范围（见 docs/01 FR-10）
DEFAULT_RETENTION_DAYS = 3
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 365

# 密码迭代次数默认值（见 docs/02 §9）
DEFAULT_PBKDF2_ITERATIONS = 200_000


@dataclass(frozen=True)
class SettingSpec:
    """一个设置项的定义。"""

    default: Any
    kind: str  # "int" | "bool" | "str"
    min_value: int | None = None
    max_value: int | None = None


# 所有受支持的设置键。新增键必须同时更新 docs/02 的 settings 表。
SPECS: dict[str, SettingSpec] = {
    "retention_days": SettingSpec(DEFAULT_RETENTION_DAYS, "int", MIN_RETENTION_DAYS, MAX_RETENTION_DAYS),
    "pwd_salt": SettingSpec("", "str"),
    "pwd_hash": SettingSpec("", "str"),
    "pwd_iterations": SettingSpec(DEFAULT_PBKDF2_ITERATIONS, "int", 10_000, 10_000_000),
    "pwd_set_at": SettingSpec("", "str"),
    "hotkey": SettingSpec("ctrl+shift+v", "str"),
    "hide_hint_shown": SettingSpec(False, "bool"),
    "window_geometry": SettingSpec("", "str"),
    "last_purge_at": SettingSpec("", "str"),
}


class Config:
    """settings 表的高层读写接口。"""

    def __init__(self, database: "db_module.Database") -> None:
        self._db = database

    # ---- 通用读写 -------------------------------------------------

    def get(self, key: str) -> Any:
        """读取并转换一个设置；无记录或值非法时返回默认值。"""
        spec = self._spec(key)
        raw = self._db.get_setting(key)
        if raw is None:
            return spec.default
        return _to_value(spec, raw, fallback=spec.default)

    def set(self, key: str, value: Any) -> None:
        """校验并写入一个设置。"""
        spec = self._spec(key)
        self._db.set_setting(key, _to_text(spec, value))

    def get_all(self) -> dict[str, Any]:
        """返回全部设置（含默认值），便于设置面板一次性读取。"""
        return {key: self.get(key) for key in SPECS}

    # ---- 便捷属性 -------------------------------------------------

    @property
    def retention_days(self) -> int:
        """当前保留天数。"""
        return int(self.get("retention_days"))

    @retention_days.setter
    def retention_days(self, days: int) -> None:
        self.set("retention_days", days)

    # ---- 内部 -----------------------------------------------------

    @staticmethod
    def _spec(key: str) -> SettingSpec:
        try:
            return SPECS[key]
        except KeyError as exc:
            raise KeyError(f"未知的设置键：{key}") from exc


def _to_text(spec: SettingSpec, value: Any) -> str:
    """把 Python 值转换成入库字符串，并做类型与范围校验。"""
    if spec.kind == "bool":
        if isinstance(value, str):
            return "1" if value.strip().lower() in {"1", "true", "yes", "on"} else "0"
        return "1" if value else "0"

    if spec.kind == "int":
        if isinstance(value, bool):
            raise ValueError("布尔值不能写入整数设置")
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"需要整数，收到：{value!r}") from exc
        if spec.min_value is not None and number < spec.min_value:
            raise ValueError(f"不能小于 {spec.min_value}，收到：{number}")
        if spec.max_value is not None and number > spec.max_value:
            raise ValueError(f"不能大于 {spec.max_value}，收到：{number}")
        return str(number)

    return "" if value is None else str(value)


def _to_value(spec: SettingSpec, raw: str, *, fallback: Any) -> Any:
    """把库里的字符串还原成 Python 值；非法数据返回 fallback。"""
    if spec.kind == "bool":
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    if spec.kind == "int":
        try:
            number = int(raw)
        except (TypeError, ValueError):
            return fallback
        if spec.min_value is not None and number < spec.min_value:
            return fallback
        if spec.max_value is not None and number > spec.max_value:
            return fallback
        return number

    return raw
