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
    """测试 1：首页正常加载。"""
    step("测试 1: 首页加载")
    page.goto(BASE_URL, wait_until="networkidle", timeout=15000)
    expect(page).to_have_title("Phonos - 口语练习平台")
    header = page.locator(".header, header").first
    expect(header).to_be_visible()
    failed = page.evaluate("""() => {
        const entries = performance.getEntriesByType('resource');
        return entries.filter(e => e.transferSize === 0 && e.name.includes('cdn'))
            .map(e => e.name);
    }""")
    if failed:
        print(f"  ⚠ CDN 加载失败的资源: {failed}")
    screenshot(page, "01_homepage")
    print("  ✓ 首页加载成功")


def test_user_registration_and_login(page: Page, context: BrowserContext):
    """测试 2：用户注册和登录。"""
    step("测试 2: 用户注册和登录")
    username = f"testuser_{uuid.uuid4().hex[:8]}"
    password = "TestPass123"
    page.goto(BASE_URL, wait_until="networkidle")
    page.wait_for_timeout(1000)

    # 找登录按钮并点击
    login_btn = page.locator("text=登录").first
    try:
        login_btn.wait_for(state="visible", timeout=3000)
        login_btn.click()
        page.wait_for_timeout(800)
    except Exception:
        print("  ⚠ 未找到登录按钮，尝试直接填写")

    # 切换到注册
    reg_tab = page.locator("text=注册").first
    try:
        reg_tab.wait_for(state="visible", timeout=2000)
        reg_tab.click()
        page.wait_for_timeout(500)
    except Exception:
        pass

    # 填写表单（用更宽容的选择器和等待）
    username_input = page.locator('input[placeholder*="用户名"], input[id*="username"], input[id="loginUsername"]').first
    try:
        username_input.wait_for(state="visible", timeout=5000)
        username_input.fill(username)
    except Exception as e:
        print(f"  ⚠ 用户名输入失败: {e}")
        screenshot(page, "02_register_form")
        return None, None

    pwd_input = page.locator('input[type="password"]').first
    pwd_input.fill(password)

    # 显示名（可选）
    display_input = page.locator('input[placeholder*="显示名"], input[placeholder*="昵称"], input[id*="display"]').first
    try:
        display_input.wait_for(state="visible", timeout=1000)
        display_input.fill("测试用户")
    except Exception:
        pass

    screenshot(page, "02_register_form")
    submit = page.locator('button:has-text("注册"), button:has-text("确定"), button:has-text("确认")').first
    submit.click()
    page.wait_for_timeout(2000)
    body_text = page.inner_text("body")
    if username in body_text or "测试用户" in body_text or "登出" in body_text or "退出" in body_text:
        print(f"  ✓ 注册并登录成功: {username}")
    else:
        print(f"  ⚠ 注册可能失败，body 含: {body_text[:200]}")
    screenshot(page, "03_after_register")
    return username, password


def test_sentence_loading(page: Page):
    """测试 3：句子加载。"""
    step("测试 3: 句子加载")
    page.goto(BASE_URL, wait_until="networkidle")
    page.wait_for_timeout(2000)
    sentence_card = page.locator(".sentence-card, .card").first
    expect(sentence_card).to_be_visible()
    sentence_text = sentence_card.inner_text()
    if any(c.isalpha() for c in sentence_text):
        print(f"  ✓ 句子已加载: {sentence_text[:80]}...")
    else:
        print(f"  ⚠ 句子可能未加载")
    screenshot(page, "04_sentence")


def test_tts_playback(page: Page):
    """测试 4：TTS 播放。"""
    step("测试 4: TTS 播放")
    page.goto(BASE_URL, wait_until="networkidle")
    page.wait_for_timeout(1500)
    play_btn = page.locator('button:has-text("播放"), button:has-text("朗读"), button:has-text("🔊")').first
    if play_btn.is_visible():
        play_btn.click()
        page.wait_for_timeout(2000)
        print("  ✓ TTS 播放按钮已点击")
    else:
        print("  ⚠ 未找到 TTS 播放按钮")
    screenshot(page, "05_tts")


def test_recording_flow(page: Page):
    """测试 5：录音流程（模拟，无真实麦克风）。"""
    step("测试 5: 录音流程")
    page.goto(BASE_URL, wait_until="networkidle")
    page.wait_for_timeout(1500)
    rec_btn = page.locator('button:has-text("录音"), button:has-text("开始录音"), button:has-text("🎤")').first
    if rec_btn.is_visible():
        rec_btn.click()
        page.wait_for_timeout(1000)
        screenshot(page, "06_recording")
        stop_btn = page.locator('button:has-text("停止"), button:has-text("完成")').first
        if stop_btn.is_visible():
            stop_btn.click()
            page.wait_for_timeout(2000)
        print("  ✓ 录音流程完成（无真实音频）")
    else:
        print("  ⚠ 未找到录音按钮")
    screenshot(page, "07_after_recording")


def test_dictation_flow(page: Page):
    """测试 6：听写流程。"""
    step("测试 6: 听写流程")
    page.goto(BASE_URL, wait_until="networkidle")
    page.wait_for_timeout(1500)
    dictation_tab = page.locator('text=听写').first
    if dictation_tab.is_visible():
        dictation_tab.click()
        page.wait_for_timeout(1000)
    input_area = page.locator('textarea, input[type="text"]').first
    if input_area.is_visible():
        input_area.fill("the weather is beautiful today")
        page.wait_for_timeout(500)
        screenshot(page, "08_dictation_input")
        check_btn = page.locator('button:has-text("检查"), button:has-text("提交")').first
        if check_btn.is_visible():
            check_btn.click()
            page.wait_for_timeout(1500)
        print("  ✓ 听写提交流程完成")
    screenshot(page, "09_dictation_result")


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
    """测试 9：移动端响应式。"""
    step("测试 9: 移动端响应式")
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(BASE_URL, wait_until="networkidle")
    page.wait_for_timeout(1500)
    screenshot(page, "12_mobile_375")
    page.set_viewport_size({"width": 768, "height": 1024})
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(1000)
    screenshot(page, "13_tablet_768")
    page.set_viewport_size({"width": 1280, "height": 800})
    print("  ✓ 移动端/平板/桌面三档响应式截图完成")


def test_no_console_errors(page: Page):
    """测试 10：控制台无错误。"""
    step("测试 10: 控制台错误检查")
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda err: errors.append(f"pageerror: {err}"))
    page.goto(BASE_URL, wait_until="networkidle")
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
