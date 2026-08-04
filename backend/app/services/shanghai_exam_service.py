"""上海高考英语听说考试模块（按 2025 年起新结构）。

考试结构（2025 届起执行）：
- 总分 35 分，时长 35 分钟
- 听力 25 分（Section A 短文对话选择 10 分 + Section B 短文/长对话选择 15 分）
- 口语 10 分：
  - 朗读句子 1 分
  - 朗读短文 1 分
  - 情景提问 2 分
  - 看图作文 1.5 分
  - 快速应答 2 分
  - 简述与回答 2.5 分

评分方式：智能双评 + 人工仲裁

合规声明：本系统为辅助评估，非官方成绩，与上海市教育考试院无关联。

数据来源：
- 上海市教育考试院官方政策（2024-2026）
- B 站 2025.6 官方模拟试卷说明
- 知乎 2026 秋考考生回忆
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


# ============================================================
# 真实高考题型枚举（7 种）
# ============================================================
class TaskType(str, Enum):
    # 听力部分（25 分，选择题）
    LISTENING_SHORT = "listening_short"  # Section A: 听短文对话选择 (10分)
    LISTENING_LONG = "listening_long"  # Section B: 听短文/长对话选择 (15分)
    # 口语部分（10 分）
    READ_SENTENCE = "read_sentence"  # 朗读句子 (1分)
    READ_PASSAGE = "read_passage"  # 朗读短文 (1分)
    SITUATIONAL_QUESTION = "situational_question"  # 情景提问 (2分)
    PICTURE_DESCRIPTION = "picture_description"  # 看图作文 (1.5分)
    QUICK_RESPONSE = "quick_response"  # 快速应答 (2分)
    RETELL_AND_ANSWER = "retell_and_answer"  # 简述与回答 (2.5分)


# 各题型分值（真实高考）
TASK_SCORES: dict[TaskType, float] = {
    TaskType.LISTENING_SHORT: 10.0,
    TaskType.LISTENING_LONG: 15.0,
    TaskType.READ_SENTENCE: 1.0,
    TaskType.READ_PASSAGE: 1.0,
    TaskType.SITUATIONAL_QUESTION: 2.0,
    TaskType.PICTURE_DESCRIPTION: 1.5,
    TaskType.QUICK_RESPONSE: 2.0,
    TaskType.RETELL_AND_ANSWER: 2.5,
}

# 各题型默认计时（秒）- 官方未公开精确值，此处为训练默认值
TASK_TIMING: dict[TaskType, dict] = {
    TaskType.LISTENING_SHORT: {"prep": 5, "response": 10, "replay": 1},
    TaskType.LISTENING_LONG: {"prep": 5, "response": 15, "replay": 1},
    TaskType.READ_SENTENCE: {"prep": 10, "response": 15},
    TaskType.READ_PASSAGE: {"prep": 30, "response": 60},
    TaskType.SITUATIONAL_QUESTION: {"prep": 15, "response": 20},
    TaskType.PICTURE_DESCRIPTION: {"prep": 60, "response": 60},
    TaskType.QUICK_RESPONSE: {"prep": 0, "response": 10},
    TaskType.RETELL_AND_ANSWER: {"prep": 30, "response": 60, "replay": 2},
}


class ExamMode(str, Enum):
    PRACTICE = "practice"
    EXAM = "exam"


# 合规声明（必须出现在所有报告）
DISCLAIMER = (
    "本报告由 Phonos 系统辅助评估生成，非官方成绩，仅供参考。"
    "评分基于本地 AI 模型 + LLM 评分，可能与人工评分存在偏差。"
    "建议结合教师反馈综合判断。"
    "Phonos 与上海市教育考试院无任何关联。"
    "各题型准备/答题时间为训练默认值，实际以当年官方界面为准。"
)


@dataclass
class ExamTask:
    """考试任务（按真实高考结构）。"""
    id: str
    type: TaskType
    section: str  # "listening" / "speaking"
    title: str
    prompt: str  # 题目文本
    audio_url: Optional[str] = None  # 听力音频
    image_urls: Optional[List[str]] = None  # 看图说话图片
    expected_answer: Optional[str] = None  # 朗读/参考答案
    keywords: Optional[List[str]] = None  # 关键信息点
    options: Optional[List[str]] = None  # 选择题选项
    correct_option: Optional[int] = None  # 正确选项 index
    full_score: float = 0.0  # 满分
    timing: Optional[dict] = None  # {prep, response, replay?}
    difficulty: str = "medium"
    topic: str = ""
    cefr: str = ""
    year: str = ""  # 真题年份（如 "2025春考"）
    source: str = ""  # "official_mock" / "candidate_recall" / "training"

    def __post_init__(self):
        if self.full_score == 0.0:
            self.full_score = TASK_SCORES.get(self.type, 0.0)
        if self.timing is None:
            self.timing = TASK_TIMING.get(self.type, {"prep": 15, "response": 30})

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "section": self.section,
            "title": self.title,
            "prompt": self.prompt,
            "audio_url": self.audio_url,
            "image_urls": self.image_urls,
            "expected_answer": self.expected_answer,
            "keywords": self.keywords,
            "options": self.options,
            "correct_option": self.correct_option,
            "full_score": self.full_score,
            "timing": self.timing,
            "difficulty": self.difficulty,
            "topic": self.topic,
            "cefr": self.cefr,
            "year": self.year,
            "source": self.source,
        }


@dataclass
class ExamSession:
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
    """考试报告（按真实高考 35 分结构）。"""
    session_id: str
    user_id: str
    mode: ExamMode
    started_at: float
    finished_at: float
    duration_sec: float
    # 总分（35 分制）
    total_score: float
    full_score: float
    # 听力部分（25 分）
    listening_score: float
    listening_full: float
    # 口语部分（10 分）
    speaking_score: float
    speaking_full: float
    # 各题型得分
    task_results: List[dict]
    # 维度评分（口语部分）
    dimension_scores: dict
    strengths: List[str]
    weaknesses: List[str]
    suggestions: List[str]
    disclaimer: str

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "mode": self.mode.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_sec": self.duration_sec,
            "total_score": self.total_score,
            "full_score": self.full_score,
            "listening_score": self.listening_score,
            "listening_full": self.listening_full,
            "speaking_score": self.speaking_score,
            "speaking_full": self.speaking_full,
            "task_results": self.task_results,
            "dimension_scores": self.dimension_scores,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "suggestions": self.suggestions,
            "disclaimer": self.disclaimer,
        }


# ============================================================
# 真题语料库（从 JSON 文件加载，支持一模/二模/春考/秋考）
# ============================================================
def _build_corpus() -> List[ExamTask]:
    """从 shanghai_corpus/*.json 加载语料。

    数据来源：
    - 2025/2026 春考、秋考考生回忆
    - 2025 一模、二模
    - 训练题
    """
    import json
    from pathlib import Path

    corpus_dir = Path(__file__).resolve().parents[2] / "shanghai_corpus"
    tasks: List[ExamTask] = []

    if not corpus_dir.is_dir():
        # 回退：使用内置示例
        return _build_fallback_corpus()

    # 按题型映射
    type_mapping = {
        "listening_short": TaskType.LISTENING_SHORT,
        "listening_long": TaskType.LISTENING_LONG,
        "read_sentence": TaskType.READ_SENTENCE,
        "read_passage": TaskType.READ_PASSAGE,
        "situational_question": TaskType.SITUATIONAL_QUESTION,
        "picture_description": TaskType.PICTURE_DESCRIPTION,
        "quick_response": TaskType.QUICK_RESPONSE,
        "retell_and_answer": TaskType.RETELL_AND_ANSWER,
    }

    for json_file in corpus_dir.glob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                continue
            for item in data:
                task_type_str = item.get("type", "")
                if task_type_str not in type_mapping:
                    continue
                task_type = type_mapping[task_type_str]
                section = "listening" if "listening" in task_type_str else "speaking"
                timing = TASK_TIMING.get(task_type, {"prep": 15, "response": 30})

                task = ExamTask(
                    id=item.get("id", ""),
                    type=task_type,
                    section=section,
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
                    year=item.get("year", ""),
                    source=item.get("source", ""),
                )
                tasks.append(task)
        except Exception as e:
            from ..core.logging import get_logger
            get_logger("shanghai_exam").warning("corpus_load_failed", file=str(json_file), error=str(e))

    return tasks


def _build_fallback_corpus() -> List[ExamTask]:
    """回退语料（当 JSON 文件不存在时）。"""

    # ========== 听力部分 ==========

    # Section A: 听短文对话选择（10 分，每题 1 分）
    listening_a_samples = [
        {
            "id": "la_001",
            "prompt": "听对话，选择正确答案。What does the woman suggest the man do?",
            "options": ["Wash by hand", "Buy a new one", "Call a repairman", "Do nothing"],
            "correct_option": 0,
            "audio_url": "audio/la_001.mp3",
            "topic": "daily_life",
            "cefr": "B1",
            "year": "2026秋考回忆",
            "source": "candidate_recall",
            "difficulty": "medium",
        },
        {
            "id": "la_002",
            "prompt": "听对话，选择正确答案。Why is the student short of money?",
            "options": ["Lost wallet", "Spent all on food", "End of month", "Parents stopped paying"],
            "correct_option": 2,
            "audio_url": "audio/la_002.mp3",
            "topic": "school_life",
            "cefr": "B1",
            "year": "2026秋考回忆",
            "source": "candidate_recall",
            "difficulty": "easy",
        },
    ]
    for s in listening_a_samples:
        tasks.append(ExamTask(
            type=TaskType.LISTENING_SHORT,
            section="listening",
            title=f"听力 Section A - {s['topic']}",
            **s,
        ))

    # Section B: 听短文/长对话选择（15 分）
    listening_b_samples = [
        {
            "id": "lb_001",
            "prompt": "听短文，选择正确答案。What is the main idea of the passage about the mobile forest?",
            "options": [
                "Innovative thinking",
                "Environmental awareness",
                "Both A and B equally",
                "Neither A nor B",
            ],
            "correct_option": 2,
            "audio_url": "audio/lb_001.mp3",
            "topic": "environment",
            "cefr": "B2",
            "year": "2026秋考回忆",
            "source": "candidate_recall",
            "difficulty": "hard",
        },
        {
            "id": "lb_002",
            "prompt": "听长对话，选择正确答案。What should you do before applying for a job?",
            "options": ["Update CV", "Practice interview", "Research company", "All of the above"],
            "correct_option": 3,
            "audio_url": "audio/lb_002.mp3",
            "topic": "career",
            "cefr": "B1",
            "year": "2026秋考回忆",
            "source": "candidate_recall",
            "difficulty": "medium",
        },
    ]
    for s in listening_b_samples:
        tasks.append(ExamTask(
            type=TaskType.LISTENING_LONG,
            section="listening",
            title=f"听力 Section B - {s['topic']}",
            **s,
        ))

    # ========== 口语部分 ==========

    # 1. 朗读句子（1 分）
    read_sentence_samples = [
        {
            "id": "rs_001",
            "prompt": "Please read the following sentence aloud.",
            "expected_answer": "The weather is beautiful today, so I decide to go for a walk in the park.",
            "topic": "daily_life",
            "cefr": "A2",
            "year": "训练题",
            "source": "training",
            "difficulty": "easy",
        },
        {
            "id": "rs_002",
            "prompt": "Please read the following sentence aloud.",
            "expected_answer": "Technology has greatly changed the way we communicate with each other.",
            "topic": "technology",
            "cefr": "B1",
            "year": "训练题",
            "source": "training",
            "difficulty": "medium",
        },
    ]
    for s in read_sentence_samples:
        tasks.append(ExamTask(
            type=TaskType.READ_SENTENCE,
            section="speaking",
            title=f"朗读句子 - {s['topic']}",
            **s,
        ))

    # 2. 朗读短文（1 分）
    read_passage_samples = [
        {
            "id": "rp_001",
            "prompt": "Please read the following passage aloud.",
            "expected_answer": "Education is not merely about acquiring knowledge but about developing the capacity to think independently. The most effective way to improve your pronunciation is through consistent practice and active listening.",
            "topic": "education",
            "cefr": "B1",
            "year": "训练题",
            "source": "training",
            "difficulty": "medium",
        },
    ]
    for s in read_passage_samples:
        tasks.append(ExamTask(
            type=TaskType.READ_PASSAGE,
            section="speaking",
            title=f"朗读短文 - {s['topic']}",
            **s,
        ))

    # 3. 情景提问（2 分）
    situational_samples = [
        {
            "id": "sq_001",
            "prompt": "情景：你想知道朋友周末的计划。请用英语提问。",
            "expected_answer": "What are you going to do this weekend? / Do you have any plans for the weekend?",
            "keywords": ["weekend", "plan", "do"],
            "topic": "daily_life",
            "cefr": "A2",
            "year": "训练题",
            "source": "training",
            "difficulty": "easy",
        },
        {
            "id": "sq_002",
            "prompt": "情景：你想询问图书馆的开放时间。请用英语提问。",
            "expected_answer": "What time does the library open? / When is the library open?",
            "keywords": ["library", "open", "time"],
            "topic": "school_life",
            "cefr": "A2",
            "year": "训练题",
            "source": "training",
            "difficulty": "easy",
        },
    ]
    for s in situational_samples:
        tasks.append(ExamTask(
            type=TaskType.SITUATIONAL_QUESTION,
            section="speaking",
            title=f"情景提问 - {s['topic']}",
            **s,
        ))

    # 4. 看图作文（1.5 分）
    picture_samples = [
        {
            "id": "pd_001",
            "prompt": "看图说话：根据以下图片，讲述一个完整的故事。",
            "image_urls": ["picture_pd_001_a.jpg", "picture_pd_001_b.jpg", "picture_pd_001_c.jpg"],
            "expected_answer": "One morning, a boy was walking to school when he saw an old lady dropping her groceries. He helped her pick up the things and she thanked him. The boy felt happy and continued to school.",
            "keywords": ["morning", "walking", "school", "old lady", "helped", "happy"],
            "topic": "narrative",
            "cefr": "B1",
            "year": "训练题",
            "source": "training",
            "difficulty": "medium",
        },
        {
            "id": "pd_002",
            "prompt": "看图说话：图片展示了一个家庭为妈妈过生日的故事。请讲述。",
            "image_urls": ["picture_pd_002_a.jpg", "picture_pd_002_b.jpg"],
            "expected_answer": "The family prepared a surprise birthday party for their mother. The children decorated the room with balloons and made a cake. When mother came home, everyone shouted 'Happy Birthday!' and she was deeply moved.",
            "keywords": ["family", "birthday", "surprise", "mother", "party", "cake"],
            "topic": "family",
            "cefr": "B1",
            "year": "2026秋考回忆",
            "source": "candidate_recall",
            "difficulty": "hard",
        },
    ]
    for s in picture_samples:
        tasks.append(ExamTask(
            type=TaskType.PICTURE_DESCRIPTION,
            section="speaking",
            title=f"看图说话 - {s['topic']}",
            **s,
        ))

    # 5. 快速应答（2 分）
    quick_response_samples = [
        {"id": "qr_001", "prompt": "听到: 'Thank you very much for your help.' 请快速应答。",
         "expected_answer": "You're welcome. / My pleasure. / Any time.",
         "topic": "social", "cefr": "A1", "year": "训练题", "source": "training", "difficulty": "easy"},
        {"id": "qr_002", "prompt": "听到: 'Would you mind opening the window?' 请快速应答。",
         "expected_answer": "Not at all. / Of course not. / Sure, no problem.",
         "topic": "social", "cefr": "A2", "year": "训练题", "source": "training", "difficulty": "easy"},
        {"id": "qr_003", "prompt": "听到: 'How was your weekend?' 请快速应答。",
         "expected_answer": "It was great. / Pretty good. / I had a wonderful time.",
         "topic": "social", "cefr": "A2", "year": "训练题", "source": "training", "difficulty": "easy"},
    ]
    for s in quick_response_samples:
        tasks.append(ExamTask(
            type=TaskType.QUICK_RESPONSE,
            section="speaking",
            title=f"快速应答 - {s['topic']}",
            **s,
        ))

    # 6. 简述与回答（2.5 分）
    retell_samples = [
        {
            "id": "ra_001",
            "prompt": "听一段材料后，简述内容并回答问题。",
            "audio_url": "audio/ra_001.mp3",
            "expected_answer": "Last Sunday, Tom went to the library to borrow some books about history. He spent two hours there and finally found three books he needed for his research paper. After that, he went to a café to review the books.",
            "keywords": ["Sunday", "library", "history", "two hours", "three books", "research"],
            "topic": "narrative",
            "cefr": "B1",
            "year": "训练题",
            "source": "training",
            "difficulty": "hard",
        },
    ]
    for s in retell_samples:
        tasks.append(ExamTask(
            type=TaskType.RETELL_AND_ANSWER,
            section="speaking",
            title=f"简述与回答 - {s['topic']}",
            **s,
        ))

    return tasks


# ============================================================
# 上海考试服务
# ============================================================
class ShanghaiExamService:
    """上海高考听说考试服务（按真实 35 分结构）。"""

    def __init__(self):
        self._corpus: List[ExamTask] = _build_corpus()
        self._sessions: dict[str, ExamSession] = {}

    def list_task_types(self) -> List[dict]:
        """列出所有题型（含真实分值）。"""
        result = []
        for tt in TaskType:
            section = "listening" if tt in (TaskType.LISTENING_SHORT, TaskType.LISTENING_LONG) else "speaking"
            result.append({
                "type": tt.value,
                "section": section,
                "full_score": TASK_SCORES[tt],
                "timing": TASK_TIMING[tt],
                "task_count": len([t for t in self._corpus if t.type == tt]),
            })
        return result

    def corpus_count(self) -> int:
        return len(self._corpus)

    def list_tasks(
        self,
        task_type: Optional[TaskType] = None,
        section: Optional[str] = None,
        difficulty: Optional[str] = None,
        year: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        tasks = self._corpus
        if task_type:
            tasks = [t for t in tasks if t.type == task_type]
        if section:
            tasks = [t for t in tasks if t.section == section]
        if difficulty:
            tasks = [t for t in tasks if t.difficulty == difficulty]
        if year:
            tasks = [t for t in tasks if year in t.year]
        return [t.to_dict() for t in tasks[:limit]]

    def list_years(self) -> List[str]:
        """列出所有年份/套卷标签。"""
        years = set()
        for t in self._corpus:
            if t.year:
                years.add(t.year)
        return sorted(years)

    def create_exam_by_year(self, user_id: str, year: str, mode: ExamMode = ExamMode.EXAM) -> ExamSession:
        """按年份/套卷创建考试（如 "2025一模"、"2026秋考"）。"""
        import uuid
        tasks = [t for t in self._corpus if year in t.year]
        if not tasks:
            tasks = self._corpus[:5]
        session = ExamSession(
            id=uuid.uuid4().hex[:16],
            user_id=user_id,
            mode=mode,
            tasks=tasks,
            started_at=time.time(),
        )
        self._sessions[session.id] = session
        return session

    def get_task(self, task_id: str) -> Optional[dict]:
        for t in self._corpus:
            if t.id == task_id:
                return t.to_dict()
        return None

    def create_full_exam(self, user_id: str, mode: ExamMode = ExamMode.EXAM) -> ExamSession:
        """创建完整高考听说套卷（35 分，35 分钟）。"""
        import uuid

        # 按真实高考顺序：听力 → 口语
        # 听力 Section A（取 2 题，每题 5 分模拟）
        # 听力 Section B（取 2 题）
        # 口语 6 题
        tasks: List[ExamTask] = []
        # 听力
        tasks.extend([t for t in self._corpus if t.type == TaskType.LISTENING_SHORT][:2])
        tasks.extend([t for t in self._corpus if t.type == TaskType.LISTENING_LONG][:2])
        # 口语（按真实顺序）
        for tt in [TaskType.READ_SENTENCE, TaskType.READ_PASSAGE,
                   TaskType.SITUATIONAL_QUESTION, TaskType.PICTURE_DESCRIPTION,
                   TaskType.QUICK_RESPONSE, TaskType.RETELL_AND_ANSWER]:
            tasks.extend([t for t in self._corpus if t.type == tt][:1])

        session = ExamSession(
            id=uuid.uuid4().hex[:16],
            user_id=user_id,
            mode=mode,
            tasks=tasks,
            started_at=time.time(),
        )
        self._sessions[session.id] = session
        return session

    def create_practice_session(
        self,
        user_id: str,
        task_types: Optional[List[TaskType]] = None,
        task_count: int = 5,
    ) -> ExamSession:
        """创建练习会话（按题型选择）。"""
        import uuid
        import random

        if task_types:
            tasks = [t for t in self._corpus if t.type in task_types]
        else:
            tasks = self._corpus[:]
        tasks = random.sample(tasks, min(task_count, len(tasks)))

        session = ExamSession(
            id=uuid.uuid4().hex[:16],
            user_id=user_id,
            mode=ExamMode.PRACTICE,
            tasks=tasks,
            started_at=time.time(),
        )
        self._sessions[session.id] = session
        return session

    def get_session(self, session_id: str) -> Optional[ExamSession]:
        return self._sessions.get(session_id)

    def submit_response(self, session_id: str, task_id: str, response: dict) -> dict:
        session = self._sessions.get(session_id)
        if not session:
            return {"error": "session_not_found"}
        session.responses.append({
            "task_id": task_id,
            "response": response,
            "submitted_at": time.time(),
        })
        return {"ok": True}

    def finish_session(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if not session:
            return False
        session.finished_at = time.time()
        return True

    def generate_report(self, session_id: str) -> Optional[ExamReport]:
        """生成考试报告（按真实高考 35 分结构）。"""
        session = self._sessions.get(session_id)
        if not session or not session.finished_at:
            return None

        task_results = []
        listening_score = 0.0
        speaking_score = 0.0
        listening_full = 0.0
        speaking_full = 0.0

        for resp in session.responses:
            task = next((t for t in session.tasks if t.id == resp["task_id"]), None)
            if not task:
                continue
            # 得分（response 中应包含 score 字段，0-100）
            score_pct = resp["response"].get("score", 0) / 100
            earned = score_pct * task.full_score

            task_results.append({
                "task_id": task.id,
                "task_type": task.type.value,
                "section": task.section,
                "title": task.title,
                "year": task.year,
                "full_score": task.full_score,
                "earned_score": round(earned, 2),
                "score_pct": round(score_pct * 100, 1),
                "feedback": resp["response"].get("feedback", ""),
                "llm_scores": resp["response"].get("llm_scores", {}),
            })

            if task.section == "listening":
                listening_score += earned
                listening_full += task.full_score
            else:
                speaking_score += earned
                speaking_full += task.full_score

        total = listening_score + speaking_score
        full = listening_full + speaking_full

        # 维度评分（口语部分汇总）
        dimension_scores = {
            "content_relevance": 0,
            "keyword_coverage": 0,
            "semantic_completeness": 0,
            "grammar_accuracy": 0,
            "pronunciation_clarity": 0,
            "fluency": 0,
        }
        speaking_tasks = [r for r in task_results if r["section"] == "speaking"]
        for r in speaking_tasks:
            llm = r.get("llm_scores", {})
            for k in dimension_scores:
                dimension_scores[k] += llm.get(k, 0)
        if speaking_tasks:
            for k in dimension_scores:
                dimension_scores[k] = round(dimension_scores[k] / len(speaking_tasks), 1)

        # 优劣势分析
        strengths = [r["title"] for r in task_results if r["score_pct"] >= 80]
        weaknesses = [r["title"] for r in task_results if r["score_pct"] < 60]
        suggestions = self._build_suggestions(task_results, weaknesses, dimension_scores)

        return ExamReport(
            session_id=session.id,
            user_id=session.user_id,
            mode=session.mode,
            started_at=session.started_at,
            finished_at=session.finished_at,
            duration_sec=session.finished_at - session.started_at,
            total_score=round(total, 2),
            full_score=full,
            listening_score=round(listening_score, 2),
            listening_full=listening_full,
            speaking_score=round(speaking_score, 2),
            speaking_full=speaking_full,
            task_results=task_results,
            dimension_scores=dimension_scores,
            strengths=strengths,
            weaknesses=weaknesses,
            suggestions=suggestions,
            disclaimer=DISCLAIMER,
        )

    def _build_suggestions(self, results, weaknesses, dims) -> List[str]:
        s = []
        if weaknesses:
            s.append(f"建议针对以下任务加强练习：{', '.join(weaknesses[:3])}")
        if dims.get("pronunciation_clarity", 100) < 70:
            s.append("发音清晰度不足，建议每天朗读 15 分钟，重点练习音素对比")
        if dims.get("fluency", 100) < 70:
            s.append("流利度有待提升，多进行连贯朗读训练，减少停顿")
        if dims.get("grammar_accuracy", 100) < 70:
            s.append("语法错误较多，复习基本句型和时态")
        if dims.get("content_relevance", 100) < 70:
            s.append("内容相关性不足，注意审题，确保回答切题")
        if dims.get("keyword_coverage", 100) < 70:
            s.append("关键词覆盖不足，听材料时注意抓取关键信息")
        s.append("建议结合教师反馈，针对性提升薄弱环节")
        return s


_exam_instance: Optional[ShanghaiExamService] = None


def get_shanghai_exam_service() -> ShanghaiExamService:
    global _exam_instance
    if _exam_instance is None:
        _exam_instance = ShanghaiExamService()
    return _exam_instance
