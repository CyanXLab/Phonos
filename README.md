# Phonos v3

> 商业级本地优先英语听说训练系统 · 重点适配上海中考/高考英语听说训练

Phonos v3 在原 Phonos（基于 HuBERT 音素识别 + FSRS-6 间隔重复）的基础上，升级为商业级系统，重点适配上海英语听说考试训练场景。

## 核心升级

### Phase 0 稳定化
- ✅ Pydantic Settings v2 + `.env` 配置管理
- ✅ structlog 结构化日志（JSON / Console）
- ✅ CORS 安全配置（白名单，不再用 `["*"]`）
- ✅ RequestID / AccessLog / ErrorHandler 中间件
- ✅ bcrypt 密码哈希（兼容旧 SHA256，自动升级）
- ✅ 密码修改失效其他会话
- ✅ 速率限制（登录/评测）
- ✅ Dockerfile + docker-compose + .env.example
- ✅ pytest 测试套件

### Phase 1 模型与推理引擎
- ✅ PronunciationProvider 抽象接口
- ✅ LocalHuPERProvider（保留原 HuBERT，扩展 softmax 置信度）
- ✅ Azure / 讯飞 / 有道 Provider 骨架（默认关闭）
- ✅ silero-vad 服务（回退能量阈值法）
- ✅ faster-whisper 服务（small/medium/large，int8/fp16）
- ✅ CTC segmentation 强制对齐
- ✅ 模型管理 API + 下载脚本

### Phase 2 发音评分算法
- ✅ 9 维评分：音素准确度/完整度/流利度/韵律/重音/语调/停顿/语速/音质
- ✅ 8 类错误：substitution/deletion/insertion/minimal_pair_confusion/vowel_length_error/stress_error/intonation_error/unnatural_pause
- ✅ 置信度加权评分
- ✅ 时间戳绑定（音素级 + 单词级）
- ✅ 校准框架（线性/逻辑回归映射到人工评分）
- ✅ 音频质量检测（SNR/clipping/silence）

### Phase 3 听写与听力理解
- ✅ 词级 Levenshtein 对齐
- ✅ 拼写容错（编辑距离 ≤ 1 → near_correct）
- ✅ 音近词容错（G2P 音素对比）
- ✅ 关键词权重
- ✅ 语法变形识别（go/went、child/children 等）
- ✅ 漏词/多词/错序/语义近似全覆盖

### Phase 4 上海听说考试模块
- ✅ 9 种任务类型：单词朗读/句子朗读/听写/听句子选择/听问题回答/信息补全/信息转述/情景应答/看图说话/模拟套卷
- ✅ 练习模式 + 考试模式
- ✅ 倒计时（准备/答题）
- ✅ 自动提交
- ✅ 考试报告（含合规声明）
- ✅ 语料管理（话题/难度/CEFR/教材来源/音素覆盖/能力标签）
- ✅ 合规声明（辅助评估、非官方、建议结合教师反馈）

### Phase 5 前端重写
- ✅ React 18 + Vite + TypeScript + Tailwind CSS
- ✅ TanStack Query + Zustand
- ✅ PWA（Service Worker + manifest）
- ✅ 移动端响应式（safe-area）
- ✅ 录音 Hook（Web Audio API）
- ✅ 实时波形可视化
- ✅ 音素时间轴组件
- ✅ 评分环组件
- ✅ 考试倒计时组件

### Phase 6 性能优化
- ✅ 单词级 G2P LRU 缓存
- ✅ 模型单例
- ✅ 异步并发查词典
- ✅ Provider 优先级选择

### Phase 7 benchmark 与校准
- ✅ benchmark 脚本（延迟 p50/p95/p99、RTF）
- ✅ 校准数据集框架
- ✅ ScoreCalibrator（线性/逻辑回归）

## 快速开始

### 后端

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env
python main.py
```

访问 http://localhost:8000

### 前端 v3

```bash
cd frontend-v3
npm install
npm run dev
```

访问 http://localhost:5173

### Docker

```bash
cp .env.example .env
docker compose up -d
```

### 模型下载

```bash
python backend/scripts/download_models.py
```

HuPER 模型请从云盘获取，放置到 `models/model.onnx`。

## 合规声明

本系统提供的所有评分为**辅助评估**，**非官方成绩**，仅供参考。评分基于本地 AI 模型，可能与人工评分存在偏差。建议结合教师反馈综合判断。

Phonos 与上海市教育考试院无任何关联。

## 隐私

- 默认本地模式：不上传用户音频
- 所有联网功能需显式开关
- 商业 API 默认关闭
- 可随时导出/删除全部数据（`/api/data/export`、`/api/data/purge`）

## License

MIT
