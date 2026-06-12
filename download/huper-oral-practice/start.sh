#!/bin/bash
# HuPER 口语练习平台 - 启动脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/backend"

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到 python3"
    exit 1
fi

# 安装依赖（如果需要）
if [ ! -f ".deps_installed" ]; then
    echo "安装依赖..."
    pip install -r requirements.txt
    touch .deps_installed
fi

# 设置模型路径（如果已有模型）
if [ -z "$HUPER_MODEL_PATH" ]; then
    # 尝试常见路径
    for path in \
        "$SCRIPT_DIR/huper_onnx/model.onnx" \
        "$SCRIPT_DIR/model/model.onnx" \
        "$SCRIPT_DIR/../huper_onnx/model.onnx"; do
        if [ -f "$path" ]; then
            export HUPER_MODEL_PATH="$path"
            echo "找到模型: $path"
            break
        fi
    done
fi

if [ -z "$HUPER_MODEL_PATH" ]; then
    echo "⚠️  未找到 ONNX 模型，将以演示模式启动"
    echo "   设置环境变量 HUPER_MODEL_PATH 指定模型路径"
    echo "   例如: HUPER_MODEL_PATH=./model.onnx ./start.sh"
fi

echo ""
echo "========================================"
echo "  HuPER 口语练习平台"
echo "  访问: http://localhost:8000"
echo "========================================"
echo ""

python3 main.py
