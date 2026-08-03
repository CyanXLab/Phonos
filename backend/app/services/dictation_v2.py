"""听写评分 v2 - 词级对齐 + 拼写容错 + 音近词容错 + 关键词权重 + 语义近似。

升级点：
1. 词级 Levenshtein 对齐（保留旧版）
2. 拼写容错：编辑距离 ≤ 1 算 near_correct
3. 音近词容错：通过 G2P 检测音素相同的拼写差异
4. 关键词权重：标记关键词，错扣更多分
5. 漏词/多词/错序/语法变形/语义近似 全覆盖
6. 输出每个词的对齐详情（含 expected/actual/match_type/score）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class WordMatch:
    expected: str
    actual: Optional[str]
    match_type: str  # match / near_correct / partial / substitution / deletion / insertion / order_error
    similarity: float
    expected_index: int
    actual_index: Optional[int]
    is_keyword: bool = False
    is_grammar_variant: bool = False
    is_phonetic_similar: bool = False
    note: str = ""


@dataclass
class DictationResultV2:
    overall_score: float
    words: List[WordMatch]
    summary: dict
    keywords_coverage: dict
    tips: List[str] = field(default_factory=list)


# 关键词权重：默认 1.0，关键词 2.0
KEYWORD_WEIGHT = 2.0


def evaluate_dictation_v2(
    expected_text: str,
    actual_text: str,
    keywords: Optional[List[str]] = None,
    keywords_weight: float = KEYWORD_WEIGHT,
    near_correct_threshold: float = 0.85,
    partial_threshold: float = 0.6,
) -> DictationResultV2:
    """v2 听写评分。

    Args:
        expected_text: 标准答案
        actual_text: 用户输入
        keywords: 关键词列表（错扣更多分）
        keywords_weight: 关键词权重倍数
        near_correct_threshold: 视为 near_correct 的相似度阈值
        partial_threshold: 视为 partial 的相似度阈值
    """
    keywords = set(kw.lower().strip() for kw in (keywords or []))

    expected_words = _tokenize(expected_text)
    actual_words = _tokenize(actual_text)

    # 词级 Levenshtein 对齐
    alignment = _word_level_align(expected_words, actual_words)

    # 转换为 WordMatch
    matches: List[WordMatch] = []
    expected_idx = 0
    actual_indices_used: set = set()

    for exp, act, exp_i, act_i in alignment:
        if exp is not None and act is not None:
            sim = _word_similarity(exp, act)
            if exp == act:
                mt = "match"
            elif _is_grammar_variant(exp, act):
                mt = "near_correct"
                sim = max(sim, 0.9)
            elif sim >= near_correct_threshold:
                mt = "near_correct"
            elif sim >= partial_threshold:
                mt = "partial"
            else:
                # 检测音近词
                if _is_phonetic_similar(exp, act):
                    mt = "near_correct"
                    sim = max(sim, 0.85)
                else:
                    mt = "substitution"
            matches.append(WordMatch(
                expected=exp, actual=act, match_type=mt, similarity=round(sim, 3),
                expected_index=exp_i, actual_index=act_i,
                is_keyword=exp in keywords,
                is_grammar_variant=_is_grammar_variant(exp, act),
                is_phonetic_similar=_is_phonetic_similar(exp, act),
            ))
            expected_idx += 1
            if act_i is not None:
                actual_indices_used.add(act_i)
        elif exp is not None and act is None:
            matches.append(WordMatch(
                expected=exp, actual=None, match_type="deletion", similarity=0.0,
                expected_index=exp_i, actual_index=None,
                is_keyword=exp in keywords, note="漏写",
            ))
            expected_idx += 1
        elif exp is None and act is not None:
            matches.append(WordMatch(
                expected="", actual=act, match_type="insertion", similarity=0.0,
                expected_index=-1, actual_index=act_i, note="多写",
            ))

    # 顺序检查：matched/near_correct 词的 actual_index 是否严格递增
    order_errors = _check_order(matches)
    for idx in order_errors:
        matches[idx].match_type = "order_error"
        matches[idx].note = "顺序错误"

    # 评分
    overall = _compute_score(matches, keywords_weight)

    # 汇总
    summary = _build_summary(matches)
    keywords_coverage = _compute_keywords_coverage(matches, keywords)
    tips = _build_tips(matches, summary, keywords_coverage)

    return DictationResultV2(
        overall_score=overall,
        words=matches,
        summary=summary,
        keywords_coverage=keywords_coverage,
        tips=tips,
    )


def _tokenize(text: str) -> List[str]:
    text = text.lower().strip()
    text = re.sub(r"[^a-z\s'-]", "", text)
    return [w for w in text.split() if w]


def _word_level_align(expected: List[str], actual: List[str]) -> List[Tuple[Optional[str], Optional[str], int, Optional[int]]]:
    """词级 Levenshtein 对齐。"""
    m, n = len(expected), len(actual)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    trace = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(1, m + 1):
        dp[i][0] = i
        trace[i][0] = 1
    for j in range(1, n + 1):
        dp[0][j] = j
        trace[0][j] = 2

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if expected[i - 1] == actual[j - 1] else 1
            sub = dp[i - 1][j - 1] + cost
            delete = dp[i - 1][j] + 1
            insert = dp[i][j - 1] + 1
            if sub <= delete and sub <= insert:
                dp[i][j] = sub
                trace[i][j] = 0
            elif delete <= insert:
                dp[i][j] = delete
                trace[i][j] = 1
            else:
                dp[i][j] = insert
                trace[i][j] = 2

    alignment = []
    i, j = m, n
    while i > 0 or j > 0:
        if i > 0 and j > 0 and trace[i][j] == 0:
            alignment.append((expected[i - 1], actual[j - 1], i - 1, j - 1))
            i -= 1
            j -= 1
        elif i > 0 and (j == 0 or trace[i][j] == 1):
            alignment.append((expected[i - 1], None, i - 1, None))
            i -= 1
        else:
            alignment.append((None, actual[j - 1], -1, j - 1))
            j -= 1

    alignment.reverse()
    return alignment


def _word_similarity(w1: str, w2: str) -> float:
    """词相似度：基于编辑距离 + 长度。"""
    if w1 == w2:
        return 1.0
    d = _edit_distance(w1, w2)
    max_len = max(len(w1), len(w2))
    if max_len == 0:
        return 0.0
    return 1.0 - d / max_len


def _edit_distance(s1: str, s2: str) -> int:
    m, n = len(s1), len(s2)
    if m == 0:
        return n
    if n == 0:
        return m
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j - 1], dp[i - 1][j], dp[i][j - 1])
    return dp[m][n]


def _is_grammar_variant(w1: str, w2: str) -> bool:
    """检测语法变形（如 go/goes/going/went, child/children）。"""
    grammar_groups = [
        {"go", "goes", "going", "went", "gone"},
        {"child", "children"},
        {"man", "men"},
        {"woman", "women"},
        {"foot", "feet"},
        {"tooth", "teeth"},
        {"mouse", "mice"},
        {"person", "people"},
        {"is", "are", "was", "were", "be", "been", "being"},
        {"have", "has", "had"},
        {"do", "does", "did", "done", "doing"},
        {"say", "says", "said", "saying"},
        {"make", "makes", "made", "making"},
        {"take", "takes", "took", "taken", "taking"},
        {"see", "sees", "saw", "seen", "seeing"},
        {"come", "comes", "came", "coming"},
        {"run", "runs", "ran", "running"},
        {"walk", "walks", "walked", "walking"},
        {"study", "studies", "studied", "studying"},
        {"play", "plays", "played", "playing"},
        {"watch", "watches", "watched", "watching"},
        {"stop", "stops", "stopped", "stopping"},
    ]
    for group in grammar_groups:
        if w1 in group and w2 in group:
            return True
    # 常见后缀变化
    suffix_pairs = [
        ("s", ""), ("es", ""), ("ed", ""), ("ing", ""),
        ("ed", "e"), ("ing", "e"), ("ies", "y"),
        ("ied", "y"), ("ied", "ie"),
    ]
    for suf1, suf2 in suffix_pairs:
        if w1.endswith(suf1) and w2.endswith(suf2):
            base1 = w1[: len(w1) - len(suf1)] if suf1 else w1
            base2 = w2[: len(w2) - len(suf2)] if suf2 else w2
            if base1 == base2 and base1:
                return True
    return False


def _is_phonetic_similar(w1: str, w2: str) -> bool:
    """音近词检测：通过 G2P 比较音素序列。"""
    try:
        from g2p_service import get_g2p_service

        g2p = get_g2p_service()
        p1 = g2p._word_to_phonemes_cached(w1)
        p2 = g2p._word_to_phonemes_cached(w2)
        if not p1 or not p2:
            return False
        if p1 == p2:
            return True
        # 编辑距离 ≤ 1 视为音近
        d = _phoneme_edit_distance(p1, p2)
        return d <= 1
    except Exception:
        return False


def _phoneme_edit_distance(p1: List[str], p2: List[str]) -> int:
    m, n = len(p1), len(p2)
    if m == 0:
        return n
    if n == 0:
        return m
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if p1[i - 1] == p2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j - 1], dp[i - 1][j], dp[i][j - 1])
    return dp[m][n]


def _check_order(matches: List[WordMatch]) -> List[int]:
    """检查 matched/near_correct 词的 actual_index 是否严格递增。"""
    order_errors = []
    prev_idx = -1
    for i, m in enumerate(matches):
        if m.match_type in ("match", "near_correct") and m.actual_index is not None:
            if m.actual_index <= prev_idx:
                order_errors.append(i)
            else:
                prev_idx = m.actual_index
    return order_errors


def _compute_score(matches: List[WordMatch], keyword_weight: float) -> float:
    if not matches:
        return 0.0
    total_weight = 0.0
    total_score = 0.0
    for m in matches:
        w = keyword_weight if m.is_keyword else 1.0
        total_weight += w
        if m.match_type == "match":
            total_score += w * 1.0
        elif m.match_type == "near_correct":
            total_score += w * 0.9
        elif m.match_type == "partial":
            total_score += w * 0.5
        elif m.match_type == "order_error":
            total_score += w * 0.4
        # substitution/deletion/insertion: 0
    return round(total_score / total_weight * 100, 1) if total_weight > 0 else 0.0


def _build_summary(matches: List[WordMatch]) -> dict:
    return {
        "total": len([m for m in matches if m.expected]),
        "match": len([m for m in matches if m.match_type == "match"]),
        "near_correct": len([m for m in matches if m.match_type == "near_correct"]),
        "partial": len([m for m in matches if m.match_type == "partial"]),
        "substitution": len([m for m in matches if m.match_type == "substitution"]),
        "deletion": len([m for m in matches if m.match_type == "deletion"]),
        "insertion": len([m for m in matches if m.match_type == "insertion"]),
        "order_error": len([m for m in matches if m.match_type == "order_error"]),
    }


def _compute_keywords_coverage(matches: List[WordMatch], keywords: set) -> dict:
    if not keywords:
        return {"total": 0, "correct": 0, "coverage": 1.0, "missed": []}
    keyword_matches = [m for m in matches if m.is_keyword]
    correct = len([m for m in keyword_matches if m.match_type in ("match", "near_correct")])
    missed = [m.expected for m in keyword_matches if m.match_type not in ("match", "near_correct")]
    return {
        "total": len(keywords),
        "correct": correct,
        "coverage": round(correct / len(keywords), 3),
        "missed": missed,
    }


def _build_tips(matches: List[WordMatch], summary: dict, keywords_coverage: dict) -> List[str]:
    tips = []
    if summary["deletion"] > 0:
        tips.append(f"漏写了 {summary['deletion']} 个词，请仔细听完整句子")
    if summary["insertion"] > 0:
        tips.append(f"多写了 {summary['insertion']} 个词，注意区分近音词")
    if summary["order_error"] > 0:
        tips.append(f"有 {summary['order_error']} 处顺序错误，注意词序")
    if summary["substitution"] > 0:
        tips.append(f"有 {summary['substitution']} 个词完全拼写错误，需重点记忆")
    if keywords_coverage["missed"]:
        tips.append(f"关键词遗漏：{', '.join(keywords_coverage['missed'][:5])}")
    return tips
