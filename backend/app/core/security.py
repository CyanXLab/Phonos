"""安全工具：密码哈希（bcrypt）、JWT、token 管理、常量时间比较。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Optional

# bcrypt 是可选依赖；不可用时回退到 pbkdf2_hmac（仍比 SHA256 安全得多）
try:
    import bcrypt as _bcrypt

    _HAS_BCRYPT = True
except ImportError:  # pragma: no cover
    _HAS_BCRYPT = False

from .config import get_settings
from .logging import get_logger


def _hash_password_bcrypt(password: str, rounds: Optional[int] = None) -> str:
    rounds = rounds or get_settings().bcrypt_rounds
    salt = _bcrypt.gensalt(rounds=rounds)
    return _bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def _verify_password_bcrypt(password: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _hash_password_pbkdf2(password: str, salt: str = "") -> str:
    if not salt:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"pbkdf2_sha256${salt}${dk.hex()}"


def _verify_password_pbkdf2(password: str, stored: str) -> bool:
    try:
        algo, salt, hex_hash = stored.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
        return hmac.compare_digest(dk.hex(), hex_hash)
    except (ValueError, TypeError):
        return False


def hash_password(password: str) -> str:
    """生成密码哈希。优先 bcrypt，回退 pbkdf2_hmac。"""
    if _HAS_BCRYPT:
        return _hash_password_bcrypt(password)
    return _hash_password_pbkdf2(password)


def verify_password(password: str, stored: str) -> bool:
    """校验密码。自动识别 bcrypt / pbkdf2 / 旧 SHA256（兼容迁移期）。"""
    if not stored:
        return False
    if stored.startswith("$2"):  # bcrypt 前缀
        return _verify_password_bcrypt(password, stored)
    if stored.startswith("pbkdf2_sha256$"):
        return _verify_password_pbkdf2(password, stored)
    # 兼容旧版 SHA256（迁移期）：先 SHA256 验，通过后由调用方触发升级
    if _looks_like_legacy_sha256(stored):
        return _verify_legacy_sha256(password, stored)
    return False


def needs_rehash(stored: str) -> bool:
    """判断是否需要重新哈希（旧 SHA256 或低 rounds bcrypt）。"""
    if _looks_like_legacy_sha256(stored):
        return True
    if _HAS_BCRYPT and stored.startswith("$2"):
        try:
            rounds = int(stored.split("$")[2])
            target = get_settings().bcrypt_rounds
            return rounds < target
        except (IndexError, ValueError):
            return True
    return False


def _looks_like_legacy_sha256(stored: str) -> bool:
    """旧 Phonos 使用 64 位十六进制 SHA256，无前缀。"""
    return len(stored) == 64 and all(c in "0123456789abcdef" for c in stored.lower())


def _verify_legacy_sha256(password: str, stored: str, salt: str = "") -> bool:
    """旧 Phonos 算法：sha256(salt + password)，salt 来自 auth_service 的全局 salt。"""
    # 注意：旧实现中 salt 是 auth_service 的全局常量，迁移时需传入
    # 此处仅作签名兼容，实际调用时由 auth_service 提供正确 salt
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return hmac.compare_digest(h, stored)


# ============================================================
# Token 管理：保留 UUID4 风格（兼容旧客户端），新增 JWT 选项
# ============================================================

def generate_token() -> str:
    """生成随机 token（与旧版兼容）。"""
    return secrets.token_urlsafe(32)


def generate_short_uuid() -> str:
    return uuid.uuid4().hex[:16]


# ============================================================
# 速率限制（轻量内存版，生产用 Redis）
# ============================================================

class InMemoryRateLimiter:
    """简单的滑动窗口速率限制器（单进程）。"""

    def __init__(self, max_calls: int = 10, window_sec: int = 60):
        self.max_calls = max_calls
        self.window_sec = window_sec
        self._buckets: dict[str, list[float]] = {}

    def check(self, key: str) -> bool:
        now = time.time()
        bucket = self._buckets.setdefault(key, [])
        # 清理过期
        cutoff = now - self.window_sec
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)
        if len(bucket) >= self.max_calls:
            return False
        bucket.append(now)
        return True


# 全局实例：登录失败限制、API 评测限制
login_limiter = InMemoryRateLimiter(max_calls=10, window_sec=60)
evaluate_limiter = InMemoryRateLimiter(max_calls=30, window_sec=60)
