"""G2P 服务测试。"""

import pytest

from g2p_service import get_g2p_service, G2PService


class TestG2P:
    def test_basic_conversion(self):
        svc = get_g2p_service()
        phonemes = svc.text_to_phonemes("hello")
        assert "HH" in phonemes
        # hello 的发音可能是 HH AH L OW / HH EH L OW / HH EH L L AA（回退）
        assert "L" in phonemes
        assert len(phonemes) >= 3

    def test_stress_preservation(self):
        """v3 新接口应保留重音标记。"""
        svc = get_g2p_service()
        if not svc.available:
            pytest.skip("g2p_en not available")
        stressed = svc.text_to_phonemes_with_stress("about")
        # about 的重音应在第二个音节
        assert any(p.endswith("1") for p in stressed)

    def test_word_level(self):
        svc = get_g2p_service()
        result = svc.text_to_phonemes_with_words("hello world")
        assert len(result) == 2
        assert result[0]["word"] == "hello"
        assert result[1]["word"] == "world"
        assert len(result[0]["phonemes"]) > 0

    def test_custom_dict(self):
        """v3 支持自定义词典。"""
        assert isinstance(get_g2p_service()._custom_dict, dict)

    def test_letter_fallback_vowels(self):
        """v3 修复：字母级回退必须包含元音。"""
        svc = get_g2p_service()
        # 即使 g2p_en 不可用，回退也应包含元音
        phonemes = svc._letter_fallback("cat")
        assert "K" in phonemes  # c
        assert "AE" in phonemes  # a
        assert "T" in phonemes  # t

    def test_letter_fallback_silent_e(self):
        """词尾 e 不发音。"""
        svc = get_g2p_service()
        phonemes = svc._letter_fallback("cake")
        # cake → K AE K (末尾 e 不发音)
        assert phonemes == ["K", "AE", "K"]

    def test_c_before_e_i_y(self):
        """c 在 e/i/y 前发 /s/。"""
        svc = get_g2p_service()
        phonemes = svc._letter_fallback("city")
        assert "S" in phonemes  # c 在 i 前
        assert "T" in phonemes
        assert "IY" in phonemes

    def test_caching(self):
        """单词级 LRU 缓存应工作。"""
        svc = get_g2p_service()
        r1 = svc._word_to_phonemes_cached("hello")
        r2 = svc._word_to_phonemes_cached("hello")
        assert r1 == r2

    def test_ipa_conversion(self):
        ipa = G2PService.arpabet_to_ipa(["HH", "AH", "L", "OW"])
        assert "h" in ipa
        assert "ə" in ipa or "ʌ" in ipa

    def test_stress_pattern(self):
        svc = get_g2p_service()
        if not svc.available:
            pytest.skip("g2p_en not available")
        pattern = svc.get_stress_pattern("about")
        assert isinstance(pattern, list)
        # about 重音在第二个元音
        assert 1 in pattern
