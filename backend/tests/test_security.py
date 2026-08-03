"""安全模块测试。"""

import pytest

from app.core.security import (
    hash_password,
    verify_password,
    needs_rehash,
    generate_token,
    InMemoryRateLimiter,
)


class TestPasswordHashing:
    def test_bcrypt_hash(self):
        hashed = hash_password("TestPass123")
        # bcrypt 哈希以 $2 开头
        assert hashed.startswith("$2") or hashed.startswith("pbkdf2_sha256$")

    def test_verify_correct(self):
        hashed = hash_password("TestPass123")
        assert verify_password("TestPass123", hashed)

    def test_verify_wrong(self):
        hashed = hash_password("TestPass123")
        assert not verify_password("WrongPass", hashed)

    def test_legacy_sha256_compat(self):
        """兼容旧版 SHA256 哈希（需要提供 salt）。"""
        import hashlib

        # 旧版 Phonos 使用 sha256(salt + password)
        # 注意：verify_password 在没有 salt 时无法验证旧 SHA256
        # 实际迁移由 auth_service._verify_password_v3 处理（含 legacy_salt 参数）
        salt = "abc123"
        legacy = hashlib.sha256((salt + "oldpass").encode()).hexdigest()
        # 直接调用 verify_password 不传 salt 时，64 位 hex 会被识别为 legacy 但无 salt 验证失败
        # 这是预期行为：迁移由 auth_service 处理
        assert not verify_password("oldpass", legacy)  # 无 salt 无法验证
        assert needs_rehash(legacy)  # 但应标记为需要重哈希

    def test_needs_rehash_legacy(self):
        """旧 SHA256 应标记为需要重哈希。"""
        import hashlib

        legacy = hashlib.sha256("abc".encode()).hexdigest()
        assert needs_rehash(legacy)

    def test_needs_rehash_bcrypt_low_rounds(self):
        try:
            import bcrypt

            low = bcrypt.hashpw(b"pass", bcrypt.gensalt(rounds=4)).decode()
            assert needs_rehash(low)
        except ImportError:
            pytest.skip("bcrypt not installed")


class TestToken:
    def test_generate_token_unique(self):
        t1 = generate_token()
        t2 = generate_token()
        assert t1 != t2
        assert len(t1) >= 32


class TestRateLimiter:
    def test_allows_under_limit(self):
        limiter = InMemoryRateLimiter(max_calls=3, window_sec=60)
        assert limiter.check("k1")
        assert limiter.check("k1")
        assert limiter.check("k1")

    def test_blocks_over_limit(self):
        limiter = InMemoryRateLimiter(max_calls=2, window_sec=60)
        limiter.check("k1")
        limiter.check("k1")
        assert not limiter.check("k1")

    def test_different_keys_independent(self):
        limiter = InMemoryRateLimiter(max_calls=1, window_sec=60)
        assert limiter.check("k1")
        assert limiter.check("k2")  # 不同 key 不受限
