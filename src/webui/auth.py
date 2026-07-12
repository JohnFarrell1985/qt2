"""模拟盘用户鉴权 (仅口令)

- 注册: 仅需用户名 + 口令 (其余无需)。口令以 PBKDF2-HMAC-SHA256 + 随机盐 存储。
- 登录: 校验口令, 签发内存会话令牌 (进程级, 重启失效, 本地场景足够)。
- 首启种子: 自动创建 ``root`` 用户, 口令 ``1234`` (若不存在)。
"""
from __future__ import annotations

import hashlib
import secrets
import threading
from typing import Optional

from src.common.logger import get_logger
from src.webui.store import MemoryStore, PaperStore

logger = get_logger(__name__)

_ITERATIONS = 120_000


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _ITERATIONS)
    return dk.hex(), salt


def verify_password(password: str, pwd_hash: str, salt: str) -> bool:
    calc, _ = hash_password(password, salt)
    return secrets.compare_digest(calc, pwd_hash)


class AuthError(Exception):
    """鉴权相关错误 (用户名占用 / 口令错误 / 未登录等)。"""


class AuthManager:
    def __init__(self, store, on_register=None, seed_root: bool = True):
        self.store = store
        self._sessions: dict[str, str] = {}   # token -> username
        self._lock = threading.RLock()
        self._on_register = on_register        # 回调: 新用户创建后初始化其账户
        if seed_root:
            self._seed_root()

    def _seed_root(self) -> None:
        try:
            if self.store.get_user("root") is None:
                self._create("root", "1234")
                logger.info("已创建默认用户 root (口令 1234)")
        except Exception as e:  # noqa: BLE001
            logger.warning("初始化 root 用户失败: %s", e)

    def _create(self, username: str, password: str) -> None:
        h, salt = hash_password(password)
        self.store.create_user(username, h, salt)
        if self._on_register:
            self._on_register(username)

    # ------------------------------------------------------------------
    def register(self, username: str, password: str) -> str:
        username = (username or "").strip()
        if not username:
            raise AuthError("用户名不能为空")
        if len(username) > 64:
            raise AuthError("用户名过长")
        if not password:
            raise AuthError("口令不能为空")
        if self.store.get_user(username) is not None:
            raise AuthError("用户名已存在")
        self._create(username, password)
        return self.login(username, password)

    def login(self, username: str, password: str) -> str:
        user = self.store.get_user((username or "").strip())
        if user is None or not verify_password(password, user["pwd_hash"], user["salt"]):
            raise AuthError("用户名或口令错误")
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._sessions[token] = user["username"]
        return token

    def logout(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    def resolve(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        with self._lock:
            return self._sessions.get(token)

    def change_password(self, username: str, new_password: str) -> None:
        if not new_password:
            raise AuthError("口令不能为空")
        h, salt = hash_password(new_password)
        self.store.update_password(username, h, salt)


def default_store():
    """返回生产用 DB 存储; 无 DB 时回退内存存储 (仍可跑起来)。"""
    try:
        return PaperStore()
    except Exception as e:  # noqa: BLE001
        logger.warning("模拟盘 DB 存储不可用, 回退内存存储: %s", e)
        return MemoryStore()
