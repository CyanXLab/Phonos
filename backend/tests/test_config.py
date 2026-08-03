"""配置测试。"""

import os

from app.core.config import get_settings, reload_settings


class TestSettings:
    def test_default_values(self):
        s = get_settings()
        assert s.app_version == "3.0.0"
        assert s.env in ("local", "dev", "staging", "prod", "test")
        assert s.port == 8000
        # bcrypt_rounds 可能被 .env 覆盖（测试环境可能用更小值）
        assert s.bcrypt_rounds >= 4

    def test_cors_origins_parsing(self):
        os.environ["CORS_ALLOWED_ORIGINS_STR"] = "https://a.com,https://b.com"
        s = reload_settings()
        assert "https://a.com" in s.cors_allowed_origins
        assert "https://b.com" in s.cors_allowed_origins
        del os.environ["CORS_ALLOWED_ORIGINS_STR"]

    def test_effective_huper_model_path(self):
        s = get_settings()
        # 不存在时返回空字符串
        path = s.effective_huper_model_path()
        assert isinstance(path, str)

    def test_provider_list_auto(self):
        s = get_settings()
        providers = s.get_provider_list()
        assert isinstance(providers, list)
        assert len(providers) > 0

    def test_provider_list_cpu(self):
        os.environ["HUPER_PROVIDER"] = "cpu"
        s = reload_settings()
        providers = s.get_provider_list()
        assert "CPUExecutionProvider" in providers
        del os.environ["HUPER_PROVIDER"]

    def test_is_production(self):
        os.environ["ENV"] = "prod"
        s = reload_settings()
        assert s.is_production
        del os.environ["ENV"]

    def test_privacy_defaults(self):
        """隐私默认安全。"""
        s = get_settings()
        assert s.upload_user_audio is False  # 默认不上传音频
        assert s.enable_azure_pronunciation is False
        assert s.enable_xfyun_ise is False
        assert s.enable_youdao is False
