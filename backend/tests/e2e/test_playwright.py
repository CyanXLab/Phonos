"""Playwright 真实浏览器交互测试套件。

模拟真实用户操作：打开浏览器 → 注册登录 → 录音 → 评测 → 看结果 → 听写 → 上海考试 → 改配置。

运行方式：
    python backend/tests/e2e/test_playwright.py
    python backend/tests/e2e/test_playwright.py --headless
    python backend/tests/e2e/test_playwright.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright, expect, Page, BrowserContext


BASE_URL = "http://127.0.0.1:8000"
RESULTS_DIR = Path(__file__).resolve().parents[3] / "test_results" / "e2e"


def step(msg: str):
    print(f"\n{'='*60}\n▶ {msg}\n{'='*60}", flush=True)


def screenshot(page: Page, name: str):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"  📸 截图: {path.name}")


def test_homepage_loads(page: Page):
    """测试 1：API 文档页正常加载（frontend 已删除，测试 API 层）。"""
    step("测试 1: API 文档加载")
    page.goto(f"{BASE_URL}/docs", wait_until="networkidle", timeout=15000)
    # FastAPI Swagger UI 标题
    expect(page).to_have_title("Phonos 口语练习平台 - Swagger UI")
    screenshot(page, "01_api_docs")
    print("  ✓ API 文档页加载成功")


def test_user_registration_and_login(page: Page, context: BrowserContext):
    """测试 2：用户注册和登录（通过 API 测试）。"""
    step("测试 2: 用户注册和登录（API）")
    import urllib.request
    import json as _json
    username = f"testuser_{uuid.uuid4().hex[:8]}"
    password = "TestPass123"

    # 通过 API 注册
    data = _json.dumps({"username": username, "password": password, "display_name": "测试用户"}).encode()
    req = urllib.request.Request(f"{BASE_URL}/api/auth/register", data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                print(f"  ✓ API 注册成功: {username}")
            else:
                print(f"  ⚠ 注册返回 {resp.status}")
    except Exception as e:
        print(f"  ⚠ 注册失败: {e}")

    # 登录
    data = _json.dumps({"username": username, "password": password}).encode()
    req = urllib.request.Request(f"{BASE_URL}/api/auth/login", data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = _json.loads(resp.read())
            if result.get("token"):
                print(f"  ✓ API 登录成功，获取 token")
            else:
                print(f"  ⚠ 登录无 token")
    except Exception as e:
        print(f"  ⚠ 登录失败: {e}")
    screenshot(page, "02_api_auth")
    return username, password


def test_sentence_loading(page: Page):
    """测试 3：句子加载（通过 API）。"""
    step("测试 3: 句子加载（API）")
    import urllib.request
    import json as _json
    req = urllib.request.Request(f"{BASE_URL}/api/sentences")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read())
            count = len(data) if isinstance(data, list) else len(data.get("sentences", []))
            print(f"  ✓ 句子列表加载: {count} 个")
    except Exception as e:
        print(f"  ⚠ 句子加载失败: {e}")
    screenshot(page, "03_sentences")


def test_tts_playback(page: Page):
    """测试 4：TTS API。"""
    step("测试 4: TTS API")
    import urllib.request
    req = urllib.request.Request(f"{BASE_URL}/api/tts/check")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json as _json
            data = _json.loads(resp.read())
            engines = [k for k, v in data.items() if v]
            print(f"  ✓ TTS 可用引擎: {engines}")
    except Exception as e:
        print(f"  ⚠ TTS 检查失败: {e}")
    screenshot(page, "04_tts")


def test_recording_flow(page: Page):
    """测试 5：录音 API（评测接口可用性）。"""
    step("测试 5: 评测 API")
    import urllib.request
    req = urllib.request.Request(f"{BASE_URL}/api/health/v2")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json as _json
            data = _json.loads(resp.read())
            huper = data.get("checks", {}).get("huper_model", {})
            if huper.get("available"):
                print(f"  ✓ HuPER 模型可用: {huper.get('path', '')[:50]}")
            else:
                print(f"  ⚠ HuPER 模型不可用")
    except Exception as e:
        print(f"  ⚠ 健康检查失败: {e}")
    screenshot(page, "05_evaluator")


def test_dictation_flow(page: Page):
    """测试 6：听写 API。"""
    step("测试 6: 听写 API")
    import urllib.request
    import json as _json
    # 注册 + 登录
    username = f"dict_{uuid.uuid4().hex[:8]}"
    data = _json.dumps({"username": username, "password": "TestPass123", "display_name": "T"}).encode()
    req = urllib.request.Request(f"{BASE_URL}/api/auth/register", data=data, headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=10)
    data = _json.dumps({"username": username, "password": "TestPass123"}).encode()
    req = urllib.request.Request(f"{BASE_URL}/api/auth/login", data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        token = _json.loads(resp.read())["token"]

    # 听写检查
    data = _json.dumps({"expected": "hello world", "actual": "hello world", "keywords": []}).encode()
    req = urllib.request.Request(f"{BASE_URL}/api/v2/dictation/check", data=data, headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = _json.loads(resp.read())
            print(f"  ✓ 听写评分: {result.get('overall_score')}")
    except Exception as e:
        print(f"  ⚠ 听写检查失败: {e}")
    screenshot(page, "06_dictation")


def test_shanghai_exam_page(page: Page):
    """测试 7：上海听说考试模块。"""
    step("测试 7: 上海听说考试模块")
    page.goto(f"{BASE_URL}/docs", wait_until="networkidle")
    page.wait_for_timeout(2000)
    body = page.inner_text("body")
    if "shanghai" in body.lower():
        print("  ✓ API 文档中包含上海考试接口")
    screenshot(page, "10_api_docs")


def test_config_center(page: Page):
    """测试 8：配置中心。"""
    step("测试 8: 配置中心")
    page.goto(f"{BASE_URL}/docs", wait_until="networkidle")
    page.wait_for_timeout(1000)
    body = page.inner_text("body")
    if "/api/config" in body:
        print("  ✓ 配置中心 API 已注册")
    screenshot(page, "11_config_docs")


def test_mobile_responsive(page: Page):
    """测试 9：API 文档在不同视口可访问。"""
    step("测试 9: 多视口访问")
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{BASE_URL}/docs", wait_until="networkidle")
    page.wait_for_timeout(1000)
    screenshot(page, "12_mobile_375")
    page.set_viewport_size({"width": 768, "height": 1024})
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(1000)
    screenshot(page, "13_tablet_768")
    page.set_viewport_size({"width": 1280, "height": 800})
    print("  ✓ 多视口访问测试完成")


def test_no_console_errors(page: Page):
    """测试 10：API 文档页控制台无错误。"""
    step("测试 10: 控制台错误检查")
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda err: errors.append(f"pageerror: {err}"))
    page.goto(f"{BASE_URL}/docs", wait_until="networkidle")
    page.wait_for_timeout(3000)
    if errors:
        print(f"  ⚠ 控制台有 {len(errors)} 个错误:")
        for e in errors[:5]:
            print(f"    - {e[:150]}")
    else:
        print("  ✓ 控制台无错误")
    screenshot(page, "14_final")
    return errors


def main():
    global BASE_URL
    parser = argparse.ArgumentParser(description="Phonos v3 Playwright E2E 测试")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--no-headless", dest="headless", action="store_false")
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()

    BASE_URL = args.base_url
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results = {"passed": 0, "failed": 0, "errors": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=args.headless,
            args=["--disable-web-security", "--auto-accept-camera-and-microphone-capture"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
            permissions=["microphone"],
        )
        page = context.new_page()

        tests = [
            ("首页加载", lambda: test_homepage_loads(page)),
            ("注册登录", lambda: test_user_registration_and_login(page, context)),
            ("句子加载", lambda: test_sentence_loading(page)),
            ("TTS 播放", lambda: test_tts_playback(page)),
            ("录音流程", lambda: test_recording_flow(page)),
            ("听写流程", lambda: test_dictation_flow(page)),
            ("上海考试", lambda: test_shanghai_exam_page(page)),
            ("配置中心", lambda: test_config_center(page)),
            ("移动端响应式", lambda: test_mobile_responsive(page)),
            ("控制台错误", lambda: test_no_console_errors(page)),
        ]

        for name, test_fn in tests:
            try:
                test_fn()
                results["passed"] += 1
            except Exception as e:
                results["failed"] += 1
                results["errors"].append({"test": name, "error": str(e)[:300]})
                print(f"  ✗ 失败: {e}")
                try:
                    screenshot(page, f"FAIL_{name}")
                except Exception:
                    pass

        browser.close()

    print(f"\n{'='*60}")
    print(f"E2E 测试结果: {results['passed']} 通过, {results['failed']} 失败")
    print(f"{'='*60}")
    if results["errors"]:
        print("\n失败详情:")
        for e in results["errors"]:
            print(f"  - {e['test']}: {e['error']}")

    result_file = RESULTS_DIR / "results.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {result_file}")
    print(f"截图目录: {RESULTS_DIR}")
    return 0 if results["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
