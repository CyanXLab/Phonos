"""听写 v2 测试。"""

import pytest

from app.services.dictation_v2 import evaluate_dictation_v2


class TestDictationV2:
    def test_perfect_match(self):
        result = evaluate_dictation_v2(
            expected_text="The weather is beautiful today",
            actual_text="The weather is beautiful today",
        )
        assert result.overall_score == 100.0
        assert result.summary["match"] == 5
        assert result.summary["substitution"] == 0

    def test_case_insensitive(self):
        result = evaluate_dictation_v2(
            expected_text="Hello World",
            actual_text="hello world",
        )
        assert result.overall_score == 100.0

    def test_punctuation_ignored(self):
        result = evaluate_dictation_v2(
            expected_text="Hello, world!",
            actual_text="hello world",
        )
        assert result.overall_score == 100.0

    def test_substitution(self):
        result = evaluate_dictation_v2(
            expected_text="The weather is beautiful",
            actual_text="The whether is beautiful",
        )
        # weather/whether 相似度 0.71，应识别为 partial 或 near_correct
        assert result.summary["substitution"] >= 1 or result.summary["near_correct"] >= 1 or result.summary["partial"] >= 1
        assert result.overall_score < 100

    def test_deletion(self):
        result = evaluate_dictation_v2(
            expected_text="The weather is beautiful today",
            actual_text="The weather is beautiful",
        )
        assert result.summary["deletion"] >= 1

    def test_insertion(self):
        result = evaluate_dictation_v2(
            expected_text="The weather",
            actual_text="The weather is nice",
        )
        assert result.summary["insertion"] >= 2

    def test_near_correct(self):
        """编辑距离 ≤ 1 视为 near_correct。"""
        result = evaluate_dictation_v2(
            expected_text="beautiful",
            actual_text="beautifull",  # 多一个 l
        )
        assert result.summary["near_correct"] >= 1

    def test_grammar_variant(self):
        """语法变形应识别为 near_correct。"""
        result = evaluate_dictation_v2(
            expected_text="The children are playing",
            actual_text="The childs are playing",
        )
        # child/children 应识别为语法变形
        assert result.summary["near_correct"] >= 1 or result.summary["partial"] >= 1

    def test_keywords_weight(self):
        """关键词错误扣更多分。"""
        result_no_kw = evaluate_dictation_v2(
            expected_text="The weather is beautiful",
            actual_text="The weather is beautifull",  # near_correct
        )
        result_with_kw = evaluate_dictation_v2(
            expected_text="The weather is beautiful",
            actual_text="The weather is beautifull",
            keywords=["beautiful"],
        )
        # 关键词加权后分数应更低（near_correct 关键词扣更多）
        assert result_with_kw.overall_score <= result_no_kw.overall_score

    def test_order_error_detection(self):
        """检测词序错误。"""
        result = evaluate_dictation_v2(
            expected_text="I love you",
            actual_text="I you love",
        )
        # 应检测到顺序错误
        assert result.summary["order_error"] >= 1 or result.summary["substitution"] >= 1

    def test_keywords_coverage(self):
        result = evaluate_dictation_v2(
            expected_text="The weather is beautiful today",
            actual_text="The weather is nice today",
            keywords=["weather", "beautiful", "today"],
        )
        assert result.keywords_coverage["total"] == 3
        # weather 和 today 命中，beautiful 漏
        assert result.keywords_coverage["correct"] >= 2
        assert "beautiful" in result.keywords_coverage["missed"]

    def test_tips_generation(self):
        result = evaluate_dictation_v2(
            expected_text="The weather is beautiful",
            actual_text="The",  # 大量漏写
        )
        assert len(result.tips) > 0
        assert any("漏写" in tip for tip in result.tips)
