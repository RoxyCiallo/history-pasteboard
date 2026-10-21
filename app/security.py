"""二级密码：PBKDF2 哈希、失败冷却与会话解锁状态。

安全边界（见 ``docs/08-decisions.md`` ADR-003）：

- 密码只控制界面上的查看与复制，数据库文件本身**未加密**；
- 能直接读取 ``data/history.db`` 的人不受密码保护。

本模块只依赖 ``config``（设置读写），不碰 tkinter、sqlite3，便于单测。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import logging
import os
import time
from typing import TYPE_CHECKING, Any, Callable

import config

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期使用
    import config as config_module

_LOGGER = logging.getLogger("pasteboard.security")

#: 盐长度（字节），见 docs/02 §9
SALT_BYTES = 16
#: 密码最小/最大长度
MIN_PASSWORD_LENGTH = 4
MAX_PASSWORD_LENGTH = 64
#: 连续失败多少次后锁定
MAX_ATTEMPTS = config.MAX_PASSWORD_ATTEMPTS
#: 锁定秒数
LOCK_SECONDS = 30
#: 解锁后空闲多少秒自动上锁
SESSION_IDLE_SECONDS = 5 * 60

#: 重置密码时需要清空的设置键
_PASSWORD_KEYS = ("pwd_salt", "pwd_hash", "pwd_set_at", "pwd_locked_until")


class Security:
    """二级密码的校验与会话状态。

    :param cfg: ``config.Config`` 实例（或其等价 stub）
    :param clock: 单调时钟，测试可注入；默认 ``time.monotonic``
    """

    def __init__(self, cfg: "config_module.Config", clock: Callable[[], float] | None = None) -> None:
        self._config = cfg
        self._clock = clock or time.monotonic
        self._unlocked = False
        self._last_action = 0.0

    # ---- 状态查询 ---------------------------------------------------

    @property
    def unlocked(self) -> bool:
        """本会话是否已解锁。"""
        return self._unlocked

    def is_password_set(self) -> bool:
        """是否已经设置过密码。"""
        return bool(str(self._config.get("pwd_hash") or ""))

    def remaining_lock_seconds(self) -> int:
        """冷却剩余秒数；不在冷却中返回 0。"""
        text = str(self._config.get("pwd_locked_until") or "")
        if not text:
            return 0
        until = _parse_iso(text)
        if until is None:
            return 0
        remain = int((until - _dt.datetime.now()).total_seconds())
        if remain <= 0:
            # 冷却已过，顺手清掉标记，下次失败重新计数。
            self._config.set("pwd_locked_until", "")
            return 0
        return remain

    def remaining_attempts(self) -> int:
        """冷却前还剩几次尝试机会。"""
        count = int(self._config.get("pwd_fail_count") or 0)
        return max(0, MAX_ATTEMPTS - count)

    # ---- 设置与校验 -------------------------------------------------

    def set_password(self, password: str) -> None:
        """设置（或修改）密码；长度不合法时抛 ``ValueError``。"""
        text = str(password or "")
        if len(text) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"密码至少需要 {MIN_PASSWORD_LENGTH} 位")
        if len(text) > MAX_PASSWORD_LENGTH:
            raise ValueError(f"密码不能超过 {MAX_PASSWORD_LENGTH} 位")
        if not text.strip():
            raise ValueError("密码不能全是空格")

        iterations = self._iterations()
        salt = os.urandom(SALT_BYTES)
        digest = hashlib.pbkdf2_hmac("sha256", text.encode("utf-8"), salt, iterations)
        self._config.set("pwd_salt", salt.hex())
        self._config.set("pwd_hash", digest.hex())
        self._config.set("pwd_iterations", iterations)
        self._config.set("pwd_set_at", _now_iso())
        self._config.set("pwd_fail_count", 0)
        self._config.set("pwd_locked_until", "")
        self._unlocked = False
        _LOGGER.info("二级密码已设置")

    def verify(self, password: str) -> bool:
        """校验密码；成功即解锁并重置失败计数。"""
        if not self.is_password_set():
            return False
        if self.remaining_lock_seconds() > 0:
            return False

        salt_hex = str(self._config.get("pwd_salt") or "")
        hash_hex = str(self._config.get("pwd_hash") or "")
        try:
            salt = bytes.fromhex(salt_hex)
        except ValueError:
            _LOGGER.warning("密码盐数据损坏，无法校验")
            return False

        candidate = hashlib.pbkdf2_hmac(
            "sha256", str(password or "").encode("utf-8"), salt, self._iterations()
        )
        if hmac.compare_digest(candidate.hex(), hash_hex):
            self._config.set("pwd_fail_count", 0)
            self._config.set("pwd_locked_until", "")
            self._unlocked = True
            self._last_action = self._clock()
            _LOGGER.info("二级密码校验通过，已解锁")
            return True

        self._record_failure()
        return False

    def reset_password(self) -> None:
        """清空全部密码设置并上锁；私密卡片由调用方负责删除。"""
        for key in _PASSWORD_KEYS:
            self._config.set(key, "")
        self._config.set("pwd_iterations", config.DEFAULT_PBKDF2_ITERATIONS)
        self._config.set("pwd_fail_count", 0)
        self._unlocked = False
        _LOGGER.info("二级密码已重置")

    # ---- 会话状态 ---------------------------------------------------

    def lock(self) -> None:
        """立即上锁（窗口隐藏、自动锁定或重置密码时调用）。"""
        if self._unlocked:
            _LOGGER.info("二级密码已上锁")
        self._unlocked = False

    def touch(self) -> None:
        """记录一次有效操作，用于空闲计时。"""
        if self._unlocked:
            self._last_action = self._clock()

    def lock_if_idle(self, now: float | None = None) -> bool:
        """空闲超时则上锁；返回是否发生了上锁。"""
        if not self._unlocked:
            return False
        moment = self._clock() if now is None else now
        if moment - self._last_action >= SESSION_IDLE_SECONDS:
            self.lock()
            return True
        return False

    # ---- 内部 -------------------------------------------------------

    def _iterations(self) -> int:
        try:
            value = int(self._config.get("pwd_iterations") or 0)
        except (TypeError, ValueError):
            value = 0
        return value if value >= 10_000 else config.DEFAULT_PBKDF2_ITERATIONS

    def _record_failure(self) -> None:
        count = int(self._config.get("pwd_fail_count") or 0) + 1
        if count >= MAX_ATTEMPTS:
            until = _dt.datetime.now() + _dt.timedelta(seconds=LOCK_SECONDS)
            self._config.set("pwd_locked_until", until.strftime("%Y-%m-%dT%H:%M:%S"))
            self._config.set("pwd_fail_count", 0)
            _LOGGER.warning("二级密码连续错误 %d 次，锁定 %d 秒", MAX_ATTEMPTS, LOCK_SECONDS)
        else:
            self._config.set("pwd_fail_count", count)


def _now_iso() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _parse_iso(text: str) -> _dt.datetime | None:
    """解析设置里存的 ISO 时间；兼容秒级与微秒级两种写法。"""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return _dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None
