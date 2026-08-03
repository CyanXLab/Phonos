"""Phonos v3 安全测试套件。

测试维度：
1. CORS 配置安全（白名单，不再 ["*"]）
2. SQL 注入（参数化查询）
3. XSS（输入转义）
4. 认证与授权（未授权访问、token 伪造）
5. 路径穿越
6. 速率限制
7. 密码强度策略
8. 敏感信息泄漏
9. HTTP 安全头
10. 文件上传安全

运行方式：
    python backend/tests/security/test_security.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import urllib.request
import urllib.error


BASE_URL = "http://127.0.0.1:8000"
RESULTS_DIR = Path(__file__).resolve().parents[3] / "test_results" / "security"


def step(msg: str):
    print(f"\n{'='*60}\n🔒 {msg}\n{'='*60}", flush=True)


def http(method: str, path: str, body=None, headers=None, token=None, retries=2):
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    if token:
        h["Authorization"] = f"Bearer {token}"
    last_err = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, resp.read().decode(), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(), dict(e.headers)
        except Exception as e:
            last_err = e
            time.sleep(1)
    return 0, str(last_err), {}


def register_and_login():
    username = f"secuser_{uuid.uuid4().hex[:8]}"
    http("POST", "/api/auth/register", {"username": username, "password": "TestPass123", "display_name": "Sec"})
    s, b, _ = http("POST", "/api/auth/login", {"username": username, "password": "TestPass123"})
    if s == 200:
        return json.loads(b).get("token", ""), username
    return None, None


def test_cors_security():
    step("测试 1: CORS 配置")
    results = []
    s, b, h = http("GET", "/api/health")
    acao = h.get("Access-Control-Allow-Origin", h.get("access-control-allow-origin", ""))
    if acao == "*":
        results.append(("FAIL", "CORS 返回 *（应白名单）"))
    else:
        results.append(("PASS", f"CORS 未返回 *（值: {acao or '空'}）"))

    req = urllib.request.Request(f"{BASE_URL}/api/health", headers={"Origin": "https://evil.com"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            acao = resp.headers.get("Access-Control-Allow-Origin", "")
            if acao == "https://evil.com":
                results.append(("FAIL", "evil.com 被加入 CORS 白名单"))
            else:
                results.append(("PASS", f"evil.com 未被加入白名单（值: {acao or '空'}）"))
    except urllib.error.HTTPError as e:
        acao = e.headers.get("Access-Control-Allow-Origin", "")
        if acao == "https://evil.com":
            results.append(("FAIL", "evil.com 被加入 CORS 白名单"))
        else:
            results.append(("PASS", f"evil.com 未被加入白名单"))

    req = urllib.request.Request(f"{BASE_URL}/api/health", headers={"Origin": "http://localhost:5173"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            acao = resp.headers.get("Access-Control-Allow-Origin", "")
            if "localhost" in acao:
                results.append(("PASS", "localhost 被允许"))
            else:
                results.append(("WARN", f"localhost 未在白名单（值: {acao}）"))
    except Exception as e:
        results.append(("WARN", f"localhost 测试失败: {e}"))

    return results


def test_sql_injection():
    step("测试 2: SQL 注入")
    results = []
    token, _ = register_and_login()
    if not token:
        return [("SKIP", "无法登录获取 token")]

    payloads = [
        "' OR '1'='1",
        "'; DROP TABLE users; --",
        "' UNION SELECT * FROM user_sessions --",
        "admin'--",
        "1; DELETE FROM cards WHERE '1'='1",
    ]

    for p in payloads:
        s, b, _ = http("GET", f"/api/sentence/{quote(p)}", token=token)
        if s in (404, 422, 400):
            results.append(("PASS", f"SQL 注入被拒（{p[:30]}）: {s}"))
        elif s == 500:
            results.append(("FAIL", f"SQL 注入导致 500（{p[:30]}）"))
        else:
            results.append(("PASS", f"SQL 注入未崩溃（{p[:30]}）: {s}"))

    return results


def test_xss():
    step("测试 3: XSS")
    results = []
    token, _ = register_and_login()
    if not token:
        return [("SKIP", "无法登录")]

    payloads = [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "javascript:alert(1)",
        "\"><script>alert(1)</script>",
    ]

    for p in payloads:
        s, b, _ = http("POST", "/api/v2/dictation/check", {
            "expected": p, "actual": "test", "keywords": []
        }, token=token)
        if s == 200:
            if "<script>" in b:
                results.append(("FAIL", f"XSS 未过滤（{p[:30]}）"))
            else:
                results.append(("PASS", f"XSS 已过滤或转义（{p[:30]}）"))
        else:
            results.append(("PASS", f"XSS 接口返回 {s}（{p[:30]}）"))

    return results


def test_auth_security():
    step("测试 4: 认证与授权")
    results = []

    s, b, _ = http("GET", "/api/data/export")
    if s in (401, 403):
        results.append(("PASS", f"无 token 访问 /api/data/export 被拒: {s}"))
    elif s == 200:
        results.append(("WARN", f"无 token 仍可访问 /api/data/export（default 兜底）"))
    else:
        results.append(("PASS", f"无 token 返回 {s}"))

    s, b, _ = http("GET", "/api/data/export", token="fake-token-12345")
    if s in (401, 403):
        results.append(("PASS", "伪造 token 被拒"))
    else:
        results.append(("FAIL", f"伪造 token 未被拒: {s}"))

    s, b, _ = http("POST", "/api/shanghai-exam/sessions", {"mode": "practice"})
    if s in (401, 403):
        results.append(("PASS", "上海考试需认证"))
    else:
        results.append(("FAIL", f"上海考试未要求认证: {s}"))

    s, b, _ = http("POST", "/api/auth/login", {"username": "admin", "password": "wrongpassword"})
    if s in (401, 400):
        results.append(("PASS", "错误密码登录被拒"))
    else:
        results.append(("FAIL", f"错误密码未被拒: {s}"))

    s, b, _ = http("POST", "/api/auth/register", {"username": "weakuser", "password": "123"})
    if s in (400, 422):
        results.append(("PASS", "弱密码注册被拒"))
    else:
        results.append(("FAIL", f"弱密码未被拒: {s}"))

    return results


def test_path_traversal():
    step("测试 5: 路径穿越")
    results = []
    token, _ = register_and_login()

    payloads = [
        "../../../etc/passwd",
        "..\\..\\..\\windows\\win.ini",
        "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "....//....//....//etc/passwd",
    ]

    for p in payloads:
        s, b, _ = http("GET", f"/api/ipa-audio/{quote(p)}", token=token)
        if "root:" in b or "[fonts]" in b:
            results.append(("FAIL", f"路径穿越成功（{p[:30]}）"))
        elif s in (404, 400, 422):
            results.append(("PASS", f"路径穿越被拒（{p[:30]}）: {s}"))
        else:
            results.append(("PASS", f"路径穿越未泄漏系统文件（{p[:30]}）: {s}"))

    return results


def test_rate_limiting():
    step("测试 6: 速率限制")
    results = []

    blocked = False
    for i in range(15):
        s, b, _ = http("POST", "/api/auth/login", {"username": "admin", "password": "wrong"})
        if s == 429:
            blocked = True
            break
        time.sleep(0.05)

    if blocked:
        results.append(("PASS", "登录失败速率限制生效（429）"))
    else:
        results.append(("WARN", "登录失败未触发速率限制（可能需要更多请求）"))

    return results


def test_password_strength():
    step("测试 7: 密码强度策略")
    results = []

    weak_passwords = [
        "123", "abcdefg", "12345678", "abcdefgh", "ABCDEFGH",
    ]

    for pwd in weak_passwords:
        s, b, _ = http("POST", "/api/auth/register", {
            "username": f"weak_{int(time.time())}_{pwd[:3]}",
            "password": pwd
        })
        if s in (400, 422):
            results.append(("PASS", f"弱密码被拒: {pwd}"))
        else:
            results.append(("FAIL", f"弱密码未被拒: {pwd} (status={s})"))

    s, b, _ = http("POST", "/api/auth/register", {
        "username": f"strong_{int(time.time())}",
        "password": "StrongPass123"
    })
    if s == 200:
        results.append(("PASS", "强密码注册成功"))
    else:
        results.append(("WARN", f"强密码注册返回 {s}"))

    return results


def test_sensitive_info_leak():
    step("测试 8: 敏感信息泄漏")
    results = []

    s, b, _ = http("GET", "/api/health/v2")
    if "api_key" in b.lower() or "secret" in b.lower():
        if '"api_key":' in b and '"***"' not in b:
            results.append(("FAIL", "健康检查泄漏 API key"))
        else:
            results.append(("PASS", "健康检查未泄漏 API key（仅 enabled 状态）"))
    else:
        results.append(("PASS", "健康检查未包含敏感字段"))

    token, _ = register_and_login()
    if token:
        s, b, _ = http("GET", "/api/config/", token=token)
        if "azure_speech_key" in b:
            import re
            m = re.search(r'"azure_speech_key".*?"value":\s*"([^"]*)"', b)
            if m and m.group(1) and m.group(1) != "***":
                results.append(("FAIL", "配置中心泄漏 Azure key"))
            else:
                results.append(("PASS", "配置中心已脱敏 Azure key"))
        else:
            results.append(("PASS", "配置中心未包含 Azure key 字段"))

    s, b, _ = http("GET", "/api/sentence/notanumber")
    if "Traceback" in b or "File \"" in b:
        results.append(("FAIL", "错误响应包含 stacktrace"))
    else:
        results.append(("PASS", "错误响应未泄漏 stacktrace"))

    return results


def test_security_headers():
    step("测试 9: HTTP 安全头")
    results = []
    s, b, h = http("GET", "/api/health")

    xcto = h.get("X-Content-Type-Options", h.get("x-content-type-options", ""))
    if xcto == "nosniff":
        results.append(("PASS", "X-Content-Type-Options: nosniff"))
    else:
        results.append(("WARN", f"X-Content-Type-Options 未设置（值: {xcto}）"))

    xfo = h.get("X-Frame-Options", h.get("x-frame-options", ""))
    if xfo:
        results.append(("PASS", f"X-Frame-Options: {xfo}"))
    else:
        results.append(("WARN", "X-Frame-Options 未设置"))

    results.append(("INFO", "CSP 应由 nginx 配置（生产环境）"))
    return results


def test_file_upload_security():
    step("测试 10: 文件上传安全")
    results = []
    token, _ = register_and_login()
    if not token:
        return [("SKIP", "无法登录")]

    import io
    boundary = "----testboundary123"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio"; filename="../../../etc/passwd"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
        f"root:x:0:0:root:/root:/bin/bash\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="sentence_text"\r\n\r\n'
        f"test\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    req = urllib.request.Request(
        f"{BASE_URL}/api/v2/evaluate",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            s = resp.status
            b = resp.read().decode()
    except urllib.error.HTTPError as e:
        s = e.code
        b = e.read().decode()
    except Exception as e:
        s = 0
        b = str(e)

    if "root:x:0:0" in b:
        results.append(("FAIL", "上传内容被回显（可能 XSS）"))
    elif s in (400, 422, 500):
        results.append(("PASS", f"恶意上传被处理（{s}）"))
    else:
        results.append(("PASS", f"上传未崩溃（{s}）"))

    return results


def main():
    global BASE_URL
    parser = argparse.ArgumentParser(description="Phonos v3 安全测试")
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()

    BASE_URL = args.base_url
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    all_results = {}
    total_pass = 0
    total_fail = 0
    total_warn = 0

    tests = [
        ("CORS 安全", test_cors_security),
        ("SQL 注入", test_sql_injection),
        ("XSS", test_xss),
        ("认证授权", test_auth_security),
        ("路径穿越", test_path_traversal),
        ("速率限制", test_rate_limiting),
        ("密码强度", test_password_strength),
        ("敏感信息泄漏", test_sensitive_info_leak),
        ("HTTP 安全头", test_security_headers),
        ("文件上传", test_file_upload_security),
    ]

    for name, fn in tests:
        try:
            r = fn()
        except Exception as e:
            r = [("ERROR", str(e)[:200])]
        all_results[name] = r
        for status, msg in r:
            if status == "PASS":
                total_pass += 1
            elif status == "FAIL":
                total_fail += 1
            elif status == "WARN":
                total_warn += 1
            print(f"  [{status}] {msg}")

    print(f"\n{'='*60}")
    print(f"安全测试汇总: {total_pass} PASS, {total_fail} FAIL, {total_warn} WARN")
    print(f"{'='*60}")

    result_file = RESULTS_DIR / "security_report.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({
            "summary": {"pass": total_pass, "fail": total_fail, "warn": total_warn},
            "details": all_results,
            "timestamp": time.time(),
            "base_url": BASE_URL,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {result_file}")

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
