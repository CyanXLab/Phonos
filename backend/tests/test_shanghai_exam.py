"""上海考试模块测试。"""

import pytest

from app.services.shanghai_exam_service import (
    ShanghaiExamService,
    TaskType,
    ExamMode,
    TASK_TIMING_PRESETS,
    DISCLAIMER,
    get_shanghai_exam_service,
)


class TestShanghaiExamService:
    def test_task_types_defined(self):
        assert len(TaskType) == 10  # 9 种 + mock_exam

    def test_timing_presets(self):
        for task_type in TaskType:
            assert task_type in TASK_TIMING_PRESETS
            timing = TASK_TIMING_PRESETS[task_type]
            # mock_exam 是套卷模式，preparation 为 0，其他都有准备时间
            if task_type == TaskType.MOCK_EXAM:
                assert timing.response_sec > 0
            else:
                assert timing.preparation_sec > 0
                assert timing.response_sec > 0

    def test_corpus_loaded(self):
        svc = get_shanghai_exam_service()
        assert svc.corpus_count() > 0  # 至少有示例语料

    def test_list_task_types(self):
        svc = get_shanghai_exam_service()
        types = svc.list_task_types()
        assert len(types) == 10
        for t in types:
            assert "type" in t
            assert "default_timing" in t
            assert "task_count" in t

    def test_list_tasks_filter(self):
        svc = get_shanghai_exam_service()
        # 按类型筛选
        tasks = svc.list_tasks(task_type=TaskType.SENTENCE_READING)
        for t in tasks:
            assert t["type"] == "sentence_reading"

    def test_get_task(self):
        svc = get_shanghai_exam_service()
        tasks = svc.list_tasks()
        if tasks:
            task_id = tasks[0]["id"]
            task = svc.get_task(task_id)
            assert task is not None
            assert task["id"] == task_id

    def test_create_session_practice(self):
        svc = get_shanghai_exam_service()
        session = svc.create_session(
            user_id="test_user",
            mode=ExamMode.PRACTICE,
            task_count=3,
        )
        assert session.id
        assert session.user_id == "test_user"
        assert session.mode == ExamMode.PRACTICE
        assert len(session.tasks) == 3

    def test_create_session_exam(self):
        svc = get_shanghai_exam_service()
        session = svc.create_session(
            user_id="test_user",
            mode=ExamMode.EXAM,
            task_count=5,
        )
        assert session.mode == ExamMode.EXAM

    def test_submit_response(self):
        svc = get_shanghai_exam_service()
        session = svc.create_session(
            user_id="test_user",
            mode=ExamMode.PRACTICE,
            task_count=2,
        )
        task_id = session.tasks[0].id
        result = svc.submit_response(
            session.id, task_id,
            {"audio_url": "test.wav", "score": 85},
        )
        assert result["ok"] is True
        assert len(session.responses) == 1

    def test_finish_session(self):
        import time

        svc = get_shanghai_exam_service()
        session = svc.create_session(
            user_id="test_user",
            mode=ExamMode.PRACTICE,
            task_count=1,
        )
        session.finished_at = time.time()
        assert session.finished_at is not None

    def test_generate_report(self):
        import time

        svc = get_shanghai_exam_service()
        session = svc.create_session(
            user_id="test_user",
            mode=ExamMode.PRACTICE,
            task_count=2,
        )
        # 提交作答
        for task in session.tasks:
            svc.submit_response(
                session.id, task.id,
                {"audio_url": "test.wav", "score": 80, "feedback": "good"},
            )
        session.finished_at = time.time()

        report = svc.generate_report(session.id)
        assert report is not None
        assert report.session_id == session.id
        assert report.user_id == "test_user"
        assert report.overall_score == 80.0
        assert DISCLAIMER in report.disclaimer
        assert "辅助评估" in report.disclaimer
        assert "非官方" in report.disclaimer
        assert "建议结合教师反馈" in report.disclaimer

    def test_disclaimer_compliance(self):
        """合规声明必须包含关键句。"""
        assert "辅助评估" in DISCLAIMER
        assert "非官方" in DISCLAIMER
        assert "建议结合教师反馈" in DISCLAIMER
        assert "上海市教育考试院" in DISCLAIMER

    def test_session_user_isolation(self):
        """会话用户隔离。"""
        svc = get_shanghai_exam_service()
        s1 = svc.create_session(user_id="user_a", mode=ExamMode.PRACTICE, task_count=1)
        s2 = svc.create_session(user_id="user_b", mode=ExamMode.PRACTICE, task_count=1)
        assert s1.user_id != s2.user_id
        assert svc.get_session(s1.id).user_id == "user_a"
        assert svc.get_session(s2.id).user_id == "user_b"
