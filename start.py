#!/usr/bin/env python3
"""Phonos v3 一键启动脚本。

特性：
- 自动检查 Python 依赖
- 自动检查模型文件
- 启动后端服务
- 启动前端开发服务器（可选）
- 自动打开浏览器
- 显示访问地址与默认账号

用法：
    python start.py              # 启动后端 + 打开浏览器
    python start.py --with-v3    # 同时启动 v3 React 前端
    python start.py --check-only # 仅检查环境
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_V3_DIR = PROJECT_ROOT / "frontend-v3"
MODELS_DIR = PROJECT_ROOT / "models"


def color(msg: str, c: str) -> str:
    colors = {
        "green": "\033[92m", "yellow": "\033[93m", "red": "\033[91m",
        "blue": "\033[94m", "reset": "\033[0m", "bold": "\033[1m",
    }
    return f"{colors.get(c, '')}{msg}{colors['reset']}"


def step(msg: str):
    print(f"\n{color('▶', 'blue')} {color(msg, 'bold')}")


def check_python():
    """检查 Python 版本。"""
    step("检查 Python")
    if sys.version_info < (3, 10):
        print(color(f"  ✗ Python {sys.version}，需要 3.10+", "red"))
        return False
    print(color(f"  ✓ Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}", "green"))
    return True


def check_dependencies():
    """检查核心 Python 依赖。"""
    step("检查 Python 依赖")
    required = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "pydantic": "pydantic",
        "pydantic_settings": "pydantic-settings",
        "structlog": "structlog",
        "onnxruntime": "onnxruntime",
        "numpy": "numpy",
        "soundfile": "soundfile",
        "fsrs": "fsrs",
    }
    optional = {
        "bcrypt": "bcrypt",
        "librosa": "librosa",
        "edge_tts": "edge-tts",
        "aiohttp": "aiohttp",
        "scipy": "scipy",
    }

    missing_required = []
    for mod, pkg in required.items():
        try:
            __import__(mod)
            print(color(f"  ✓ {pkg}", "green"))
        except ImportError:
            print(color(f"  ✗ {pkg}（缺失）", "red"))
            missing_required.append(pkg)

    missing_optional = []
    for mod, pkg in optional.items():
        try:
            __import__(mod)
            print(color(f"  ✓ {pkg}", "green"))
        except ImportError:
            print(color(f"  ⚠ {pkg}（可选，缺失）", "yellow"))
            missing_optional.append(pkg)

    if missing_required:
        print(f"\n{color('安装缺失依赖:', 'yellow')}")
        print(f"  pip install {' '.join(missing_required + missing_optional)}")
        return False
    return True


def check_models():
    """检查模型文件。"""
    step("检查模型")
    checks = [
        (MODELS_DIR / "huper_onnx_int8_dynamic" / "model_quantized.onnx",
         "HuPER 音素识别（INT8）",
         "https://github.com/CyanXLab/CyanXLab/releases/tag/models-v3"),
        (MODELS_DIR / "silero_vad.onnx",
         "silero VAD",
         "https://github.com/snakers4/silero-vad"),
    ]

    all_ok = True
    for path, name, url in checks:
        if path.exists() and path.stat().st_size > 1000:
            size_mb = path.stat().st_size / 1024 / 1024
            print(color(f"  ✓ {name}: {path.name} ({size_mb:.1f} MB)", "green"))
        else:
            print(color(f"  ✗ {name}（缺失）", "yellow"))
            print(f"    下载: {url}")
            print(f"    放置: {path}")
            all_ok = False

    return all_ok


def check_env_file():
    """检查 .env 文件。"""
    step("检查配置文件")
    env_file = PROJECT_ROOT / ".env"
    env_example = PROJECT_ROOT / ".env.example"
    if not env_file.exists() and env_example.exists():
        shutil.copy(env_example, env_file)
        print(color(f"  ✓ 已从 .env.example 创建 .env", "green"))
    elif env_file.exists():
        print(color(f"  ✓ .env 已存在", "green"))
    else:
        print(color(f"  ⚠ 未找到 .env 或 .env.example", "yellow"))
    return True


def start_backend(host: str = "127.0.0.1", port: int = 8000):
    """启动后端服务。"""
    step(f"启动后端: http://{host}:{port}")
    cmd = [
        sys.executable, "-m", "uvicorn", "main:app",
        "--host", host, "--port", str(port),
        "--log-level", "info",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_DIR)
    proc = subprocess.Popen(
        cmd, cwd=str(BACKEND_DIR), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    # 等待启动
    for _ in range(30):
        line = proc.stdout.readline().decode(errors="replace")
        if line:
            print(f"  {line.rstrip()}")
        if "Uvicorn running" in line or "Application startup complete" in line:
            break
        if proc.poll() is not None:
            print(color("  ✗ 后端启动失败", "red"))
            return None
        time.sleep(0.5)
    print(color(f"  ✓ 后端已启动: http://{host}:{port}", "green"))
    return proc


def start_frontend_v3(host: str = "127.0.0.1", port: int = 5173):
    """启动 v3 React 前端。"""
    step(f"启动前端 v3: http://{host}:{port}")
    if not (FRONTEND_V3_DIR / "node_modules").exists():
        print(color("  安装前端依赖（首次需要 1-2 分钟）...", "yellow"))
        npm = shutil.which("npm")
        if not npm:
            print(color("  ✗ 未找到 npm，请先安装 Node.js", "red"))
            return None
        subprocess.run([npm, "install"], cwd=str(FRONTEND_V3_DIR), check=True)

    npm = shutil.which("npm")
    proc = subprocess.Popen(
        [npm, "run", "dev", "--", "--host", host, "--port", str(port)],
        cwd=str(FRONTEND_V3_DIR),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    for _ in range(20):
        line = proc.stdout.readline().decode(errors="replace")
        if line:
            print(f"  {line.rstrip()}")
        if "Local:" in line or "ready in" in line:
            break
        time.sleep(0.5)
    print(color(f"  ✓ 前端 v3 已启动: http://{host}:{port}", "green"))
    return proc


def open_browser(url: str):
    """打开浏览器。"""
    step(f"打开浏览器: {url}")
    try:
        webbrowser.open(url)
        print(color(f"  ✓ 已打开浏览器", "green"))
    except Exception as e:
        print(color(f"  ⚠ 无法自动打开浏览器: {e}", "yellow"))
        print(f"  请手动访问: {url}")


def show_info():
    """显示使用信息。"""
    step("使用信息")
    print(f"""
{color('Phonos v3 已启动', 'green')}

{color('访问地址:', 'bold')}
  - 旧版前端:        http://127.0.0.1:8000
  - v3 React 前端:   http://127.0.0.1:5173  （如已启动）
  - API 文档:        http://127.0.0.1:8000/docs
  - 配置中心:        http://127.0.0.1:8000/api/config/

{color('默认账号:', 'bold')}
  首次访问会自动创建访客账号。也可注册新账号。
  密码要求: 至少 8 位，含大小写字母和数字。

{color('配置修改:', 'bold')}
  - 网页: 访问 http://127.0.0.1:8000/api/config/（需登录）
  - 文件: 编辑 .env 或 .env.runtime（网页修改的配置）

{color('停止服务:', 'bold')}
  按 Ctrl+C 停止所有服务。

{color('模型下载:', 'bold')}
  python backend/scripts/quantize_models.py
  或从云盘下载: https://github.com/CyanXLab/CyanXLab/releases
""")


def main():
    parser = argparse.ArgumentParser(description="Phonos v3 一键启动")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--with-v3", action="store_true", help="同时启动 v3 React 前端")
    parser.add_argument("--check-only", action="store_true", help="仅检查环境")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    print(color("=" * 60, "blue"))
    print(color("  Phonos v3 一键启动", "bold"))
    print(color("=" * 60, "blue"))

    if not check_python():
        sys.exit(1)

    if not check_dependencies():
        if not args.check_only:
            print(color("\n请先安装缺失依赖，再运行此脚本", "yellow"))
            sys.exit(1)

    check_env_file()
    models_ok = check_models()

    if args.check_only:
        if not models_ok:
            print(color("\n⚠ 模型未就绪，请先下载", "yellow"))
        else:
            print(color("\n✓ 环境检查通过", "green"))
        return

    if not models_ok:
        print(color("\n⚠ 模型未就绪，部分功能不可用（评测/听写评分）", "yellow"))
        print(color("  其他功能（上海考试 UI、配置中心、FSRS）仍可使用", "yellow"))
        resp = input("\n  是否继续启动？[Y/n] ").strip().lower()
        if resp == "n":
            return

    backend_proc = start_backend(args.host, args.port)
    if not backend_proc:
        sys.exit(1)

    frontend_proc = None
    if args.with_v3:
        frontend_proc = start_frontend_v3(args.port_v3 if hasattr(args, 'port_v3') else "5173")

    if not args.no_browser:
        time.sleep(1)
        open_browser(f"http://127.0.0.1:{args.port}")

    show_info()

    # 等待退出
    try:
        print(f"\n{color('服务运行中，按 Ctrl+C 停止...', 'blue')}")
        while True:
            time.sleep(1)
            if backend_proc.poll() is not None:
                print(color("后端进程退出", "yellow"))
                break
    except KeyboardInterrupt:
        print(f"\n{color('停止服务...', 'yellow')}")
        if frontend_proc:
            frontend_proc.terminate()
        if backend_proc:
            backend_proc.terminate()
        print(color("已停止", "green"))


if __name__ == "__main__":
    import argparse
    main()
