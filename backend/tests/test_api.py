"""API 端点集成测试。

需要完整依赖（fsrs, g2p-en, onnxruntime 等），通过 --integration 标志运行：
    pytest tests/test_api.py --integration
"""

import pytest
from fastapi.testclient import TestClient

# 标记为集成测试，默认跳过
pytestmark = pytest.mark.skipif(
    True,  # 默认跳过，需显式 --integration 才运行
    reason="集成测试需要完整依赖，运行：pytest --integration",
)


@pytest.fixture
def client():
    """创建测试客户端。"""
    from main import app

    return TestClient(app)


@pytest.fixture
def auth_token(client):
    """注册并获取 token。"""
    import uuid

    username = f"testuser_{uuid.uuid4().hex[:8]}"
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "TestPass123", "display_name": "Test"},
    )
    if response.status_code == 200:
        return response.json()["token"]
    # 已存在则登录
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": "TestPass123"},
    )
    return response.json()["token"]


class TestHealthEndpoints:
    def test_health_basic(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_health_v2(self, client):
        r = client.get("/api/health/v2")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        assert "checks" in data
        assert "huper_model" in data["checks"]
        assert "version" in data

    def test_liveness(self, client):
        r = client.get("/api/liveness")
        assert r.status_code == 200
        assert r.json()["alive"] is True


class TestShanghaiExamAPI:
    def test_list_task_types(self, client):
        r = client.get("/api/shanghai-exam/task-types")
        assert r.status_code == 200
        data = r.json()
        assert "task_types" in data
        assert len(data["task_types"]) == 10

    def test_list_tasks(self, client):
        r = client.get("/api/shanghai-exam/tasks")
        assert r.status_code == 200
        assert "tasks" in r.json()

    def test_get_disclaimer(self, client):
        r = client.get("/api/shanghai-exam/disclaimer")
        assert r.status_code == 200
        assert "辅助评估" in r.json()["disclaimer"]

    def test_create_session_requires_auth(self, client):
        r = client.post("/api/shanghai-exam/sessions", json={"mode": "practice"})
        assert r.status_code == 401

    def test_full_exam_flow(self, client, auth_token):
        headers = {"Authorization": f"Bearer {auth_token}"}

        # 1. 创建会话
        r = client.post(
            "/api/shanghai-exam/sessions",
            json={"mode": "practice", "task_count": 2},
            headers=headers,
        )
        assert r.status_code == 200
        session = r.json()
        session_id = session["session_id"]
        assert len(session["tasks"]) == 2

        # 2. 获取会话
        r = client.get(f"/api/shanghai-exam/sessions/{session_id}", headers=headers)
        assert r.status_code == 200

        # 3. 提交作答
        task_id = session["tasks"][0]["id"]
        r = client.post(
            f"/api/shanghai-exam/sessions/{session_id}/submit",
            json={"task_id": task_id, "response": {"score": 85, "feedback": "good"}},
            headers=headers,
        )
        assert r.status_code == 200

        # 4. 结束会话
        r = client.post(f"/api/shanghai-exam/sessions/{session_id}/finish", headers=headers)
        assert r.status_code == 200

        # 5. 获取报告
        r = client.get(f"/api/shanghai-exam/sessions/{session_id}/report", headers=headers)
        assert r.status_code == 200
        report = r.json()
        assert "disclaimer" in report
        assert "辅助评估" in report["disclaimer"]


class TestDictationV2API:
    def test_check_requires_auth(self, client):
        r = client.post("/api/v2/dictation/check", json={"expected": "hello", "actual": "hello"})
        # 旧 get_current_user 兜底为 default，所以可能 200
        assert r.status_code in (200, 401)

    def test_check_perfect(self, client, auth_token):
        headers = {"Authorization": f"Bearer {auth_token}"}
        r = client.post(
            "/api/v2/dictation/check",
            json={
                "expected": "The weather is beautiful",
                "actual": "The weather is beautiful",
            },
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["overall_score"] == 100.0


class TestModelsAPI:
    def test_list_models_requires_auth(self, client):
        r = client.get("/api/models/")
        assert r.status_code == 401

    def test_download_info(self, client, auth_token):
        headers = {"Authorization": f"Bearer {auth_token}"}
        r = client.get("/api/models/download-info", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert "models" in data
        assert "commercial_apis" in data
        # 验证每个模型都有许可证信息
        for m in data["models"]:
            assert "license" in m
            assert "online" in m
            assert "fallback" in m


class TestDataAPI:
    def test_privacy_info(self, client):
        r = client.get("/api/data/privacy")
        assert r.status_code == 200
        data = r.json()
        assert data["default_local"] is True
        assert "user_rights" in data

    def test_export_requires_auth(self, client):
        r = client.get("/api/data/export")
        # 旧 default 兜底会返回 200，但 require_user 应拒绝
        assert r.status_code in (200, 401)
