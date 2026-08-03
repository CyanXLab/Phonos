# ============================================================
# Phonos v3 Dockerfile（多阶段构建）
# ============================================================

# ---------- Stage 1: 构建阶段 ----------
FROM python:3.11-slim AS builder

WORKDIR /build

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ---------- Stage 2: 运行阶段 ----------
FROM python:3.11-slim

WORKDIR /app

# 运行时系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# 复制 Python 依赖
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app/backend

# 复制项目代码
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

# 创建数据/模型目录
RUN mkdir -p /app/models /app/data /app/logs

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=5)" || exit 1

# 暴露端口
EXPOSE 8000

# 环境变量（默认值，可通过 -e 覆盖）
ENV ENV=prod
ENV LOG_FORMAT=json
ENV LOG_LEVEL=INFO
ENV MODELS_DIR=/app/models

# 启动命令
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
