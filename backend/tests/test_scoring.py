"""音素对齐算法单元测试。"""

import pytest

from scoring import align_phonemes, analyze_errors, calculate_pronunciation_score


class TestAlignPhonemes:
    def test_perfect_match(self):
        expected = ["AH", "B", "AA", "T"]
        actual = ["AH", "B", "AA", "T"]
        alignment, cost = align_phonemes(expected, actual)
        assert cost == 0.0
        assert len(alignment) == 4
        for exp, act in alignment:
            assert exp == act

    def test_substitution(self):
        expected = ["TH", "R", "IY"]
        actual = ["S", "R", "IY"]  # TH -> S（最小对立对）
        alignment, cost = align_phonemes(expected, actual)
        assert cost > 0
        assert alignment[0] == ("TH", "S")

    def test_deletion(self):
        expected = ["DH", "AH", "K", "AE", "T"]
        actual = ["AH", "K", "AE", "T"]  # 漏读 DH
        alignment, _ = align_phonemes(expected, actual)
        assert ("DH", None) in alignment

    def test_insertion(self):
        expected = ["HH", "AH", "L", "OW"]
        actual = ["HH", "AH", "L", "AH", "OW"]  # 多读 AH
        alignment, _ = align_phonemes(expected, actual)
        assert (None, "AH") in alignment

    def test_empty_expected(self):
        alignment, cost = align_phonemes([], ["AH"])
        assert cost == 1.0
        assert alignment == [(None, "AH")]

    def test_empty_actual(self):
        alignment, cost = align_phonemes(["AH"], [])
        assert cost == 1.0
        assert alignment == [("AH", None)]


class TestAnalyzeErrors:
    def test_no_errors(self):
        expected = ["AH", "B", "AA", "T"]
        actual = ["AH", "B", "AA", "T"]
        alignment, _ = align_phonemes(expected, actual)
        errors = analyze_errors(alignment, expected)
        assert len(errors) == 0

    def test_substitution_error(self):
        expected = ["TH", "R", "IY"]
        actual = ["S", "R", "IY"]
        alignment, _ = align_phonemes(expected, actual)
        errors = analyze_errors(alignment, expected)
        assert len(errors) == 1
        assert errors[0].error_type == "substitution"
        assert errors[0].expected == "TH"
        assert errors[0].actual == "S"
        assert errors[0].is_minimal_pair_issue  # TH/S 是最小对立对

    def test_deletion_error(self):
        expected = ["DH", "AH"]
        actual = ["AH"]
        alignment, _ = align_phonemes(expected, actual)
        errors = analyze_errors(alignment, expected)
        assert any(e.error_type == "deletion" for e in errors)

    def test_insertion_error(self):
        expected = ["AH"]
        actual = ["AH", "B"]
        alignment, _ = align_phonemes(expected, actual)
        errors = analyze_errors(alignment, expected)
        assert any(e.error_type == "insertion" for e in errors)


class TestPronunciationScore:
    def test_perfect_score(self):
        expected = ["AH", "B", "AA", "T"]
        actual = ["AH", "B", "AA", "T"]
        alignment, _ = align_phonemes(expected, actual)
        errors = analyze_errors(alignment, expected)
        score = calculate_pronunciation_score(alignment, errors, expected)
        assert score > 90  # 完美匹配应得高分

    def test_zero_score_on_all_deletion(self):
        expected = ["AH", "B", "AA", "T"]
        actual = []
        alignment, _ = align_phonemes(expected, actual)
        errors = analyze_errors(alignment, expected)
        score = calculate_pronunciation_score(alignment, errors, expected)
        assert score < 10  # 全部漏读应得极低分
