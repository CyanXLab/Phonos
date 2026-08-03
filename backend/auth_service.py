"""
Phonos 用户认证服务

功能：用户注册、登录、会话管理、用户切换
密码安全：hashlib.sha256 + 随机盐值
令牌：UUID4，存储在 user_sessions 表
会话过期：30天
"""

import sqlite3
import uuid
import hashlib
import hmac
import time
import json
import secrets
from pathlib import Path
from typing import Optional, Dict

DB_PATH = Path(__file__).parent / "phonos_auth.db"

SESSION_EXPIRY_DAYS = 30
AVATAR_COLORS = [
    "#4f46e5", "#7c3aed", "#2563eb", "#0891b2", "#0d9488",
    "#059669", "#65a30d", "#ca8a04", "#ea580c", "#dc2626",
    "#e11d48", "#be185d", "#9333ea", "#6366f1", "#3b82f6",
]

# v3：使用 bcrypt 优先，回退 pbkdf2，兼容旧 SHA256
try:
    import bcrypt as _bcrypt
    _HAS_BCRYPT = True
except ImportError:
    _HAS_BCRYPT = False


def _hash_password(password: str, salt: str) -> str:
    """SHA256 hash with salt（旧版，仅用于兼容验证）"""
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def _hash_password_v3(password: str) -> str:
    """v3 密码哈希：优先 bcrypt，回退 pbkdf2_hmac。"""
    if _HAS_BCRYPT:
        return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode("utf-8")
    # pbkdf2_hmac 回退（200k 迭代）
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"pbkdf2_sha256${salt}${dk.hex()}"


def _verify_password_v3(password: str, stored: str, legacy_salt: str = "") -> bool:
    """v3 密码校验：自动识别 bcrypt/pbkdf2/旧 SHA256。"""
    if not stored:
        return False
    # bcrypt
    if stored.startswith("$2"):
        try:
            return _bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
        except (ValueError, TypeError):
            return False
    # pbkdf2
    if stored.startswith("pbkdf2_sha256$"):
        try:
            algo, salt, hex_hash = stored.split("$", 2)
            dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
            return hmac.compare_digest(dk.hex(), hex_hash)
        except (ValueError, TypeError):
            return False
    # 旧 SHA256（64 位十六进制）
    if len(stored) == 64 and legacy_salt:
        h = hashlib.sha256((legacy_salt + password).encode("utf-8")).hexdigest()
        return hmac.compare_digest(h, stored)
    return False


def _needs_rehash(stored: str) -> bool:
    """判断是否需要重新哈希（旧 SHA256 或低 rounds bcrypt）。"""
    if len(stored) == 64 and all(c in "0123456789abcdef" for c in stored.lower()):
        return True
    if _HAS_BCRYPT and stored.startswith("$2"):
        try:
            rounds = int(stored.split("$")[2])
            return rounds < 12
        except (IndexError, ValueError):
            return True
    return False


def _get_conn(db_path: str = None):
    return sqlite3.connect(db_path or str(DB_PATH))


class AuthService:
    """用户认证服务"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                avatar_color TEXT NOT NULL DEFAULT '#4f46e5',
                created_at REAL NOT NULL DEFAULT 0,
                last_login REAL NOT NULL DEFAULT 0,
                settings TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS user_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token TEXT UNIQUE NOT NULL,
                created_at REAL NOT NULL DEFAULT 0,
                expires_at REAL NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_token ON user_sessions(token);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
        """)
        conn.commit()
        # Don't close yet, we need to ensure guest user
        self._ensure_guest_user(conn)
        conn.close()

    def _ensure_guest_user(self, conn=None):
        """确保默认访客用户存在（向后兼容）"""
        close = False
        if conn is None:
            conn = self._get_conn()
            close = True
        try:
            row = conn.execute("SELECT id FROM users WHERE id = 'default'").fetchone()
            if not row:
                salt = uuid.uuid4().hex
                password_hash = _hash_password("guest", salt)
                conn.execute(
                    "INSERT INTO users (id, username, password_hash, salt, display_name, avatar_color, created_at, last_login) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("default", "guest", password_hash, salt, "访客", "#6b7280", time.time(), time.time())
                )
                conn.commit()
        finally:
            if close:
                conn.close()

    def register(self, username: str, password: str, display_name: str = "") -> Dict:
        """注册新用户"""
        if not username or len(username) < 3 or len(username) > 20:
            raise ValueError("用户名长度须在3-20个字符之间")
        if not password or len(password) < 8:
            raise ValueError("密码至少8个字符")
        if not username.replace("_", "").replace("-", "").isalnum():
            raise ValueError("用户名只能包含字母、数字、下划线和连字符")
        # 密码强度检查
        if not any(c.isupper() for c in password) or not any(c.islower() for c in password) or not any(c.isdigit() for c in password):
            raise ValueError("密码必须包含大小写字母和数字")

        user_id = str(uuid.uuid4())
        salt = uuid.uuid4().hex  # 保留字段（兼容旧 schema）
        password_hash = _hash_password_v3(password)  # v3 哈希
        # 稳定的 avatar 颜色（基于 sha256，而非 Python hash）
        color_idx = int(hashlib.sha256(username.encode()).hexdigest(), 16) % len(AVATAR_COLORS)
        avatar_color = AVATAR_COLORS[color_idx]
        display_name = display_name or username
        now = time.time()

        conn = _get_conn(self.db_path)
        try:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, salt, display_name, avatar_color, created_at, last_login) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, username, password_hash, salt, display_name, avatar_color, now, now)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            raise ValueError("用户名已存在")
        conn.close()

        # Auto-login after registration
        token_data = self._create_session(user_id)
        user = self._get_user_by_id(user_id)
        return {
            "token": token_data["token"],
            "user": user,
        }

    def login(self, username: str, password: str) -> Dict:
        """用户登录"""
        conn = _get_conn(self.db_path)
        row = conn.execute(
            "SELECT id, password_hash, salt FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        conn.close()

        if not row:
            # 常量时间延迟，避免用户名枚举
            _verify_password_v3(password, "$2b$12$" + "x" * 53)
            raise ValueError("用户名或密码错误")

        user_id, stored_hash, salt = row
        if not _verify_password_v3(password, stored_hash, legacy_salt=salt):
            raise ValueError("用户名或密码错误")

        # v3：旧 SHA256 自动升级到 bcrypt/pbkdf2
        if _needs_rehash(stored_hash):
            new_hash = _hash_password_v3(password)
            conn = _get_conn(self.db_path)
            conn.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
                (new_hash, "", user_id),
            )
            conn.commit()
            conn.close()

        # Update last login
        conn = _get_conn(self.db_path)
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (time.time(), user_id))
        conn.commit()
        conn.close()

        token_data = self._create_session(user_id)
        user = self._get_user_by_id(user_id)
        return {
            "token": token_data["token"],
            "user": user,
        }

    def logout(self, token: str) -> bool:
        """登出（删除会话）"""
        conn = _get_conn(self.db_path)
        conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
        conn.commit()
        affected = conn.total_changes
        conn.close()
        return True

    def get_user_by_token(self, token: str) -> Optional[Dict]:
        """通过令牌获取用户"""
        if not token:
            return self._get_user_by_id("default")

        conn = _get_conn(self.db_path)
        row = conn.execute(
            "SELECT user_id, expires_at FROM user_sessions WHERE token = ?",
            (token,)
        ).fetchone()
        conn.close()

        if not row:
            return self._get_user_by_id("default")

        user_id, expires_at = row
        if time.time() > expires_at:
            # Session expired, clean up
            conn = _get_conn(self.db_path)
            conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
            conn.commit()
            conn.close()
            return self._get_user_by_id("default")

        return self._get_user_by_id(user_id)

    def update_profile(self, user_id: str, display_name: str = None, settings: dict = None) -> Dict:
        """更新用户资料"""
        conn = _get_conn(self.db_path)
        if display_name is not None:
            conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (display_name, user_id))
        if settings is not None:
            conn.execute("UPDATE users SET settings = ? WHERE id = ?", (json.dumps(settings), user_id))
        conn.commit()
        conn.close()
        return self._get_user_by_id(user_id)

    def change_password(self, user_id: str, old_password: str, new_password: str, current_token: str = "") -> bool:
        """修改密码（v3：失效其他会话）"""
        if len(new_password) < 8:
            raise ValueError("新密码至少8个字符")
        if not any(c.isupper() for c in new_password) or not any(c.islower() for c in new_password) or not any(c.isdigit() for c in new_password):
            raise ValueError("密码必须包含大小写字母和数字")

        conn = _get_conn(self.db_path)
        row = conn.execute(
            "SELECT password_hash, salt FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()

        if not row:
            conn.close()
            raise ValueError("用户不存在")

        stored_hash, salt = row
        if not _verify_password_v3(old_password, stored_hash, legacy_salt=salt):
            conn.close()
            raise ValueError("旧密码错误")

        new_hash = _hash_password_v3(new_password)
        conn.execute(
            "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
            (new_hash, "", user_id)
        )
        # v3：失效除当前会话外的所有会话
        if current_token:
            conn.execute(
                "DELETE FROM user_sessions WHERE user_id = ? AND token != ?",
                (user_id, current_token)
            )
        else:
            conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

        return True

    # 注意：不提供 list_users 接口，不暴露其他用户信息
    # 每个用户只能看到自己的数据，跨浏览器通过服务端数据库同步

    def _create_session(self, user_id: str) -> Dict:
        """创建会话令牌"""
        session_id = str(uuid.uuid4())
        token = str(uuid.uuid4())
        now = time.time()
        expires_at = now + SESSION_EXPIRY_DAYS * 86400

        conn = _get_conn(self.db_path)
        # Clean up old sessions for this user (keep only 5 most recent)
        conn.execute(
            "DELETE FROM user_sessions WHERE user_id = ? AND id NOT IN (SELECT id FROM user_sessions WHERE user_id = ? ORDER BY created_at DESC LIMIT 4)",
            (user_id, user_id)
        )
        conn.execute(
            "INSERT INTO user_sessions (id, user_id, token, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, token, now, expires_at)
        )
        conn.commit()
        conn.close()

        return {"token": token, "expires_at": expires_at}

    def _get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """通过ID获取用户信息"""
        conn = _get_conn(self.db_path)
        row = conn.execute(
            "SELECT id, username, display_name, avatar_color, created_at, last_login, settings FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        conn.close()

        if not row:
            return {
                "id": "default",
                "username": "guest",
                "display_name": "访客",
                "avatar_color": "#6b7280",
                "created_at": 0,
                "last_login": 0,
                "settings": {},
            }

        return {
            "id": row[0],
            "username": row[1],
            "display_name": row[2],
            "avatar_color": row[3],
            "created_at": row[4],
            "last_login": row[5],
            "settings": json.loads(row[6]) if row[6] else {},
        }


# 全局实例
_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
