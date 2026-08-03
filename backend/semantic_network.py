"""
Phonos 语义场词汇网络 + 认知最优学习路径 + 探索-利用权衡

功能概述：
1. 语义场词汇网络（Semantic Network）
   - 基于语义场理论构建词汇关系图
   - 四种关系类型：共现(COOCCURRENCE)、语义相似(SEMANTIC_SIMILARITY)、
     组合关系(SYNTAGMATIC)、聚合关系(PARADIGMATIC)
   - PMI式搭配强度计算
   - 从 sentences.json + dict/endict/common.json 自动构建

2. 认知最优学习路径（Cognitive-Optimal Learning Path）
   - 语义启动(Semantic Priming)：相关词汇一起学习，扩散激活
   - 干扰最小化(Interference Minimization)：避免同时学习过多相似词
   - 渐进复杂度(Progressive Complexity)：高频词优先于低频词

3. 探索-利用权衡（Exploration-Exploitation Tradeoff）
   - UCB1启发式评分：score = expected_value + c * sqrt(ln(total_reviews) / card_reviews)
   - 自动调节探索率：高保持率(>85%)增加探索，低保持率(<60%)增加利用

4. 语义场覆盖度（Semantic Field Coverage）
   - 基于句子类别定义语义场：daily, greeting, travel, ordering 等
   - 追踪用户各语义场的学习覆盖度
   - 识别未探索的语义场

数据来源：
- sentences.json：句子语料，提取共现关系和语义场
- dict/endict/common.json：5万高频词，提供词频和词性数据

优雅降级：如果数据文件不存在，模块仍可正常工作（空网络）。

持久化：SQLite 数据库（phonos_semantic.db）
"""

import sqlite3
import json
import math
import time
import re
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Set
from collections import defaultdict
from itertools import combinations

# ============================================================
# 日志配置
# ============================================================
logger = logging.getLogger("semantic_network")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[语义网络] %(message)s"))
    logger.addHandler(handler)

# ============================================================
# 路径常量
# ============================================================
_BACKEND_DIR = Path(__file__).parent
DB_PATH = _BACKEND_DIR / "phonos_semantic.db"
SENTENCES_PATH = _BACKEND_DIR / "sentences.json"
COMMON_DICT_PATH = _BACKEND_DIR / "dict" / "endict" / "common.json"
LEARNING_DB_PATH = _BACKEND_DIR / "phonos_learning.db"
FSRS_DB_PATH = _BACKEND_DIR / "phonos_fsrs.db"

# ============================================================
# 关系类型常量
# ============================================================
REL_COOCCURRENCE = "COOCCURRENCE"           # 共现关系：同一句子中出现的词汇搭配
REL_SEMANTIC_SIMILARITY = "SEMANTIC_SIMILARITY"  # 语义相似：相似音素模式或词典分类
REL_SYNTAGMATIC = "SYNTAGMATIC"             # 组合关系：相同语法位置（动词-动词，名词-名词）
REL_PARADIGMATIC = "PARADIGMATIC"            # 聚合关系：可互相替换的同义词

ALL_RELATION_TYPES = [REL_COOCCURRENCE, REL_SEMANTIC_SIMILARITY, REL_SYNTAGMATIC, REL_PARADIGMATIC]

# ============================================================
# 停用词（英语常见功能词，不参与语义网络构建）
# ============================================================
STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "because", "but", "and", "or", "if", "while", "although", "though",
    "that", "which", "who", "whom", "this", "these", "those", "it", "its",
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you",
    "your", "yours", "yourself", "yourselves", "he", "him", "his",
    "himself", "she", "her", "hers", "herself", "they", "them", "their",
    "theirs", "themselves", "what", "up", "about", "also",
})

# ============================================================
# 词性分类映射（从 common.json 的 pos 字段提取主要词性）
# ============================================================
def _extract_pos_tag(pos_str: str) -> str:
    """
    从 common.json 的 pos 字段提取主要词性标签。
    pos 格式如 "n:4 v:96" 表示名词4% 动词96%，取最高比例的词性。

    返回: 'n'(名词), 'v'(动词), 'j'(形容词), 'r'(副词), 'p'(介词), 'c'(连词) 等
    """
    if not pos_str:
        return ""
    best_tag = ""
    best_ratio = -1
    for part in pos_str.strip().split():
        if ":" in part:
            tag, ratio_str = part.split(":", 1)
            try:
                ratio = int(ratio_str)
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_tag = tag
            except ValueError:
                continue
    return best_tag


# 词性大类映射
POS_CATEGORIES = {
    "n": "noun", "v": "verb", "j": "adjective", "r": "adverb",
    "p": "preposition", "c": "conjunction", "u": "pronoun",
    "i": "interjection", "d": "determiner", "m": "number",
}


def _pos_to_category(pos_tag: str) -> str:
    """将词性标签映射为大类名称"""
    return POS_CATEGORIES.get(pos_tag, "other")


# ============================================================
# 辅助函数
# ============================================================
def _tokenize(text: str) -> List[str]:
    """
    将英文句子分词并清理。
    - 转小写
    - 移除标点
    - 过滤停用词
    - 过滤过短的词
    """
    words = re.findall(r"[a-zA-Z'-]+", text.lower())
    return [w for w in words if w not in STOP_WORDS and len(w) > 1]


def _normalize_word(word: str) -> str:
    """标准化词汇：小写、去标点"""
    return re.sub(r"[^a-z'-]", "", word.lower()).strip("'-")


# ============================================================
# SemanticNetwork 主类
# ============================================================
class SemanticNetwork:
    """
    语义场词汇网络

    核心功能：
    - 从语料和词典数据构建词汇关系网络
    - 基于语义场理论组织词汇
    - 认知最优学习路径推荐
    - 探索-利用权衡的下一卡片选择
    - 语义场覆盖度追踪
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self._network_built = False
        self._word_freq_cache: Dict[str, float] = {}  # word -> frequency (0~1)
        self._word_pos_cache: Dict[str, str] = {}      # word -> pos category
        self._phoneme_cache: Dict[str, str] = {}       # word -> ipa_us
        self._init_db()

    # ================================================================
    # 数据库初始化
    # ================================================================
    def _init_db(self):
        """初始化 SQLite 数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS word_relations (
                word1 TEXT NOT NULL,
                word2 TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                strength REAL NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                updated_at REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (word1, word2, relation_type)
            );

            CREATE INDEX IF NOT EXISTS idx_word1 ON word_relations(word1);
            CREATE INDEX IF NOT EXISTS idx_word2 ON word_relations(word2);
            CREATE INDEX IF NOT EXISTS idx_relation_type ON word_relations(relation_type);
            CREATE INDEX IF NOT EXISTS idx_strength ON word_relations(strength);

            CREATE TABLE IF NOT EXISTS semantic_fields (
                field_name TEXT NOT NULL PRIMARY KEY,
                words_json TEXT NOT NULL DEFAULT '[]',
                updated_at REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS user_field_coverage (
                user_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                total_words INTEGER NOT NULL DEFAULT 0,
                learned_words INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, field_name)
            );

            CREATE INDEX IF NOT EXISTS idx_ufc_user ON user_field_coverage(user_id);

            CREATE TABLE IF NOT EXISTS exploration_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                card_id TEXT NOT NULL,
                card_type TEXT NOT NULL DEFAULT 'word',
                exploration_score REAL NOT NULL DEFAULT 0,
                was_exploration INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_explore_user ON exploration_log(user_id);
            CREATE INDEX IF NOT EXISTS idx_explore_time ON exploration_log(created_at);
            CREATE INDEX IF NOT EXISTS idx_explore_type ON exploration_log(card_type);
        """)
        conn.commit()
        conn.close()

    # ================================================================
    # 数据加载
    # ================================================================
    def _load_sentences(self) -> List[dict]:
        """加载句子数据，优雅降级"""
        if not SENTENCES_PATH.exists():
            logger.info("未找到 sentences.json，跳过语料加载")
            return []
        try:
            with open(SENTENCES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"加载 {len(data)} 条句子数据")
            return data
        except Exception as e:
            logger.warning(f"加载 sentences.json 失败: {e}")
            return []

    def _load_common_dict(self) -> dict:
        """加载高频词词典，优雅降级"""
        if not COMMON_DICT_PATH.exists():
            logger.info("未找到 common.json，跳过词典加载")
            return {}
        try:
            with open(COMMON_DICT_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"加载 {len(data)} 个词典词条")
            return data
        except Exception as e:
            logger.warning(f"加载 common.json 失败: {e}")
            return {}

    # ================================================================
    # 网络构建
    # ================================================================
    def build_network(self):
        """
        从数据源重建语义网络

        步骤：
        1. 加载 sentences.json 和 common.json
        2. 构建共现关系（COOCCURRENCE）
        3. 构建语义相似关系（SEMANTIC_SIMILARITY）
        4. 构建组合关系（SYNTAGMATIC）
        5. 构建聚合关系（PARADIGMATIC）
        6. 构建语义场
        7. 持久化到数据库
        """
        logger.info("开始构建语义网络...")

        sentences = self._load_sentences()
        common_dict = self._load_common_dict()

        # 预处理词典数据，缓存词频和词性
        self._build_dict_caches(common_dict)

        # 清空旧数据
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM word_relations")
        conn.execute("DELETE FROM semantic_fields")
        conn.commit()

        # 构建各种关系
        cooccurrence_pairs = self._build_cooccurrence_relations(sentences)
        semantic_pairs = self._build_semantic_similarity_relations(common_dict)
        syntagmatic_pairs = self._build_syntagmatic_relations(sentences)
        paradigmatic_pairs = self._build_paradigmatic_relations(common_dict)

        # 批量写入关系
        now = time.time()
        all_relations = []
        all_relations.extend(cooccurrence_pairs)
        all_relations.extend(semantic_pairs)
        all_relations.extend(syntagmatic_pairs)
        all_relations.extend(paradigmatic_pairs)

        # 写入数据库（确保 word1 < word2 以避免重复）
        batch = []
        for word1, word2, rel_type, strength, metadata in all_relations:
            w1, w2 = sorted([word1, word2])
            batch.append((w1, w2, rel_type, strength, json.dumps(metadata, ensure_ascii=False), now))

        conn.executemany(
            """INSERT OR REPLACE INTO word_relations
            (word1, word2, relation_type, strength, metadata_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            batch
        )
        conn.commit()

        # 构建语义场
        self._build_semantic_fields(sentences, common_dict, conn)

        conn.close()

        self._network_built = True
        total = len(batch)
        logger.info(
            f"语义网络构建完成: {total} 条关系 "
            f"(共现:{len(cooccurrence_pairs)} 语义相似:{len(semantic_pairs)} "
            f"组合:{len(syntagmatic_pairs)} 聚合:{len(paradigmatic_pairs)})"
        )

    def _build_dict_caches(self, common_dict: dict):
        """从词典数据构建词频和词性缓存"""
        if not common_dict:
            return

        # 词典的 key 顺序大致反映词频（靠前的更常用）
        total_words = len(common_dict)
        for idx, (word, entry) in enumerate(common_dict.items()):
            # 词频：基于在词典中的排序位置（越靠前越常用）
            freq = 1.0 - (idx / total_words) if total_words > 0 else 0.5
            self._word_freq_cache[word.lower()] = freq

            # 词性
            pos_str = entry.get("pos", "")
            pos_tag = _extract_pos_tag(pos_str)
            self._word_pos_cache[word.lower()] = _pos_to_category(pos_tag)

            # 音标
            ipa = entry.get("ipa_us", "")
            if ipa:
                self._phoneme_cache[word.lower()] = ipa

    def _build_cooccurrence_relations(self, sentences: List[dict]) -> List[Tuple]:
        """
        构建共现关系（COOCCURRENCE）

        算法：
        1. 从每个句子中提取有效词汇对
        2. 统计每对词的共现次数
        3. 计算类似 PMI 的搭配强度：
           strength = cooc_count / total_sentences_containing_either
           （简化版 PMI，值域 [0, 1]）
        """
        if not sentences:
            return []

        # 统计每个词出现在哪些句子中
        word_sentences: Dict[str, Set[int]] = defaultdict(set)
        # 统计每对词的共现次数
        pair_cooc: Dict[Tuple[str, str], int] = defaultdict(int)
        # 每个句子的词汇集合
        sentence_words: Dict[int, Set[str]] = {}

        for sent in sentences:
            sid = sent.get("id", 0)
            text = sent.get("text", "")
            words = set(_tokenize(text))
            sentence_words[sid] = words

            for w in words:
                word_sentences[w].add(sid)

            # 提取所有词汇对
            for w1, w2 in combinations(sorted(words), 2):
                pair_cooc[(w1, w2)] += 1

        # 计算搭配强度
        total_sentences = len(sentences)
        relations = []

        for (w1, w2), cooc_count in pair_cooc.items():
            if cooc_count < 1:
                continue

            # 两个词各自出现的句子数
            s1 = len(word_sentences.get(w1, set()))
            s2 = len(word_sentences.get(w2, set()))

            # 包含 w1 或 w2 的句子总数
            union_count = len(word_sentences.get(w1, set()) | word_sentences.get(w2, set()))

            if union_count == 0:
                continue

            # 搭配强度 = 共现次数 / 包含任一词的句子数
            # 类似于条件概率 P(w1,w2 | w1 or w2)
            strength = cooc_count / union_count

            # PMI 式增强：如果共现频率远超随机期望，给额外加分
            # P(w1) * P(w2) 是随机共现的期望
            expected = (s1 / total_sentences) * (s2 / total_sentences)
            actual = cooc_count / total_sentences

            if expected > 0 and actual > 0:
                pmi = math.log(actual / expected + 1e-10)
                # PMI 范围大约 [-∞, +∞]，映射到 [0, 1] 的加分项
                pmi_bonus = 1.0 / (1.0 + math.exp(-pmi))  # sigmoid
                # 综合强度：条件概率 * 0.6 + PMI加分 * 0.4
                strength = 0.6 * strength + 0.4 * pmi_bonus

            # 过滤极弱关系
            if strength < 0.01:
                continue

            # 限制最大强度为 1.0
            strength = min(strength, 1.0)

            metadata = {
                "cooc_count": cooc_count,
                "sentences_w1": s1,
                "sentences_w2": s2,
                "union_count": union_count,
            }

            relations.append((w1, w2, REL_COOCCURRENCE, round(strength, 4), metadata))

        return relations

    def _build_semantic_similarity_relations(self, common_dict: dict) -> List[Tuple]:
        """
        构成语义相似关系（SEMANTIC_SIMILARITY）

        基于两种特征：
        1. 音素模式相似：IPA 音标有共同前缀或后缀（如 read/feed, light/night）
        2. 词典分类相似：同一词性大类的词

        注意：不穷举所有词对（O(n²)太大），而是抽样高频词构建
        """
        if not common_dict:
            return []

        relations = []
        # 取高频词子集（前3000词），避免 O(n²) 爆炸
        high_freq_words = list(common_dict.keys())[:3000]

        # 按 IPA 音标前缀分组（取前2个音素作为前缀）
        ipa_groups: Dict[str, List[str]] = defaultdict(list)
        for word in high_freq_words:
            ipa = self._phoneme_cache.get(word.lower(), "")
            if ipa:
                # 提取前缀（去掉重音标记，取前2个音素字符段）
                clean_ipa = re.sub(r"[ˈˌː.]", "", ipa)
                prefix = clean_ipa[:3] if len(clean_ipa) >= 3 else clean_ipa
                if prefix:
                    ipa_groups[prefix].append(word.lower())

        # 在音素前缀组内构建相似关系
        for prefix, words in ipa_groups.items():
            if len(words) < 2:
                continue
            # 组内两两配对（限制每对词最多10个关系）
            for w1, w2 in combinations(sorted(words), 2):
                if w1 == w2:
                    continue
                # 计算音素相似度：共享前缀越长越相似
                ipa1 = self._phoneme_cache.get(w1, "")
                ipa2 = self._phoneme_cache.get(w2, "")
                sim = self._ipa_similarity(ipa1, ipa2)

                if sim >= 0.3:
                    metadata = {"ipa1": ipa1, "ipa2": ipa2, "similarity_type": "phoneme"}
                    relations.append((w1, w2, REL_SEMANTIC_SIMILARITY, round(sim, 4), metadata))

        # 按词性大类分组，同词性的词建立弱相似关系
        pos_groups: Dict[str, List[str]] = defaultdict(list)
        for word in high_freq_words:
            cat = self._word_pos_cache.get(word.lower(), "")
            if cat:
                pos_groups[cat].append(word.lower())

        for cat, words in pos_groups.items():
            if len(words) < 2 or cat == "other":
                continue
            # 每个词性大类取前50个高频词两两配对
            top_words = sorted(words, key=lambda w: self._word_freq_cache.get(w, 0), reverse=True)[:50]
            for w1, w2 in combinations(sorted(top_words), 2):
                if w1 == w2:
                    continue
                strength = 0.15  # 同词性基础相似度
                # 如果词频接近，增强
                f1 = self._word_freq_cache.get(w1, 0.5)
                f2 = self._word_freq_cache.get(w2, 0.5)
                freq_sim = 1.0 - abs(f1 - f2)
                strength *= freq_sim

                if strength >= 0.05:
                    metadata = {"pos_category": cat, "similarity_type": "pos_category"}
                    relations.append((w1, w2, REL_SEMANTIC_SIMILARITY, round(strength, 4), metadata))

        return relations

    def _ipa_similarity(self, ipa1: str, ipa2: str) -> float:
        """
        计算两个 IPA 音标的相似度

        基于最长公共前缀占比
        """
        if not ipa1 or not ipa2:
            return 0.0

        # 清理重音标记
        c1 = re.sub(r"[ˈˌː.]", "", ipa1)
        c2 = re.sub(r"[ˈˌː.]", "", ipa2)

        if not c1 or not c2:
            return 0.0

        # 计算最长公共前缀
        common_len = 0
        for ch1, ch2 in zip(c1, c2):
            if ch1 == ch2:
                common_len += 1
            else:
                break

        # 相似度 = 公共前缀长度 / 较长音标长度
        max_len = max(len(c1), len(c2))
        return common_len / max_len if max_len > 0 else 0.0

    def _build_syntagmatic_relations(self, sentences: List[dict]) -> List[Tuple]:
        """
        构建组合关系（SYNTAGMATIC）

        基于语法位置相似性：
        - 在不同句子中出现在相同位置的词（如都是第1个实词 = 主语位置）
        - 简化实现：按词在句子中的位置分桶，同位置词建立关系
        """
        if not sentences:
            return []

        # 按位置分桶：position -> [words]
        position_buckets: Dict[int, List[str]] = defaultdict(list)

        for sent in sentences:
            text = sent.get("text", "")
            words = _tokenize(text)
            for pos, word in enumerate(words):
                # 将位置标准化为前/中/后三段
                if len(words) <= 3:
                    norm_pos = pos
                else:
                    third = len(words) // 3
                    if pos < third:
                        norm_pos = 0  # 前
                    elif pos < 2 * third:
                        norm_pos = 1  # 中
                    else:
                        norm_pos = 2  # 后

                position_buckets[norm_pos].append(word)

        relations = []
        for pos, words in position_buckets.items():
            if len(words) < 2:
                continue

            # 统计同位置词的共现频率
            word_counts: Dict[str, int] = defaultdict(int)
            for w in words:
                word_counts[w] += 1

            # 只取出现2次以上的词
            frequent_words = {w for w, c in word_counts.items() if c >= 2}

            # 同位置的词两两建立组合关系
            sorted_words = sorted(frequent_words)
            for w1, w2 in combinations(sorted_words, 2):
                c1 = word_counts[w1]
                c2 = word_counts[w2]
                # 强度基于两个词在该位置出现的频率
                strength = min(c1, c2) / max(c1, c2) * 0.3  # 归一化到 [0, 0.3]

                if strength >= 0.05:
                    pos_label = {0: "sentence_start", 1: "sentence_middle", 2: "sentence_end"}.get(pos, f"pos_{pos}")
                    metadata = {"position": pos, "position_label": pos_label}
                    relations.append((w1, w2, REL_SYNTAGMATIC, round(strength, 4), metadata))

        return relations

    def _build_paradigmatic_relations(self, common_dict: dict) -> List[Tuple]:
        """
        构建聚合关系（PARADIGMATIC）

        基于可替换性：
        1. 同一词性且意义相近的词（从 meaning 字段提取关键词）
        2. 词典的 exchange 字段（词形变化：go/went, big/bigger）
        3. 同义词：共享相同中文释义关键词的词
        """
        if not common_dict:
            return []

        relations = []

        # 方法1：从 exchange 字段提取词形变化关系
        for word, entry in list(common_dict.items())[:3000]:
            exchanges = entry.get("exchange", [])
            if not exchanges:
                continue

            for ex in exchanges:
                # exchange 格式如 "d:abandoned", "p:abandoned", "s:abandons"
                if ":" not in ex:
                    continue
                prefix, related_form = ex.split(":", 1)
                related_form = related_form.lower().strip()

                if not related_form or related_form == word.lower():
                    continue

                # 不同类型的词形变化给予不同强度
                strength_map = {
                    "d": 0.9,   # 过去式/过去分词（高度相关）
                    "p": 0.9,   # 过去分词
                    "i": 0.85,  # 现在分词
                    "3": 0.85,  # 第三人称单数
                    "s": 0.8,   # 复数
                    "r": 0.7,   # 比较级
                    "t": 0.7,   # 最高级
                }
                strength = strength_map.get(prefix, 0.5)

                metadata = {"exchange_type": prefix, "type_label": {
                    "d": "past_tense", "p": "past_participle",
                    "i": "present_participle", "3": "third_person",
                    "s": "plural", "r": "comparative", "t": "superlative",
                }.get(prefix, "inflection")}

                relations.append((word.lower(), related_form, REL_PARADIGMATIC, round(strength, 4), metadata))

        # 方法2：基于中文释义关键词构建同义词关系
        # 提取每个词的释义关键词
        meaning_keywords: Dict[str, Set[str]] = {}
        for word, entry in list(common_dict.items())[:3000]:
            meaning = entry.get("meaning", "")
            # 提取中文关键词（去掉词性标注和括号内容）
            keywords = set()
            for line in meaning.split("\n"):
                # 去掉英文词性标注如 "vt.", "n.", "a."
                cleaned = re.sub(r"^[a-z]+\.\s*", "", line.strip())
                # 去掉括号内容
                cleaned = re.sub(r"[（(].*?[）)]", "", cleaned)
                # 按逗号、顿号分割
                for kw in re.split(r"[,，、；;]", cleaned):
                    kw = kw.strip()
                    if kw and len(kw) >= 2:
                        keywords.add(kw)
            if keywords:
                meaning_keywords[word.lower()] = keywords

        # 找共享关键词的词对（限制：只比较高频词）
        keyword_to_words: Dict[str, List[str]] = defaultdict(list)
        for word, kws in meaning_keywords.items():
            for kw in kws:
                keyword_to_words[kw].append(word)

        # 对每个关键词，其关联的词互为同义/近义
        synonym_count = 0
        for kw, words in keyword_to_words.items():
            if len(words) < 2 or len(words) > 20:  # 跳过过于宽泛的关键词
                continue
            sorted_words = sorted(words)
            for w1, w2 in combinations(sorted_words, 2):
                if w1 == w2:
                    continue
                # 共享关键词数量决定强度
                shared = len(meaning_keywords.get(w1, set()) & meaning_keywords.get(w2, set()))
                strength = min(0.1 * shared, 0.8)  # 每个共享关键词 +0.1，上限 0.8

                if strength >= 0.1:
                    metadata = {"shared_keywords": shared, "similarity_type": "synonym"}
                    relations.append((w1, w2, REL_PARADIGMATIC, round(strength, 4), metadata))
                    synonym_count += 1

        logger.info(f"聚合关系: {len(relations)} 条 (词形变化 + 同义词:{synonym_count})")
        return relations

    def _build_semantic_fields(self, sentences: List[dict], common_dict: dict, conn: sqlite3.Connection):
        """
        构建语义场（Semantic Fields）

        基于句子类别（category）分组，提取每个类别的词汇集。
        同时从词典中按词义关键词补充语义场词汇。
        """
        now = time.time()

        # 从句子类别提取语义场
        field_words: Dict[str, Set[str]] = defaultdict(set)

        for sent in sentences:
            category = sent.get("category", "uncategorized")
            text = sent.get("text", "")
            words = _tokenize(text)
            field_words[category].update(words)

        # 从词典中补充每个语义场的词汇
        # 基于句子中已知的类别词汇，查找词典中有相似释义的词
        if common_dict:
            category_keywords = {
                "daily": {"日常", "生活", "每天", "日常的"},
                "greeting": {"问候", "打招呼", "你好", "欢迎"},
                "travel": {"旅行", "旅游", "出行", "风景"},
                "ordering": {"点餐", "订单", "菜单", "咖啡"},
                "food": {"食物", "饮食", "餐厅", "美味"},
                "education": {"教育", "学习", "学生", "学校", "大学"},
                "business": {"商业", "公司", "经济", "投资"},
                "technology": {"技术", "科技", "电脑", "网络", "互联网"},
                "health": {"健康", "医疗", "医生", "疾病"},
                "environment": {"环境", "气候", "生态", "污染"},
                "culture": {"文化", "传统", "艺术", "文明"},
                "society": {"社会", "公共", "社区", "公民"},
                "career": {"职业", "工作", "事业", "职位"},
                "politics": {"政治", "政府", "政策", "法律"},
                "science": {"科学", "研究", "实验", "理论"},
                "news": {"新闻", "报道", "事件", "调查"},
                "psychology": {"心理", "情绪", "认知", "行为"},
                "hobby": {"爱好", "兴趣", "娱乐", "休闲"},
                "communication": {"沟通", "交流", "表达", "对话"},
                "inspiration": {"激励", "梦想", "奋斗", "坚持"},
                "literature": {"文学", "小说", "诗歌", "作品"},
                "academic": {"学术", "论文", "研究", "教授"},
                "history": {"历史", "古代", "文明", "传统"},
                "mystery": {"神秘", "谜团", "未解"},
                "tongue_twister": {"绕口令", "发音", "练习"},
            }

            for word, entry in list(common_dict.items())[:5000]:
                meaning = entry.get("meaning", "")
                for field, keywords in category_keywords.items():
                    for kw in keywords:
                        if kw in meaning:
                            field_words[field].add(word.lower())
                            break

        # 写入数据库
        for field_name, words in field_words.items():
            words_list = sorted(words)
            conn.execute(
                """INSERT OR REPLACE INTO semantic_fields (field_name, words_json, updated_at)
                VALUES (?, ?, ?)""",
                (field_name, json.dumps(words_list, ensure_ascii=False), now)
            )

        conn.commit()
        logger.info(f"构建 {len(field_words)} 个语义场")

    # ================================================================
    # 查询接口 - 语义网络
    # ================================================================
    def get_word_network(self, word: str, depth: int = 1) -> dict:
        """
        获取词汇的网络关系

        参数:
            word: 目标词汇
            depth: 关系深度（1=直接关系，2=二跳关系）

        返回: {word, relations: [{word, type, strength}]}
        """
        word = _normalize_word(word)
        if not word:
            return {"word": word, "relations": []}

        conn = sqlite3.connect(self.db_path)

        # 第一层：直接关系
        direct_relations = []
        rows = conn.execute(
            """SELECT word2, relation_type, strength FROM word_relations WHERE word1 = ?
            UNION ALL
            SELECT word1, relation_type, strength FROM word_relations WHERE word2 = ?
            ORDER BY strength DESC""",
            (word, word)
        ).fetchall()

        visited = {word}
        for row in rows:
            related_word, rel_type, strength = row
            if related_word not in visited:
                direct_relations.append({
                    "word": related_word,
                    "type": rel_type,
                    "strength": strength,
                })
                visited.add(related_word)

        result_relations = list(direct_relations)

        # 第二层：如果 depth >= 2，递归获取
        if depth >= 2:
            second_hop = []
            for rel in direct_relations[:20]:  # 限制展开节点数
                related = rel["word"]
                rows2 = conn.execute(
                    """SELECT word2, relation_type, strength FROM word_relations WHERE word1 = ?
                    UNION ALL
                    SELECT word1, relation_type, strength FROM word_relations WHERE word2 = ?
                    ORDER BY strength DESC LIMIT 5""",
                    (related, related)
                ).fetchall()
                for row in rows2:
                    w2, rt2, s2 = row
                    if w2 not in visited:
                        second_hop.append({
                            "word": w2,
                            "type": rt2,
                            "strength": s2 * rel["strength"],  # 衰减
                            "via": related,
                        })
                        visited.add(w2)

            result_relations.extend(second_hop)

        conn.close()

        return {"word": word, "relations": result_relations}

    def get_related_words(self, word: str, relation_type: str = None, limit: int = 10) -> list:
        """
        获取相关词汇列表

        参数:
            word: 目标词汇
            relation_type: 关系类型过滤（None=所有类型）
            limit: 返回数量上限

        返回: [{word, type, strength}]
        """
        word = _normalize_word(word)
        if not word:
            return []

        conn = sqlite3.connect(self.db_path)

        if relation_type:
            rows = conn.execute(
                """SELECT word2, relation_type, strength FROM word_relations
                WHERE word1 = ? AND relation_type = ?
                UNION ALL
                SELECT word1, relation_type, strength FROM word_relations
                WHERE word2 = ? AND relation_type = ?
                ORDER BY strength DESC LIMIT ?""",
                (word, relation_type, word, relation_type, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT word2, relation_type, strength FROM word_relations WHERE word1 = ?
                UNION ALL
                SELECT word1, relation_type, strength FROM word_relations WHERE word2 = ?
                ORDER BY strength DESC LIMIT ?""",
                (word, word, limit)
            ).fetchall()

        conn.close()

        return [{"word": r[0], "type": r[1], "strength": r[2]} for r in rows]

    def get_collocations(self, word: str, min_strength: float = 0.1) -> List[Tuple[str, float]]:
        """
        获取词汇的搭配词（共现关系）

        参数:
            word: 目标词汇
            min_strength: 最低搭配强度阈值

        返回: [(word, strength)] 按强度降序排列
        """
        word = _normalize_word(word)
        if not word:
            return []

        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """SELECT word2, strength FROM word_relations
            WHERE word1 = ? AND relation_type = ? AND strength >= ?
            UNION ALL
            SELECT word1, strength FROM word_relations
            WHERE word2 = ? AND relation_type = ? AND strength >= ?
            ORDER BY strength DESC""",
            (word, REL_COOCCURRENCE, min_strength,
             word, REL_COOCCURRENCE, min_strength)
        ).fetchall()
        conn.close()

        return [(r[0], r[1]) for r in rows]

    def get_word_frequency(self, word: str) -> float:
        """获取词汇频率（0~1，越高越常用）"""
        word = _normalize_word(word)
        return self._word_freq_cache.get(word, 0.5)

    # ================================================================
    # 认知最优学习路径
    # ================================================================
    def get_optimal_path(self, user_id: str, target_words: List[str] = None) -> List[str]:
        """
        生成认知最优学习路径

        原则：
        1. 语义启动(Semantic Priming)：相关词汇一起学习
        2. 干扰最小化(Interference Minimization)：避免同时学过多相似词
        3. 渐进复杂度(Progressive Complexity)：高频词优先

        算法：
        1. 获取用户已掌握的词汇集
        2. 过滤掉已掌握的词
        3. 按语义场聚类
        4. 在每个语义场内按词频排序
        5. 语义场间交替（避免连续学同一领域），优先选择与已掌握词关联度高的场

        参数:
            user_id: 用户ID
            target_words: 目标词汇列表（None=所有未掌握词）

        返回: 排序后的词汇列表
        """
        # 获取用户已掌握的词
        mastered_words = self._get_mastered_words(user_id)

        # 确定待学习词集
        if target_words:
            candidates = [_normalize_word(w) for w in target_words]
        else:
            # 从语义场中获取所有词
            candidates = self._get_all_field_words()

        # 过滤已掌握词
        candidates = [w for w in candidates if w not in mastered_words and w]

        if not candidates:
            return []

        # 按语义场分组
        word_to_field = self._map_words_to_fields(candidates)
        field_to_words: Dict[str, List[str]] = defaultdict(list)
        for word, field in word_to_field.items():
            field_to_words[field].append(word)

        # 每个语义场内按词频排序（高频优先）
        for field in field_to_words:
            field_to_words[field].sort(
                key=lambda w: self._word_freq_cache.get(w, 0.5),
                reverse=True
            )

        # 语义场间交替排序
        # 优先级：与已掌握词关联度高的语义场优先
        field_priority = self._compute_field_priority(field_to_words.keys(), mastered_words)

        result = []
        field_queues = {f: list(words) for f, words in field_to_words.items()}
        # 按优先级排序的语义场列表
        sorted_fields = sorted(field_priority.keys(), key=lambda f: field_priority[f], reverse=True)

        # 轮流从各语义场取词
        round_robin_idx = 0
        max_iterations = len(candidates) * 2  # 防止死循环
        iteration = 0

        while any(field_queues.values()) and iteration < max_iterations:
            iteration += 1
            # 按轮转顺序选择语义场
            active_fields = [f for f in sorted_fields if field_queues.get(f)]
            if not active_fields:
                break

            # 轮转 + 优先级混合：80% 按优先级，20% 轮转
            if iteration % 5 == 0 and len(active_fields) > 1:
                # 轮转探索
                field = active_fields[round_robin_idx % len(active_fields)]
                round_robin_idx += 1
            else:
                # 优先级选择
                field = active_fields[0]

            word = field_queues[field].pop(0)

            # 干扰最小化：如果最近3个词与当前词太相似，跳过
            if self._would_cause_interference(word, result[-3:] if len(result) >= 3 else result):
                # 放回队列末尾
                field_queues[field].append(word)
                # 尝试下一个语义场
                if len(active_fields) > 1:
                    alt_field = active_fields[1] if active_fields[1] != field else active_fields[-1]
                    if field_queues.get(alt_field):
                        word = field_queues[alt_field].pop(0)
                        result.append(word)
                        continue
                # 如果只有一个语义场，直接加入
                result.append(word)
            else:
                result.append(word)

        return result

    def _get_mastered_words(self, user_id: str) -> Set[str]:
        """从 learning_algorithm 数据库获取用户已掌握的词"""
        mastered = set()
        try:
            if LEARNING_DB_PATH.exists():
                conn = sqlite3.connect(str(LEARNING_DB_PATH))
                rows = conn.execute(
                    "SELECT word FROM user_word_progress WHERE user_id = ? AND mastered = 1",
                    (user_id,)
                ).fetchall()
                conn.close()
                mastered = {r[0] for r in rows}
        except Exception as e:
            logger.debug(f"获取已掌握词汇失败: {e}")
        return mastered

    def _get_user_word_progress(self, user_id: str) -> Dict[str, dict]:
        """获取用户所有词汇进度"""
        progress = {}
        try:
            if LEARNING_DB_PATH.exists():
                conn = sqlite3.connect(str(LEARNING_DB_PATH))
                rows = conn.execute(
                    "SELECT word, attempts, best_score, avg_score, mastered FROM user_word_progress WHERE user_id = ?",
                    (user_id,)
                ).fetchall()
                conn.close()
                for r in rows:
                    progress[r[0]] = {
                        "word": r[0],
                        "attempts": r[1],
                        "best_score": r[2],
                        "avg_score": r[3],
                        "mastered": bool(r[4]),
                    }
        except Exception as e:
            logger.debug(f"获取词汇进度失败: {e}")
        return progress

    def _get_all_field_words(self) -> List[str]:
        """获取所有语义场中的词汇"""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT words_json FROM semantic_fields").fetchall()
        conn.close()

        all_words = set()
        for row in rows:
            words = json.loads(row[0])
            all_words.update(words)

        return sorted(all_words)

    def _map_words_to_fields(self, words: List[str]) -> Dict[str, str]:
        """将词汇映射到其主要所属的语义场"""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT field_name, words_json FROM semantic_fields").fetchall()
        conn.close()

        field_word_sets: Dict[str, Set[str]] = {}
        for field_name, words_json in rows:
            field_words = set(json.loads(words_json))
            field_word_sets[field_name] = field_words

        word_to_field = {}
        for word in words:
            for field_name, field_words in field_word_sets.items():
                if word in field_words:
                    word_to_field[word] = field_name
                    break
            else:
                word_to_field[word] = "uncategorized"

        return word_to_field

    def _compute_field_priority(self, fields, mastered_words: Set[str]) -> Dict[str, float]:
        """
        计算语义场优先级

        与已掌握词关联度高的语义场优先（语义启动效应）
        """
        if not mastered_words:
            # 没有已掌握词时，优先日常/问候等基础场
            base_priority = {
                "daily": 1.0, "greeting": 0.95, "ordering": 0.85,
                "food": 0.8, "travel": 0.75, "hobby": 0.7,
                "education": 0.65, "communication": 0.6,
            }
            return {f: base_priority.get(f, 0.5) for f in fields}

        conn = sqlite3.connect(self.db_path)
        priorities = {}

        for field in fields:
            # 统计该语义场中有多少词与已掌握词有直接关系
            field_words_rows = conn.execute(
                "SELECT words_json FROM semantic_fields WHERE field_name = ?", (field,)
            ).fetchone()

            if not field_words_rows:
                priorities[field] = 0.5
                continue

            field_words = set(json.loads(field_words_rows[0]))
            # 与已掌握词的交集
            overlap = field_words & mastered_words
            # 关联度 = 交集比例
            connection_ratio = len(overlap) / len(field_words) if field_words else 0

            # 有较多已掌握词的语义场优先（扩散激活）
            priorities[field] = connection_ratio

        conn.close()
        return priorities

    def _would_cause_interference(self, word: str, recent_words: List[str]) -> bool:
        """
        判断学习该词是否会造成干扰

        如果最近学习的词与当前词过于相似（同词性 + 同语义场），
        可能造成前摄抑制/倒摄抑制，应避免连续学习。
        """
        if not recent_words:
            return False

        conn = sqlite3.connect(self.db_path)

        # 检查与最近3个词的语义相似度
        similar_count = 0
        for recent in recent_words:
            # 查询直接关系
            row = conn.execute(
                """SELECT strength FROM word_relations
                WHERE ((word1 = ? AND word2 = ?) OR (word1 = ? AND word2 = ?))
                AND relation_type IN (?, ?)
                ORDER BY strength DESC LIMIT 1""",
                (word, recent, recent, word,
                 REL_SEMANTIC_SIMILARITY, REL_PARADIGMATIC)
            ).fetchone()

            if row and row[0] >= 0.5:
                similar_count += 1

        conn.close()

        # 如果2个以上最近词与当前词高度相似，判定为干扰
        return similar_count >= 2

    # ================================================================
    # 探索-利用权衡
    # ================================================================
    def get_next_card_explore_exploit(self, user_id: str, card_type: str = "word") -> dict:
        """
        基于探索-利用权衡选择下一张卡片

        UCB1启发式评分：
        score = expected_value + c * sqrt(ln(total_reviews) / card_reviews)

        - expected_value：卡片的预期价值（基于历史表现和语义关联）
        - c：探索参数（默认0.3，可配置）
        - total_reviews：用户总复习次数
        - card_reviews：该卡片被复习的次数

        利用(EXPLOITATION)：到期复习卡片，强化已知词
        探索(EXPLORATION)：引入新语义场，发现弱连接

        参数:
            user_id: 用户ID
            card_type: 卡片类型（'word' 或 'sentence'）

        返回: {
            card_id, card_type, exploration_score,
            was_exploration, reason, suggested_action
        }
        """
        # 自动调节探索参数
        c = self._auto_adjust_exploration_param(user_id)

        # 获取用户统计数据
        total_reviews = self._get_total_reviews(user_id)
        word_progress = self._get_user_word_progress(user_id)
        mastered_words = {w for w, p in word_progress.items() if p["mastered"]}

        # 获取候选卡片
        candidates = self._get_card_candidates(user_id, card_type, word_progress, mastered_words)

        if not candidates:
            return {
                "card_id": None,
                "card_type": card_type,
                "exploration_score": 0,
                "was_exploration": False,
                "reason": "no_candidates",
                "suggested_action": "所有词汇已掌握或无可学习内容",
            }

        # 为每个候选计算 UCB1 分数
        scored_candidates = []
        for candidate in candidates:
            card_id = candidate["card_id"]

            # 预期价值（exploitation部分）
            expected_value = candidate.get("expected_value", 0.5)

            # 该卡片的复习次数
            card_reviews = candidate.get("review_count", 0)

            # UCB1 探索加分
            if total_reviews > 0 and card_reviews > 0:
                exploration_bonus = c * math.sqrt(math.log(total_reviews) / card_reviews)
            else:
                # 未复习过的卡片给予最大探索加分
                exploration_bonus = c * math.sqrt(math.log(max(total_reviews, 1)))

            ucb1_score = expected_value + exploration_bonus

            # 语义场覆盖度加分：未探索领域的词额外加分
            field_coverage_bonus = self._get_field_coverage_bonus(user_id, card_id)
            ucb1_score += field_coverage_bonus * 0.2

            is_exploration = exploration_bonus > expected_value

            scored_candidates.append({
                "card_id": card_id,
                "card_type": card_type,
                "expected_value": round(expected_value, 4),
                "exploration_bonus": round(exploration_bonus, 4),
                "field_coverage_bonus": round(field_coverage_bonus, 4),
                "exploration_score": round(ucb1_score, 4),
                "was_exploration": is_exploration,
                "reason": "exploration" if is_exploration else "exploitation",
                "suggested_action": candidate.get("suggested_action", ""),
            })

        # 选择最高分的卡片
        scored_candidates.sort(key=lambda x: x["exploration_score"], reverse=True)
        best = scored_candidates[0]

        # 记录探索日志
        self._log_exploration(
            user_id, best["card_id"], card_type,
            best["exploration_score"], best["was_exploration"]
        )

        return best

    def _auto_adjust_exploration_param(self, user_id: str) -> float:
        """
        自动调节探索参数 c

        - 用户保持率 > 85%：增加探索（c = 0.5）
        - 用户保持率 < 60%：增加利用（c = 0.1）
        - 其他：默认（c = 0.3）
        """
        retention = self._get_user_retention(user_id)

        if retention > 0.85:
            return 0.5  # 高保持率，增加探索
        elif retention < 0.60:
            return 0.1  # 低保持率，增加利用
        else:
            # 线性插值
            return 0.1 + (retention - 0.60) / (0.85 - 0.60) * 0.4

    def _get_user_retention(self, user_id: str) -> float:
        """
        计算用户的保持率

        基于已学习词汇的平均得分
        """
        progress = self._get_user_word_progress(user_id)
        if not progress:
            return 0.5  # 默认值

        # 只看有尝试记录的词
        attempted = {w: p for w, p in progress.items() if p["attempts"] > 0}
        if not attempted:
            return 0.5

        avg_score = sum(p["avg_score"] for p in attempted.values()) / len(attempted)
        return avg_score / 100.0  # 归一化到 [0, 1]

    def _get_total_reviews(self, user_id: str) -> int:
        """获取用户总复习次数"""
        total = 0
        try:
            # 从 learning_algorithm 数据库
            if LEARNING_DB_PATH.exists():
                conn = sqlite3.connect(str(LEARNING_DB_PATH))
                row = conn.execute(
                    "SELECT COUNT(*) FROM user_evaluations WHERE user_id = ?",
                    (user_id,)
                ).fetchone()
                total += row[0] if row else 0
                conn.close()

            # 从 fsrs 数据库
            if FSRS_DB_PATH.exists():
                conn = sqlite3.connect(str(FSRS_DB_PATH))
                row = conn.execute(
                    "SELECT COUNT(*) FROM review_log WHERE user_id = ?",
                    (user_id,)
                ).fetchone()
                total += row[0] if row else 0
                conn.close()
        except Exception as e:
            logger.debug(f"获取总复习次数失败: {e}")

        return total

    def _get_card_candidates(
        self, user_id: str, card_type: str,
        word_progress: Dict[str, dict], mastered_words: Set[str]
    ) -> List[dict]:
        """获取候选卡片列表，计算预期价值"""
        candidates = []

        # 1. 到期复习的卡片（利用）
        due_cards = self._get_due_cards(user_id, card_type)
        for card in due_cards:
            word = card.get("word", card.get("card_id", ""))
            # 预期价值基于历史表现
            prog = word_progress.get(word.lower(), {})
            ev = prog.get("avg_score", 50) / 100.0 if prog else 0.5
            review_count = prog.get("attempts", 0)

            candidates.append({
                "card_id": card.get("card_id", word),
                "expected_value": max(ev, 0.3),  # 最低0.3，确保复习卡有基本价值
                "review_count": review_count,
                "suggested_action": "review",
            })

        # 2. 新词（探索）
        all_field_words = self._get_all_field_words()
        unexplored_fields = self.get_unexplored_fields(user_id)

        for word in all_field_words:
            if word in mastered_words:
                continue
            if word.lower() in word_progress:
                continue  # 已学过但未掌握的词走复习路径

            # 新词的预期价值基于词频（高频词更有价值）
            freq = self._word_freq_cache.get(word, 0.5)
            # 所在语义场的覆盖度越低，探索价值越高
            word_field = self._map_words_to_fields([word]).get(word, "uncategorized")
            field_coverage = self._get_single_field_coverage(user_id, word_field)

            # 新词预期价值 = 词频 * (1 - 场覆盖度) + 基础值
            ev = freq * (1 - field_coverage) * 0.5 + 0.3

            candidates.append({
                "card_id": word,
                "expected_value": ev,
                "review_count": 0,
                "suggested_action": "learn_new",
            })

        return candidates

    def _get_due_cards(self, user_id: str, card_type: str) -> List[dict]:
        """获取到期复习卡片"""
        due_cards = []
        try:
            if FSRS_DB_PATH.exists():
                conn = sqlite3.connect(str(FSRS_DB_PATH))
                now = time.time()
                if card_type == "word":
                    rows = conn.execute(
                        """SELECT card_id, word FROM cards
                        WHERE user_id = ? AND card_type = 'word'
                        AND state != 0 AND due <= ? AND suspended = 0
                        ORDER BY due ASC LIMIT 20""",
                        (user_id, now)
                    ).fetchall()
                    for r in rows:
                        due_cards.append({"card_id": r[0], "word": r[1] or r[0]})
                else:
                    rows = conn.execute(
                        """SELECT card_id FROM cards
                        WHERE user_id = ? AND card_type = ? AND state != 0
                        AND due <= ? AND suspended = 0
                        ORDER BY due ASC LIMIT 20""",
                        (user_id, card_type, now)
                    ).fetchall()
                    for r in rows:
                        due_cards.append({"card_id": r[0]})
                conn.close()
        except Exception as e:
            logger.debug(f"获取到期卡片失败: {e}")

        return due_cards

    def _get_field_coverage_bonus(self, user_id: str, card_id: str) -> float:
        """获取语义场覆盖度探索加分"""
        word = _normalize_word(card_id)
        word_field = self._map_words_to_fields([word]).get(word, "uncategorized")
        coverage = self._get_single_field_coverage(user_id, word_field)
        # 覆盖度越低，加分越高
        return 1.0 - coverage

    def _get_single_field_coverage(self, user_id: str, field_name: str) -> float:
        """获取单个语义场的覆盖度"""
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT total_words, learned_words FROM user_field_coverage WHERE user_id = ? AND field_name = ?",
            (user_id, field_name)
        ).fetchone()
        conn.close()

        if row and row[0] > 0:
            return row[1] / row[0]
        return 0.0

    def _log_exploration(
        self, user_id: str, card_id: str, card_type: str,
        exploration_score: float, was_exploration: bool
    ):
        """记录探索日志"""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO exploration_log
            (user_id, card_id, card_type, exploration_score, was_exploration, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, card_id, card_type, exploration_score, int(was_exploration), time.time())
        )
        conn.commit()
        conn.close()

    def get_exploration_stats(self, user_id: str) -> dict:
        """
        获取用户的探索-利用统计

        返回: {
            exploitation_ratio: float,     # 利用比例
            exploration_ratio: float,      # 探索比例
            coverage_by_field: [{field, total_words, learned_words, coverage_ratio}],
            total_reviews: int,
            exploration_c: float,          # 当前探索参数
            retention: float,              # 保持率
        }
        """
        conn = sqlite3.connect(self.db_path)

        # 统计探索/利用比例
        total_log = conn.execute(
            "SELECT COUNT(*) FROM exploration_log WHERE user_id = ?",
            (user_id,)
        ).fetchone()[0]

        exploration_count = conn.execute(
            "SELECT COUNT(*) FROM exploration_log WHERE user_id = ? AND was_exploration = 1",
            (user_id,)
        ).fetchone()[0]

        if total_log > 0:
            exploration_ratio = exploration_count / total_log
        else:
            exploration_ratio = 0.5  # 默认50:50

        conn.close()

        # 语义场覆盖度
        coverage_by_field = self.get_field_coverage(user_id)

        # 当前参数
        c = self._auto_adjust_exploration_param(user_id)
        retention = self._get_user_retention(user_id)
        total_reviews = self._get_total_reviews(user_id)

        return {
            "exploitation_ratio": round(1.0 - exploration_ratio, 4),
            "exploration_ratio": round(exploration_ratio, 4),
            "coverage_by_field": coverage_by_field,
            "total_reviews": total_reviews,
            "exploration_c": round(c, 4),
            "retention": round(retention, 4),
        }

    # ================================================================
    # 语义场覆盖度
    # ================================================================
    def get_field_coverage(self, user_id: str) -> List[dict]:
        """
        获取用户的语义场覆盖度

        返回: [{field, total_words, learned_words, coverage_ratio}]
        """
        # 先更新覆盖度数据
        self._update_field_coverage(user_id)

        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT field_name, total_words, learned_words FROM user_field_coverage WHERE user_id = ?",
            (user_id,)
        ).fetchall()
        conn.close()

        result = []
        for field_name, total, learned in rows:
            ratio = learned / total if total > 0 else 0
            result.append({
                "field": field_name,
                "total_words": total,
                "learned_words": learned,
                "coverage_ratio": round(ratio, 4),
            })

        return sorted(result, key=lambda x: x["coverage_ratio"])

    def get_unexplored_fields(self, user_id: str, threshold: float = 0.3) -> List[str]:
        """
        获取未充分探索的语义场（覆盖度 < threshold）

        参数:
            user_id: 用户ID
            threshold: 覆盖度阈值（默认0.3，即30%）

        返回: [field_name] 按覆盖度升序排列
        """
        coverage = self.get_field_coverage(user_id)
        unexplored = [
            item["field"] for item in coverage
            if item["coverage_ratio"] < threshold
        ]
        return unexplored

    def _update_field_coverage(self, user_id: str):
        """更新用户语义场覆盖度数据"""
        mastered_words = self._get_mastered_words(user_id)
        if not mastered_words and not self._has_any_progress(user_id):
            # 没有任何学习记录的新用户，初始化所有语义场
            self._init_field_coverage_for_new_user(user_id)
            return

        conn = sqlite3.connect(self.db_path)
        now = time.time()

        # 获取所有语义场
        fields = conn.execute("SELECT field_name, words_json FROM semantic_fields").fetchall()

        for field_name, words_json in fields:
            field_words = set(json.loads(words_json))
            total = len(field_words)
            learned = len(field_words & mastered_words)

            conn.execute(
                """INSERT OR REPLACE INTO user_field_coverage
                (user_id, field_name, total_words, learned_words, updated_at)
                VALUES (?, ?, ?, ?, ?)""",
                (user_id, field_name, total, learned, now)
            )

        conn.commit()
        conn.close()

    def _has_any_progress(self, user_id: str) -> bool:
        """检查用户是否有任何学习记录"""
        try:
            if LEARNING_DB_PATH.exists():
                conn = sqlite3.connect(str(LEARNING_DB_PATH))
                row = conn.execute(
                    "SELECT COUNT(*) FROM user_word_progress WHERE user_id = ?",
                    (user_id,)
                ).fetchone()
                conn.close()
                return row[0] > 0
        except Exception:
            pass
        return False

    def _init_field_coverage_for_new_user(self, user_id: str):
        """为新用户初始化语义场覆盖度"""
        conn = sqlite3.connect(self.db_path)
        now = time.time()

        fields = conn.execute("SELECT field_name, words_json FROM semantic_fields").fetchall()
        for field_name, words_json in fields:
            field_words = set(json.loads(words_json))
            conn.execute(
                """INSERT OR REPLACE INTO user_field_coverage
                (user_id, field_name, total_words, learned_words, updated_at)
                VALUES (?, ?, ?, 0, ?)""",
                (user_id, field_name, len(field_words), now)
            )

        conn.commit()
        conn.close()

    # ================================================================
    # 辅助查询
    # ================================================================
    def get_network_stats(self) -> dict:
        """获取语义网络统计信息"""
        conn = sqlite3.connect(self.db_path)

        total_relations = conn.execute("SELECT COUNT(*) FROM word_relations").fetchone()[0]
        total_fields = conn.execute("SELECT COUNT(*) FROM semantic_fields").fetchone()[0]

        # 各类型关系数量
        type_counts = {}
        for rel_type in ALL_RELATION_TYPES:
            count = conn.execute(
                "SELECT COUNT(*) FROM word_relations WHERE relation_type = ?",
                (rel_type,)
            ).fetchone()[0]
            type_counts[rel_type] = count

        # 不重复词汇数
        unique_words = conn.execute(
            "SELECT COUNT(DISTINCT w) FROM (SELECT word1 as w FROM word_relations UNION ALL SELECT word2 as w FROM word_relations)"
        ).fetchone()[0]

        # 平均关系强度
        avg_strength = conn.execute("SELECT AVG(strength) FROM word_relations").fetchone()[0] or 0

        conn.close()

        return {
            "total_relations": total_relations,
            "total_fields": total_fields,
            "unique_words": unique_words,
            "avg_strength": round(avg_strength, 4),
            "type_counts": type_counts,
        }

    def get_semantic_fields_info(self) -> List[dict]:
        """获取所有语义场信息"""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT field_name, words_json, updated_at FROM semantic_fields ORDER BY field_name"
        ).fetchall()
        conn.close()

        result = []
        for field_name, words_json, updated_at in rows:
            words = json.loads(words_json)
            result.append({
                "field": field_name,
                "word_count": len(words),
                "top_words": words[:10],  # 前10个词
                "updated_at": updated_at,
            })
        return result

    def search_words_by_field(self, field_name: str) -> List[str]:
        """搜索指定语义场的所有词汇"""
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT words_json FROM semantic_fields WHERE field_name = ?",
            (field_name,)
        ).fetchone()
        conn.close()

        if row:
            return json.loads(row[0])
        return []

    def ensure_network_built(self):
        """确保语义网络已构建（懒加载）"""
        if not self._network_built:
            # 检查数据库中是否已有数据
            conn = sqlite3.connect(self.db_path)
            count = conn.execute("SELECT COUNT(*) FROM word_relations").fetchone()[0]
            conn.close()

            if count == 0:
                logger.info("语义网络为空，开始构建...")
                self.build_network()
            else:
                self._network_built = True
                logger.info(f"语义网络已存在（{count} 条关系），跳过构建")

                # 重新加载词典缓存（用于词频查询等）
                common_dict = self._load_common_dict()
                self._build_dict_caches(common_dict)


# ============================================================
# 全局单例
# ============================================================
_instance: Optional[SemanticNetwork] = None


def get_semantic_network() -> SemanticNetwork:
    """
    获取语义网络全局单例

    首次调用时自动构建网络（如果数据库为空）。
    后续调用返回同一实例。
    """
    global _instance
    if _instance is None:
        _instance = SemanticNetwork()
        _instance.ensure_network_built()
    return _instance


# ============================================================
# 快速测试入口
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=" * 60)
    print("Phonos 语义网络模块测试")
    print("=" * 60)

    sn = get_semantic_network()

    # 统计信息
    stats = sn.get_network_stats()
    print(f"\n📊 网络统计:")
    print(f"  总关系数: {stats['total_relations']}")
    print(f"  不重复词汇: {stats['unique_words']}")
    print(f"  语义场数: {stats['total_fields']}")
    print(f"  平均关系强度: {stats['avg_strength']}")
    for rt, cnt in stats['type_counts'].items():
        print(f"  {rt}: {cnt}")

    # 语义场信息
    print(f"\n📂 语义场:")
    fields = sn.get_semantic_fields_info()
    for f in fields[:10]:
        print(f"  {f['field']}: {f['word_count']} 词 (Top: {', '.join(f['top_words'][:5])})")

    # 词汇网络查询
    print(f"\n🔗 'weather' 的网络关系:")
    network = sn.get_word_network("weather", depth=1)
    for rel in network["relations"][:5]:
        print(f"  → {rel['word']} [{rel['type']}] strength={rel['strength']}")

    # 搭配词查询
    print(f"\n🤝 'beautiful' 的搭配词:")
    collocations = sn.get_collocations("beautiful")
    for word, strength in collocations[:5]:
        print(f"  → {word} (strength={strength})")

    # 相关词查询
    print(f"\n📎 'coffee' 的相关词:")
    related = sn.get_related_words("coffee", limit=5)
    for r in related:
        print(f"  → {r['word']} [{r['type']}] strength={r['strength']}")

    # 学习路径
    print(f"\n🛤️ 学习路径（测试用户）:")
    path = sn.get_optimal_path("test_user", target_words=[
        "weather", "coffee", "beautiful", "government", "education",
        "restaurant", "morning", "delicious", "reading", "park"
    ])
    print(f"  → {' → '.join(path)}")

    # 探索-利用
    print(f"\n⚖️ 探索-利用（测试用户）:")
    next_card = sn.get_next_card_explore_exploit("test_user", "word")
    print(f"  卡片: {next_card['card_id']}")
    print(f"  类型: {next_card['reason']}")
    print(f"  探索分: {next_card['exploration_score']}")

    # 探索统计
    explore_stats = sn.get_exploration_stats("test_user")
    print(f"\n📈 探索统计:")
    print(f"  利用比例: {explore_stats['exploitation_ratio']}")
    print(f"  探索比例: {explore_stats['exploration_ratio']}")
    print(f"  探索参数c: {explore_stats['exploration_c']}")
    print(f"  保持率: {explore_stats['retention']}")

    # 语义场覆盖度
    print(f"\n📊 语义场覆盖度:")
    coverage = sn.get_field_coverage("test_user")
    for c in coverage[:5]:
        print(f"  {c['field']}: {c['learned_words']}/{c['total_words']} ({c['coverage_ratio']:.1%})")

    # 未探索语义场
    unexplored = sn.get_unexplored_fields("test_user")
    print(f"\n🗺️ 未充分探索的语义场: {unexplored}")

    print(f"\n{'=' * 60}")
    print("测试完成!")
