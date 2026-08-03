"""评分 v2 单元测试。"""

import pytest

from app.services.scoring_v2 import (
    ErrorType,
    ScoreBreakdown,
    evaluate_pronunciation_v2,
    result_v2_to_dict,
    ScoreCalibrator,
    _is_vowel_length_error,
    _check_minimal_pair,
)


class TestVowelLengthError:
    def test_ih_iy(self):
        assert _is_vowel_length_error("IH", "IY")
        assert _is_vowel_length_error("IY", "IH")

    def test_uh_uw(self):
        assert _is_vowel_length_error("UH", "UW")

    def test_consonants_not_vowel_length(self):
        assert not _is_vowel_length_error("P", "B")


class TestMinimalPair:
    def test_l_r(self):
        mp = _check_minimal_pair("L", "R")
        assert mp is not None
        assert mp["pair"] == ("L", "R")

    def test_th_s(self):
        mp = _check_minimal_pair("TH", "S")
        assert mp is not None

    def test_no_match(self):
        assert _check_minimal_pair("AH", "B") is None


class TestEvaluateV2:
    def test_perfect_match(self):
        expected = ["AH", "B", "AA", "T"]
        actual = ["AH", "B", "AA", "T"]
        timeline = [
            {"phoneme": "AH", "start_time": 0.0, "end_time": 0.1, "duration": 0.1, "confidence": 0.95},
            {"phoneme": "B", "start_time": 0.1, "end_time": 0.2, "duration": 0.1, "confidence": 0.92},
            {"phoneme": "AA", "start_time": 0.2, "end_time": 0.4, "duration": 0.2, "confidence": 0.93},
            {"phoneme": "T", "start_time": 0.4, "end_time": 0.5, "duration": 0.1, "confidence": 0.91},
        ]
        result = evaluate_pronunciation_v2(
            expected_phonemes=expected,
            actual_phonemes=actual,
            timeline=timeline,
            total_duration=0.5,
        )
        assert result.scores.phoneme_accuracy > 90
        assert result.scores.overall > 80
        # 所有音素应为 match
        assert all(p.error_type == ErrorType.MATCH for p in result.phonemes)

    def test_substitution_detected(self):
        expected = ["TH", "R", "IY"]
        actual = ["S", "R", "IY"]
        result = evaluate_pronunciation_v2(
            expected_phonemes=expected,
            actual_phonemes=actual,
        )
        sub_errors = [p for p in result.phonemes if p.error_type == ErrorType.MINIMAL_PAIR_CONFUSION]
        assert len(sub_errors) == 1
        assert sub_errors[0].expected_phone == "TH"
        assert sub_errors[0].recognized_phone == "S"

    def test_deletion_detected(self):
        expected = ["DH", "AH", "K", "AE", "T"]
        actual = ["AH", "K", "AE", "T"]
        result = evaluate_pronunciation_v2(
            expected_phonemes=expected,
            actual_phonemes=actual,
        )
        del_errors = [p for p in result.phonemes if p.error_type == ErrorType.DELETION]
        assert len(del_errors) == 1
        assert del_errors[0].expected_phone == "DH"

    def test_insertion_detected(self):
        expected = ["HH", "AH", "L", "OW"]
        actual = ["HH", "AH", "L", "AH", "OW"]
        result = evaluate_pronunciation_v2(
            expected_phonemes=expected,
            actual_phonemes=actual,
        )
        ins_errors = [p for p in result.phonemes if p.error_type == ErrorType.INSERTION]
        assert len(ins_errors) == 1

    def test_confidence_weighting(self):
        """低置信度的错误扣分应更轻。"""
        expected = ["AH", "B", "AA", "T"]
        actual = ["AE", "B", "AA", "T"]  # AH -> AE 替换
        # 高置信度
        result_high = evaluate_pronunciation_v2(
            expected_phonemes=expected,
            actual_phonemes=actual,
            phone_confidences=[0.95, 0.9, 0.9, 0.9],
        )
        # 低置信度
        result_low = evaluate_pronunciation_v2(
            expected_phonemes=expected,
            actual_phonemes=actual,
            phone_confidences=[0.3, 0.9, 0.9, 0.9],
        )
        # 低置信度时分数应更高（错误扣分更轻）
        assert result_low.scores.phoneme_accuracy >= result_high.scores.phoneme_accuracy

    def test_tips_generation(self):
        expected = ["TH", "R", "IY"]
        actual = ["S", "R", "IY"]
        result = evaluate_pronunciation_v2(
            expected_phonemes=expected,
            actual_phonemes=actual,
        )
        assert len(result.tips) > 0
        # 应有最小对立对 tip
        mp_tips = [t for t in result.tips if t.get("type") == "minimal_pair_confusion"]
        assert len(mp_tips) > 0

    def test_result_to_dict(self):
        expected = ["AH", "B"]
        actual = ["AH", "B"]
        result = evaluate_pronunciation_v2(
            expected_phonemes=expected,
            actual_phonemes=actual,
        )
        d = result_v2_to_dict(result)
        assert d["version"] == "v2"
        assert "scores" in d
        assert "phonemes" in d
        assert "fluency_details" in d


class TestCalibrator:
    def test_linear_fit(self):
        cal = ScoreCalibrator()
        # 简单线性关系：target = 0.8 * raw + 10
        raw = [50, 60, 70, 80, 90, 100]
        target = [0.8 * r + 10 for r in raw]
        params = cal.fit_linear("overall", raw, target)
        assert abs(params["a"] - 0.8) < 0.01
        assert abs(params["b"] - 10) < 0.5

    def test_apply(self):
        cal = ScoreCalibrator()
        cal._params[("overall", "linear")] = {"a": 0.8, "b": 10}
        assert abs(cal.apply("overall", 50) - 50) < 0.1

    def test_no_params_returns_raw(self):
        cal = ScoreCalibrator()
        assert cal.apply("unknown", 75) == 75
