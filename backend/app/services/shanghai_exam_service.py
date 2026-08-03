"""上海听说考试模块 - 任务类型定义、计时、报告、语料管理。

任务类型（9 种）：
1. word_reading - 单词朗读
2. sentence_reading - 句子朗读
3. dictation - 听写
4. listening_choice - 听句子选择
5. question_answer - 听问题回答
6. information_completion - 信息补全
7. information_retelling - 信息转述
8. situational_response - 情景应答
9. picture_description - 看图说话
10. mock_exam - 模拟套卷

合规声明：
- 所有报告必须标注"辅助评估"、"非官方成绩"、"建议结合教师反馈"
- 不得声称与上海教育考试院有任何关联
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class TaskType(str, Enum):
    WORD_READING = "word_reading"
    SENTENCE_READING = "sentence_reading"
    DICTATION = "dictation"
    LISTENING_CHOICE = "listening_choice"
    QUESTION_ANSWER = "question_answer"
    INFORMATION_COMPLETION = "information_completion"
    INFORMATION_RETELLING = "information_retelling"
    SITUATIONAL_RESPONSE = "situational_response"
    PICTURE_DESCRIPTION = "picture_description"
    MOCK_EXAM = "mock_exam"


class ExamMode(str, Enum):
    PRACTICE = "practice"  # 练习模式：可暂停、可重做
    EXAM = "exam"  # 考试模式：严格计时、自动提交


@dataclass
class TaskTiming:
    """任务计时配置。"""
    preparation_sec: int  # 准备时间
    response_sec: int  # 答题时间
    auto_play_audio: bool = True  # 自动播放音频
    auto_record_after_audio: bool = True  # 音频播放完自动开始录音
    allow_replay: bool = True  # 练习模式允许重听
    replay_count_limit: int = 2  # 重听次数


# 上海听说考试各题型标准计时（参考公开考试大纲，单位秒）
TASK_TIMING_PRESETS: dict[TaskType, TaskTiming] = {
    TaskType.WORD_READING: TaskTiming(preparation_sec=10, response_sec=15),
    TaskType.SENTENCE_READING: TaskTiming(preparation_sec=15, response_sec=30),
    TaskType.DICTATION: TaskTiming(preparation_sec=20, response_sec=90, replay_count_limit=3),
    TaskType.LISTENING_CHOICE: TaskTiming(preparation_sec=5, response_sec=10),
    TaskType.QUESTION_ANSWER: TaskTiming(preparation_sec=10, response_sec=20),
    TaskType.INFORMATION_COMPLETION: TaskTiming(preparation_sec=20, response_sec=60),
    TaskType.INFORMATION_RETELLING: TaskTiming(preparation_sec=30, response_sec=60),
    TaskType.SITUATIONAL_RESPONSE: TaskTiming(preparation_sec=10, response_sec=20),
    TaskType.PICTURE_DESCRIPTION: TaskTiming(preparation_sec=30, response_sec=60),
    TaskType.MOCK_EXAM: TaskTiming(preparation_sec=0, response_sec=1800),  # 30 分钟
}


@dataclass
class ExamTask:
    """考试任务定义。"""
    id: str
    type: TaskType
    title: str
    prompt: str  # 题目文本
    audio_url: Optional[str] = None  # 听力音频
    image_urls: Optional[List[str]] = None  # 看图说话图片
    expected_answer: Optional[str] = None  # 标准答案（朗读/听写）
    keywords: Optional[List[str]] = None  # 关键词（用于评分）
    options: Optional[List[str]] = None  # 选项（选择题）
    correct_option: Optional[int] = None
    timing: Optional[TaskTiming] = None
    difficulty: str = "medium"  # easy/medium/hard
    topic: str = ""  # 话题
    cefr: str = ""  # A1/A2/B1/B2/C1/C2
    textbook_source: str = ""  # 教材来源
    skill_tags: List[str] = field(default_factory=list)  # 考试能力标签
    phoneme_coverage: List[str] = field(default_factory=list)  # 音素覆盖标签

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "type": self.type.value,
            "title": self.title,
            "prompt": self.prompt,
            "audio_url": self.audio_url,
            "image_urls": self.image_urls,
            "expected_answer": self.expected_answer,
            "keywords": self.keywords,
            "options": self.options,
            "correct_option": self.correct_option,
            "difficulty": self.difficulty,
            "topic": self.topic,
            "cefr": self.cefr,
            "textbook_source": self.textbook_source,
            "skill_tags": self.skill_tags,
            "phoneme_coverage": self.phoneme_coverage,
            "timing": None,
        }
        if self.timing:
            d["timing"] = {
                "preparation_sec": self.timing.preparation_sec,
                "response_sec": self.timing.response_sec,
                "auto_play_audio": self.timing.auto_play_audio,
                "auto_record_after_audio": self.timing.auto_record_after_audio,
                "allow_replay": self.timing.allow_replay,
                "replay_count_limit": self.timing.replay_count_limit,
            }
        return d


@dataclass
class ExamSession:
    """考试会话。"""
    id: str
    user_id: str
    mode: ExamMode
    tasks: List[ExamTask]
    current_task_index: int = 0
    started_at: float = 0
    finished_at: Optional[float] = None
    responses: List[dict] = field(default_factory=list)
    auto_submitted: bool = False


@dataclass
class ExamReport:
    """考试报告。"""
    session_id: str
    user_id: str
    mode: ExamMode
    started_at: float
    finished_at: float
    duration_sec: float
    task_results: List[dict]
    overall_score: float
    dimension_scores: dict
    strengths: List[str]
    weaknesses: List[str]
    suggestions: List[str]
    disclaimer: str  # 合规声明

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "mode": self.mode.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_sec": self.duration_sec,
            "task_results": self.task_results,
            "overall_score": self.overall_score,
            "dimension_scores": self.dimension_scores,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "suggestions": self.suggestions,
            "disclaimer": self.disclaimer,
        }


# 合规声明（所有报告必须包含）
DISCLAIMER = (
    "本报告由 Phonos 系统辅助评估生成，非官方成绩，仅供参考。"
    "评分基于本地 AI 模型，可能与人工评分存在偏差。建议结合教师反馈综合判断。"
    "Phonos 与上海市教育考试院无任何关联。"
)


# ============================================================
# 上海考试服务
# ============================================================
class ShanghaiExamService:
    """上海听说考试服务。"""

    def __init__(self):
        self._corpus: List[ExamTask] = []
        self._sessions: dict[str, ExamSession] = {}
        self._load_corpus()

    def _load_corpus(self) -> None:
        """加载语料库（从 shanghai_corpus/ 目录）。"""
        import json
        import os
        from pathlib import Path

        corpus_dir = Path(__file__).resolve().parents[2] / "shanghai_corpus"
        if not corpus_dir.is_dir():
            # 创建目录 + 示例语料
            corpus_dir.mkdir(parents=True, exist_ok=True)
            self._write_sample_corpus(corpus_dir)

        for json_file in corpus_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        task = self._parse_task(item)
                        if task:
                            self._corpus.append(task)
                elif isinstance(data, dict) and "tasks" in data:
                    for item in data["tasks"]:
                        task = self._parse_task(item)
                        if task:
                            self._corpus.append(task)
            except Exception as e:
                from ..core.logging import get_logger

                get_logger("shanghai_exam").warning(
                    "corpus_load_failed", file=str(json_file), error=str(e)
                )

    def _parse_task(self, item: dict) -> Optional[ExamTask]:
        try:
            task_type = TaskType(item.get("type", "sentence_reading"))
            timing_dict = item.get("timing") or {}
            timing = TASK_TIMING_PRESETS.get(task_type)
            if timing_dict:
                timing = TaskTiming(
                    preparation_sec=timing_dict.get("preparation_sec", timing.preparation_sec if timing else 15),
                    response_sec=timing_dict.get("response_sec", timing.response_sec if timing else 30),
                    auto_play_audio=timing_dict.get("auto_play_audio", True),
                    auto_record_after_audio=timing_dict.get("auto_record_after_audio", True),
                    allow_replay=timing_dict.get("allow_replay", True),
                    replay_count_limit=timing_dict.get("replay_count_limit", 2),
                )
            return ExamTask(
                id=item.get("id", ""),
                type=task_type,
                title=item.get("title", ""),
                prompt=item.get("prompt", ""),
                audio_url=item.get("audio_url"),
                image_urls=item.get("image_urls"),
                expected_answer=item.get("expected_answer"),
                keywords=item.get("keywords"),
                options=item.get("options"),
                correct_option=item.get("correct_option"),
                timing=timing,
                difficulty=item.get("difficulty", "medium"),
                topic=item.get("topic", ""),
                cefr=item.get("cefr", ""),
                textbook_source=item.get("textbook_source", ""),
                skill_tags=item.get("skill_tags", []),
                phoneme_coverage=item.get("phoneme_coverage", []),
            )
        except Exception:
            return None

    def _write_sample_corpus(self, corpus_dir: Path) -> None:
        """写入示例语料（覆盖 9 种任务类型）。"""
        sample = [
            {
                "id": "sr_001",
                "type": "sentence_reading",
                "title": "句子朗读 - 日常生活",
                "prompt": "Please read the following sentence aloud.",
                "expected_answer": "The weather is beautiful today, so I decide to go for a walk in the park.",
                "keywords": ["weather", "beautiful", "park"],
                "difficulty": "easy",
                "topic": "daily_life",
                "cefr": "A2",
                "textbook_source": "上海七年级英语",
                "skill_tags": ["pronunciation", "intonation"],
                "phoneme_coverage": ["TH", "DH", "ER", "AE"],
            },
            {
                "id": "wr_001",
                "type": "word_reading",
                "title": "单词朗读 - 高频词",
                "prompt": "Please read the following words aloud.",
                "expected_answer": "beautiful environment technology experience pronunciation",
                "difficulty": "medium",
                "topic": "vocabulary",
                "cefr": "B1",
                "skill_tags": ["pronunciation"],
                "phoneme_coverage": ["B", "F", "V", "TH"],
            },
            {
                "id": "dt_001",
                "type": "dictation",
                "title": "听写 - 校园生活",
                "prompt": "Listen carefully and write down what you hear.",
                "expected_answer": "My classmates and I are preparing for the English speech contest next week.",
                "keywords": ["classmates", "preparing", "speech", "contest"],
                "difficulty": "medium",
                "topic": "school_life",
                "cefr": "B1",
                "skill_tags": ["listening", "spelling"],
            },
            {
                "id": "lc_001",
                "type": "listening_choice",
                "title": "听句子选择",
                "prompt": "Listen and choose the best response.",
                "options": [
                    "I'm fine, thank you.",
                    "How do you do?",
                    "Nice to meet you.",
                    "See you later.",
                ],
                "correct_option": 1,
                "expected_answer": "How do you do?",
                "difficulty": "easy",
                "topic": "greeting",
                "cefr": "A2",
                "skill_tags": ["listening", "comprehension"],
            },
            {
                "id": "qa_001",
                "type": "question_answer",
                "title": "听问题回答",
                "prompt": "Listen to the question and give your answer.",
                "expected_answer": "I usually get up at six thirty in the morning.",
                "keywords": ["six", "thirty", "morning"],
                "difficulty": "medium",
                "topic": "daily_routine",
                "cefr": "A2",
                "skill_tags": ["listening", "speaking", "grammar"],
            },
            {
                "id": "ic_001",
                "type": "information_completion",
                "title": "信息补全",
                "prompt": "Listen to the dialogue and complete the notes.",
                "expected_answer": "The meeting will be held in Room 302 at 3 p.m. on Friday.",
                "keywords": ["Room 302", "3 p.m.", "Friday"],
                "difficulty": "hard",
                "topic": "school_activity",
                "cefr": "B1",
                "skill_tags": ["listening", "note_taking"],
            },
            {
                "id": "ir_001",
                "type": "information_retelling",
                "title": "信息转述",
                "prompt": "Listen to the story and retell it in your own words.",
                "expected_answer": "Last Sunday, Tom went to the library to borrow some books about history. He spent two hours there and finally found three books he needed for his research paper.",
                "keywords": ["Sunday", "library", "history", "two hours", "three books"],
                "difficulty": "hard",
                "topic": "narrative",
                "cefr": "B1",
                "skill_tags": ["listening", "speaking", "summary"],
            },
            {
                "id": "sr_002",
                "type": "situational_response",
                "title": "情景应答",
                "prompt": "Situation: Your friend invites you to a birthday party but you have an exam the next day. Respond appropriately.",
                "expected_answer": "Thank you for the invitation, but I'm afraid I can't come because I have an important exam tomorrow. Maybe we can celebrate together this weekend.",
                "keywords": ["thank", "exam", "weekend"],
                "difficulty": "hard",
                "topic": "social_interaction",
                "cefr": "B1",
                "skill_tags": ["speaking", "communication", "grammar"],
            },
            {
                "id": "pd_001",
                "type": "picture_description",
                "title": "看图说话",
                "prompt": "Look at the pictures and tell a story.",
                "image_urls": ["picture_001_a.jpg", "picture_001_b.jpg", "picture_001_c.jpg"],
                "expected_answer": "One morning, a boy was walking to school when he saw an old lady dropping her groceries. He helped her pick up the things and she thanked him. The boy felt happy and continued to school.",
                "keywords": ["morning", "walking", "school", "old lady", "helped", "happy"],
                "difficulty": "hard",
                "topic": "narrative",
                "cefr": "B1",
                "skill_tags": ["speaking", "narrative", "vocabulary"],
            },
        ]
        import json

        with open(corpus_dir / "sample_tasks.json", "w", encoding="utf-8") as f:
            json.dump(sample, f, ensure_ascii=False, indent=2)

    # ============================================================
    # 公共 API
    # ============================================================
    def list_task_types(self) -> List[dict]:
        return [
            {
                "type": t.value,
                "default_timing": {
                    "preparation_sec": TASK_TIMING_PRESETS[t].preparation_sec,
                    "response_sec": TASK_TIMING_PRESETS[t].response_sec,
                },
                "task_count": len([c for c in self._corpus if c.type == t]),
            }
            for t in TaskType
        ]

    def corpus_count(self) -> int:
        return len(self._corpus)

    def list_tasks(
        self,
        task_type: Optional[TaskType] = None,
        difficulty: Optional[str] = None,
        topic: Optional[str] = None,
        cefr: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        tasks = self._corpus
        if task_type:
            tasks = [t for t in tasks if t.type == task_type]
        if difficulty:
            tasks = [t for t in tasks if t.difficulty == difficulty]
        if topic:
            tasks = [t for t in tasks if t.topic == topic]
        if cefr:
            tasks = [t for t in tasks if t.cefr == cefr]
        return [t.to_dict() for t in tasks[:limit]]

    def get_task(self, task_id: str) -> Optional[dict]:
        for t in self._corpus:
            if t.id == task_id:
                return t.to_dict()
        return None

    def create_session(
        self,
        user_id: str,
        mode: ExamMode,
        task_ids: Optional[List[str]] = None,
        task_types: Optional[List[TaskType]] = None,
        task_count: int = 5,
    ) -> ExamSession:
        """创建考试会话。"""
        import time
        import uuid

        # 选择任务
        if task_ids:
            tasks = [t for t in self._corpus if t.id in task_ids]
        elif task_types:
            tasks = []
            for tt in task_types:
                tasks.extend([t for t in self._corpus if t.type == tt])
        else:
            # 随机抽题
            import random

            tasks = random.sample(self._corpus, min(task_count, len(self._corpus)))

        session = ExamSession(
            id=uuid.uuid4().hex[:16],
            user_id=user_id,
            mode=mode,
            tasks=tasks,
            started_at=time.time(),
        )
        self._sessions[session.id] = session
        return session

    def get_session(self, session_id: str) -> Optional[ExamSession]:
        return self._sessions.get(session_id)

    def submit_response(
        self,
        session_id: str,
        task_id: str,
        response: dict,
    ) -> dict:
        """提交单个任务作答。"""
        session = self._sessions.get(session_id)
        if not session:
            return {"error": "session_not_found"}
        session.responses.append({
            "task_id": task_id,
            "response": response,
            "submitted_at": time.time(),
        })
        return {"ok": True}

    def auto_submit_if_timeout(self, session_id: str) -> bool:
        """超时自动提交。"""
        import time

        from ..core.config import get_settings

        if not get_settings().shanghai_exam_auto_submit:
            return False
        session = self._sessions.get(session_id)
        if not session or session.finished_at:
            return False
        # 检查总时长
        total_sec = sum(t.timing.response_sec + t.timing.preparation_sec for t in session.tasks if t.timing)
        elapsed = time.time() - session.started_at
        if elapsed > total_sec + 60:  # 60s 缓冲
            session.finished_at = time.time()
            session.auto_submitted = True
            return True
        return False

    def generate_report(self, session_id: str) -> Optional[ExamReport]:
        """生成考试报告。"""
        import time

        session = self._sessions.get(session_id)
        if not session:
            return None

        # 简化：把所有作答的分数汇总（实际需调用评分引擎）
        task_results = []
        for resp in session.responses:
            task = next((t for t in session.tasks if t.id == resp["task_id"]), None)
            if not task:
                continue
            task_results.append({
                "task_id": task.id,
                "task_type": task.type.value,
                "title": task.title,
                "response": resp["response"],
                "score": resp["response"].get("score", 0),
                "feedback": resp["response"].get("feedback", ""),
            })

        scores = [r["score"] for r in task_results]
        overall = sum(scores) / len(scores) if scores else 0.0

        # 维度评分汇总
        dimension_scores = {
            "pronunciation": overall,
            "fluency": overall,
            "completeness": overall,
            "content_relevance": overall,
            "grammar_accuracy": overall,
            "time_management": 100.0 if not session.auto_submitted else 80.0,
        }

        strengths = [r["title"] for r in task_results if r["score"] >= 80]
        weaknesses = [r["title"] for r in task_results if r["score"] < 60]
        suggestions = self._build_suggestions(task_results, weaknesses)

        return ExamReport(
            session_id=session.id,
            user_id=session.user_id,
            mode=session.mode,
            started_at=session.started_at,
            finished_at=session.finished_at or time.time(),
            duration_sec=(session.finished_at or time.time()) - session.started_at,
            task_results=task_results,
            overall_score=round(overall, 1),
            dimension_scores={k: round(v, 1) for k, v in dimension_scores.items()},
            strengths=strengths,
            weaknesses=weaknesses,
            suggestions=suggestions,
            disclaimer=DISCLAIMER,
        )

    def _build_suggestions(self, task_results: List[dict], weaknesses: List[str]) -> List[str]:
        suggestions = []
        if weaknesses:
            suggestions.append(f"建议针对以下任务加强练习：{', '.join(weaknesses[:3])}")
        low_score_types = [r["task_type"] for r in task_results if r["score"] < 70]
        if low_score_types:
            type_counts = {}
            for t in low_score_types:
                type_counts[t] = type_counts.get(t, 0) + 1
            top_weak = sorted(type_counts.items(), key=lambda x: -x[1])[:2]
            for t, c in top_weak:
                suggestions.append(f"在 {t} 题型失分较多（{c} 次），建议专项训练")
        suggestions.append("建议结合教师反馈，针对性提升薄弱环节")
        return suggestions


_exam_instance: Optional[ShanghaiExamService] = None


def get_shanghai_exam_service() -> ShanghaiExamService:
    global _exam_instance
    if _exam_instance is None:
        _exam_instance = ShanghaiExamService()
    return _exam_instance
