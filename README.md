# Phonos - 英语口语练习平台

> 基于 AI 语音识别 (HuPER-Recognizer) + FSRS 间隔重复算法的英语发音评测与词汇记忆平台

Phonos 是一款面向中文学习者的英语口语练习工具，融合语言学（最小对立对、ARPAbet/IPA 双音标、词组搭配）与认知科学（FSRS-4.5 间隔重复、主动回忆、错误模式追踪、自适应难度）理念，帮助用户系统性地提升英语发音和词汇记忆。

**核心特色**：不是简单的朗读打分，而是从音素级别精准定位发音问题，结合间隔重复算法科学安排复习，形成「评测 → 诊断 → 练习 → 复习」的完整闭环。

---

## 目录

- [功能概览](#功能概览)
- [快速开始](#快速开始)
- [项目架构](#项目架构)
- [核心模块详解](#核心模块详解)
- [API 文档](#api-文档)
- [数据库设计](#数据库设计)
- [配置说明](#配置说明)
- [部署指南](#部署指南)
- [技术栈](#技术栈)
- [浏览器兼容性](#浏览器兼容性)
- [常见问题](#常见问题)
- [License](#license)

---

## 功能概览

### 发音评测

Phonos 的发音评测不是简单的"整体打分"，而是深入到每个音素级别进行精细分析：

- **三维评分体系**：综合发音准确度(55%)、完整度(25%)、流利度(20%)三个维度计算总分，比单一维度评分更科学
  - **准确度**：基于动态规划音素对齐，逐音素对比用户发音与标准发音，计算相似度加权得分
  - **完整度**：检测用户是否遗漏了音素（如把 "three" 读成 "tree"），衡量发音的完整性
  - **流利度**：分析语速、停顿次数和停顿时长，评估说话的自然程度

- **音素级诊断**：评测结果精确定位到每个错误的音素，告知用户"你把 /θ/ 发成了 /s/"，而非笼统地说"发音不准"
- **音素相似度矩阵**：区分"接近的错误"（如 /ɪ/ → /iː/，轻微偏差）和"严重的错误"（如 /θ/ → /f/，完全替代），给予不同权重的扣分
- **最小对立对检测**：自动识别中国学习者最常混淆的 12 对音素，如：
  - L/R 混淆（light → right）
  - TH/S 混淆（think → sink）
  - V/W 混淆（vine → wine）
  - SH/S 混淆（she → see）

- **44 音素完整指南**：每个英语音素都有详细的发音指导，包含：
  - 常见错误及原因分析
  - 纠正方法和练习技巧
  - 口型要点（舌位、唇形）
  - 练习词汇列表

- **IPA 可点击发音**：点击音标即可听到该音素的标准人声录音（来自维基百科 IPA 音频库），无需猜测音标怎么读

### 听写模式

听写是提高听力和拼写能力的有效方法，Phonos 提供了完整的听写练习流程：

- **先听后写**：系统先通过 TTS 播放句子，用户在输入框中逐词听写
- **三档倍速控制**：0.5x / 0.75x / 1x 三种语速，初学者可从慢速开始
- **Levenshtein 编辑距离算法**：智能对比用户的听写结果与原文，避免级联错误（一个错位导致后续全部标错）
- **跳过听写**：如果只想练口语，可以一键跳过听写直接进入发音练习
- **自动隐藏原文**：听写模式下自动隐藏英文原文，防止偷看
- **错误单词自动追踪**：听写错误的单词会被记录，自动进入单词复习队列

### 双学习模式

- **顺序模式**：按 `sentences.json` 中的 ID 顺序逐句学习
  - 适合系统学习，从简单到复杂逐步推进
  - 支持手动指定 ID 范围（如从第 10 句开始到第 50 句）
  - 页面刷新后自动记住上次的进度位置
  - 句子数据更新时自动检测变更，提示用户重新指定起始位置

- **智能模式**：基于 FSRS + 薄弱分析 + 难度自适应的综合推荐
  - 优先推荐到期复习的句子（FSRS 调度）
  - 如果没有到期复习，基于薄弱音素推荐针对性练习
  - 根据历史表现动态调整推荐难度（easy → medium → hard）
  - 结合 FSRS 卡片难度、记忆稳定性、薄弱项重叠度综合打分排序

- **一键切换**：页面头部即可切换模式，选择自动保存到本地

### 智能学习系统

- **薄弱音素分析**：自动追踪用户在每个音素上的错误率，识别高频错误音素，生成薄弱项画像
- **自适应难度**：根据历史表现动态调整推荐句子难度。连续高分则提升难度，连续低分则降低难度
- **针对性练习推荐**：基于薄弱项推荐包含目标音素/单词的练习句子，确保练习有针对性
- **FSRS 评分驱动推荐**：智能模式结合 FSRS 卡片难度、记忆稳定性、薄弱项重叠度综合打分，选出最优的下一句
- **学习趋势分析**：得分趋势图、连续学习天数、每日练习量统计，让学习效果可视化
- **单词掌握追踪**：追踪每个单词的练习次数、最高分、平均分，判断是否已掌握

### 单词复习

- **FSRS 单词复习队列**：练习过的句子中的所有单词都会自动创建 FSRS 卡片（每个新出现的单词都记录，但不重复）；听写错误和发音错误（准确度 < 60%）的单词会被标记为错误单词，优先进入复习
- **逐个推荐**：每次只展示一个单词，用户评级后再推荐下一个，符合间隔重复的"主动回忆"原则
- **4 级评级**：忘了(Again) / 难(Hard) / 模糊(Good) / 会了(Easy)，驱动 FSRS 间隔重复调度
- **掌握度分类**：
  - **已掌握**：FSRS 状态为 REVIEW 且未到期且间隔≥3天（记忆稳定，短期内无需复习）
  - **待复习**：所有非已掌握且非新词的卡片 = LEARNING + RELEARNING + REVIEW到期 + REVIEW间隔<3天
  - **新词**：从未复习过的 FSRS 新卡片
- **错误追踪**：自动记录听写错误和发音错误，分别计数
- **单词详情卡片**：展示 IPA 音标、中文释义、词性、错误次数等完整信息

### 单词独立练习

独立于句子练习的单词级练习模式，包含三个标签页：

- **🎤 跟读练习**：只推荐经常读错的单词
  - 听单词发音 → 跟读录音 → 自动评分发音 → FSRS 自动评级 → 推荐下一个单词
  - 自动评级：发音分数 ≥90% → Easy, ≥70% → Good, ≥50% → Hard, <50% → Again
  - 无需手动评级按钮，系统根据发音评分自动 FSRS 评级

- **✏️ 听写练习**：只推荐经常听写错误的单词
  - 听单词发音 → 输入拼写 → 自动检查 → FSRS 自动评级 → 推荐下一个单词
  - 自动评级：完全正确 → Easy, 近似正确(相似度≥80%) → Good, 部分正确(≥60%) → Hard, 完全错误 → Again
  - 字符级 Levenshtein 编辑距离算法，容错判定

- **📊 错误统计**：查看经常读错和听写错误的单词列表，按错误次数排序

- **独立队列**：跟读和听写有独立的复习队列，不会互相干扰，但数据是同步的（共享同一套 FSRS 卡片）
- **FSRS 驱动**：错误次数多、FSRS 难度高的单词优先推荐，已掌握的自动跳过

### 用户认证

- **注册/登录**：用户名 + 密码注册，密码使用 SHA256 + 随机盐值加密存储
- **会话管理**：UUID4 令牌，30 天有效期，存储在服务端 SQLite
- **跨设备同步**：所有学习数据（FSRS 状态、评测记录、薄弱项分析）存储在服务端数据库，跨浏览器自动同步
- **访客模式**：无需注册即可使用，数据保存为默认用户

### 词汇与翻译

- **ENDICT 动态词典**：内置 5 万高频英语词汇，包含英美音标、中文释义、词性
- **多级翻译回退**：6 级翻译服务按优先级依次尝试，确保总能得到翻译结果
- **ONNX 离线翻译**：在线 API 不可用时，自动切换至本地 Opus-MT Seq2Seq 模型
- **翻译缓存**：已翻译过的句子缓存到本地 JSON 文件，避免重复请求
- **延迟加载**：词典按需加载，启动速度快

---

## 快速开始

### 环境要求

- Python 3.10+
- 现代浏览器（Chrome 60+ / Firefox 55+ / Safari 14+ / Edge 79+）
- 麦克风（用于录音评测）
- **可选**：HuPER ONNX 模型文件（用于音素识别评测，没有时系统仍可运行其他功能）

### 1. 克隆项目

```bash
git clone <repository-url>
cd Phonos
```

### 2. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

依赖列表（共 17 个包）：

| 包 | 用途 |
|------|------|
| `fastapi` + `uvicorn` | Web 框架 + ASGI 服务器 |
| `python-multipart` | 文件上传支持 |
| `onnxruntime` | ONNX 模型推理（音素识别 + 翻译） |
| `numpy` | 数值计算 |
| `soundfile` + `librosa` | 音频读取与处理 |
| `g2p-en` | 英文文本→音素转换 (Grapheme-to-Phoneme) |
| `scipy` | 信号处理 |
| `pydub` | 音频格式转换 |
| `edge-tts` | 微软 Edge TTS 语音合成 |
| `pyttsx3` | 本地离线 TTS（桌面环境备用） |
| `aiohttp` | 异步 HTTP 客户端 |
| `optimum[onnxruntime]` | ONNX 翻译模型加载 |
| `transformers` + `sentencepiece` + `sacremoses` | 翻译模型 tokenizer |

### 3. 放置模型（可选）

将 HuPER ONNX 模型文件放到项目根目录的 `models/` 文件夹中：

```
Phonos/
├── models/
│   ├── model.onnx              ← HuPER 音素识别模型
│   └── onnx_quant/             ← ONNX 翻译模型（可选，用于离线翻译）
├── backend/
├── frontend/
└── README.md
```

> **HuPER 模型**：基于 WavLM-Large + CTC 的音素识别模型，ONNX 格式。推荐使用量化版本（`model_quantized.onnx`）以降低推理延迟。
>
> **翻译模型**：Opus-MT-en-zh 的 ONNX 导出版本，需包含 `*.onnx` 文件和 tokenizer 配置（`source.spm`、`vocab.json` 等）。没有翻译模型时，系统自动回退到在线 API 或简易词典。

### 4. 启动服务

```bash
cd backend
python main.py
```

服务将在 `http://localhost:8000` 启动。

启动时控制台会输出：
```
[Phonos] Starting server...
[Phonos] ONNX recognizer: loaded (or: model not found, pronunciation evaluation disabled)
[Phonos] Dictionary: lazy-loaded (loaded on first query)
[Phonos] Translation cache: N entries loaded
[Phonos] Server running at http://localhost:8000
```

### 5. 访问应用

打开浏览器访问 http://localhost:8000

> 首次访问以访客身份登录，所有数据自动保存。如需跨设备同步，可注册账号。

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HUPER_MODEL_PATH` | `models/model.onnx` | HuPER ONNX 模型路径 |
| `PHONOS_TRANSLATE_MODEL_PATH` | `models/onnx_quant` | ONNX 翻译模型目录 |

```bash
# 示例：指定模型路径启动
HUPER_MODEL_PATH=/data/models/huper.onnx python main.py
```

---

## 项目架构

```
Phonos/
├── models/                          ← ONNX 模型文件（需手动放置）
│   ├── model.onnx                   # HuPER 音素识别模型
│   └── onnx_quant/                  # Opus-MT 翻译模型（可选）
├── backend/
│   ├── main.py                      # FastAPI 应用入口（1,875 行）
│   │                                #   - 30+ API 路由
│   │                                #   - 启动初始化逻辑
│   │                                #   - 音频评测、TTS、翻译等接口
│   ├── fsrs_db.py                   # FSRS-4.5 间隔重复引擎（653 行）
│   │                                #   - FSRSScheduler: 算法核心
│   │                                #   - FSRSDatabase: SQLite 持久化
│   │                                #   - 卡片状态机：NEW→LEARNING→REVIEW
│   ├── learning_algorithm.py        # 智能学习算法（895 行）
│   │                                #   - 薄弱音素分析
│   │                                #   - 自适应难度调整
│   │                                #   - 针对性练习推荐
│   │                                #   - 学习趋势与连续天数统计
│   ├── scoring.py                   # 三维评分算法（454 行）
│   │                                #   - 动态规划音素对齐
│   │                                #   - 音素相似度矩阵
│   │                                #   - 最小对立对检测
│   ├── phoneme_data.py              # 语言学数据（711 行）
│   │                                #   - 44 音素发音指南
│   │                                #   - 12 最小对立对
│   │                                #   - ARPAbet→IPA 映射表
│   │                                #   - 预设练习句子
│   ├── translate_service.py         # 翻译服务（477 行）
│   │                                #   - Edge Translator JWT 认证
│   │                                #   - MyMemory / Google 回退
│   │                                #   - ONNX 本地翻译
│   │                                #   - API 失败冷却机制
│   ├── tts_service.py               # TTS 语音合成（400 行）
│   │                                #   - edge-tts 多 voice 轮询
│   │                                #   - pyttsx3 本地回退
│   │                                #   - TTS 缓存机制
│   ├── auth_service.py              # 用户认证（308 行）
│   │                                #   - 注册/登录/登出
│   │                                #   - SHA256+盐值加密
│   │                                #   - UUID4 会话令牌
│   ├── dict_service.py              # 动态词典（233 行）
│   │                                #   - ENDICT 5万词词典
│   │                                #   - 延迟加载
│   ├── audio_processor.py           # 音频预处理（196 行）
│   │                                #   - 自动增益控制 (AGC)
│   │                                #   - 降噪处理
│   ├── onnx_service.py              # HuPER ONNX 推理（183 行）
│   ├── onnx_translate_service.py    # ONNX 翻译推理（186 行）
│   ├── g2p_service.py               # 文本→音素转换（132 行）
│   ├── sentences.json               # 100 句预设练习句子
│   │                                #   - 3 级难度（easy/medium/hard）
│   │                                #   - 25 个主题分类
│   │                                #   - 含翻译、关键短语、文化注释
│   ├── requirements.txt             # Python 依赖
│   ├── dict/endict/
│   │   └── common.json              # ENDICT 高频词典（5 万词）
│   └── ipa_audio/                   # 标准音素发音音频
│       ├── consonants/              # 22 个辅音录音
│       └── vowels/                  # 28 个元音录音
├── frontend/
│   ├── index.html                   # 主页面（424 行）
│   ├── style.css                    # UI 样式（1,141 行）
│   └── app.js                       # 前端逻辑（2,704 行）
└── README.md
```

**代码规模**：后端 ~6,700 行 Python + 前端 ~4,300 行 HTML/CSS/JS = 总计 ~11,000 行

---

## 核心模块详解

### FSRS-4.5 间隔重复算法

FSRS (Free Spaced Repetition Scheduler) 是一种基于记忆模型的科学间隔重复算法，Phonos 使用 FSRS-4.5 版本。

#### 卡片状态机

```
NEW(0) ──评级──→ LEARNING(1) ──Good/Easy──→ REVIEW(2)
                  │                           │
                  │    Again                   │ Again
                  ↓                           ↓
              RELEARNING(3) ──Good/Easy──→ REVIEW(2)
```

- **NEW**：从未复习过的新卡片
- **LEARNING**：初次学习中（Again/Hard 评级后进入）
- **REVIEW**：已学会，等待间隔重复复习（Good/Easy 评级后进入）
- **RELEARNING**：忘记后重新学习（REVIEW 状态下 Again 评级后进入）

#### 评级与调度

| 评级 | 含义 | 新卡片→状态 | 非新卡片→效果 |
|------|------|------------|-------------|
| 1 (Again) | 忘了 | → LEARNING | 稳定性降低，进入 RELEARNING |
| 2 (Hard) | 困难 | → LEARNING | 稳定性微增，仍需频繁复习 |
| 3 (Good) | 记得 | → REVIEW | 稳定性正常增长，标准间隔 |
| 4 (Easy) | 很容易 | → REVIEW | 稳定性大幅增长，延长间隔 |

#### 核心参数（18 个权重）

```python
DEFAULT_FSRS_PARAMS = [
    0.4072, 1.1829, 3.1262, 15.4722,  # w[0-3]: Again/Hard/Good/Easy 初始稳定性
    7.2102,                              # w[4]: 初始难度
    0.5316, 1.0651,                      # w[5-6]: 难度调整 + 均值回归
    0.0589, 0.3498, 1.1168,              # w[7-9]: 回忆稳定性增长
    0.5772, 0.1140, 0.4985, 0.2928,     # w[10-13]: 遗忘稳定性
    2.1207,                              # w[14]: 重组学习奖励
    0.0, 0.4506,                         # w[15-16]: Hard 惩罚 + Easy 加成
    0.8500                               # w[17]: 衰减因子
]
```

#### 可回忆率计算

```
R(t, S) = (1 + t / (9 × S))^(-1/decay)
```

其中 `t` = 距上次复习的天数，`S` = 记忆稳定性，`decay` = 衰减因子。目标可回忆率设定为 90%。

#### 复习队列策略

1. **优先到期复习**：先返回 FSRS 调度到期（`due ≤ now`）的复习卡片
2. **补充新卡片**：如果没有到期复习，从新卡片池中按创建时间顺序补充
3. **每日新卡片上限**：默认每天最多引入 5 张新卡片，避免学习负担过重

### 三维评分算法

评分基于动态规划 (DP) 的音素对齐算法，核心流程如下：

```
用户录音 → AGC + 降噪 → HuPER ONNX 推理 → 音素序列
                                                    ↓
标准文本 → G2P 转换 → 标准音素序列 ────────→ DP 对齐 → 逐音素对比
                                                    ↓
                                          准确度 / 完整度 / 流利度
```

1. **准确度 (55%)**：每个对齐的音素对计算相似度，加权平均
2. **完整度 (25%)**：标准音素被正确发音的比例（检测遗漏）
3. **流利度 (20%)**：基于语速和停顿的流利程度评估

### 翻译服务回退链

翻译服务采用 6 级回退策略，确保在任何网络环境下都能提供翻译：

```
┌──────────────────────────────────────────────────┐
│ 1. 本地缓存                                       │
│    ↑ 命中即返回，零延迟                            │
├──────────────────────────────────────────────────┤
│ 2. Microsoft Edge Translator                      │
│    JWT 认证 + 官方 API，质量最高                    │
├──────────────────────────────────────────────────┤
│ 3. MyMemory Translation API                       │
│    免费，每天 5K 字符匿名额度                       │
├──────────────────────────────────────────────────┤
│ 4. Google Translate                               │
│    需安装 googletrans，可能不稳定                    │
│    ↳ 连续失败 ≥ 3 次 → 5 分钟冷却期                │
├──────────────────────────────────────────────────┤
│ 5. ONNX 本地翻译 (Opus-MT)                        │
│    完全离线，Seq2Seq + ONNX Runtime                │
├──────────────────────────────────────────────────┤
│ 6. 简易词典回退                                    │
│    功能词翻译，实词保留英文                          │
└──────────────────────────────────────────────────┘
```

**冷却机制**：在线 API 连续失败 3 次后，自动进入 5 分钟冷却期，期间直接使用 ONNX 本地翻译，避免反复等待超时。

### TTS 语音合成

TTS 同样采用多级回退：

1. **浏览器 Web Speech API**（零延迟，无需服务器）
2. **edge-tts**（微软 Edge TTS，高质量在线语音）
   - 多 voice 轮询（AriaNeural → JennyNeural → GuyNeural → DavisNeural）
   - 单个 voice 被 403 封禁时自动切换下一个
   - 生成结果缓存到本地文件
3. **pyttsx3**（本地离线 TTS，桌面环境备用）
4. **静音占位**（所有 TTS 均失败时的兜底）

### 智能学习算法

智能学习算法模块 (`learning_algorithm.py`) 包含以下核心功能：

1. **薄弱音素分析**：统计用户在每个音素上的错误率，按错误率从高到低排序，生成薄弱项画像
2. **自适应难度调整**：
   - 连续 3 次评分 ≥ 80 分 → 提升难度 (easy → medium → hard)
   - 连续 3 次评分 < 50 分 → 降低难度
   - 否则维持当前难度
3. **针对性推荐**：从句子库中筛选包含用户薄弱音素的句子，优先推荐
4. **学习分析**：
   - 得分趋势（最近 N 次评测的平均分变化）
   - 连续学习天数（每天至少评测 1 次即计入）
   - 每日/每周练习量统计

---

## API 文档

所有 API 路径以 `/api` 为前缀，服务地址 `http://localhost:8000`。

### 基础接口

#### `GET /api/health`

健康检查。

**响应**：
```json
{ "status": "ok" }
```

#### `GET /api/sentence`

获取一个推荐句子（FSRS 优先返回到期复习的句子，否则随机）。

**响应**：
```json
{
  "id": 1,
  "text": "The weather is beautiful today",
  "translation": "今天天气真好",
  "difficulty": "easy",
  "category": "daily",
  "phonemes": ["DH", "AH", "W", "EH", "DH", "ER", ...],
  "ipa": "ðə wɛðər ɪz bjuːtəfəl tədeɪ",
  "words": [
    { "word": "the", "arpabet": "DH AH", "ipa": "ðə" },
    { "word": "weather", "arpabet": "W EH DH ER", "ipa": "wɛðər" },
    ...
  ],
  "key_phrases": [...],
  "cultural_note": "...",
  "fsrs": {
    "state": "new",
    "reps": 0,
    "due": "...",
    "scheduled_days": 0
  }
}
```

#### `GET /api/sentences`

获取所有句子列表（基本信息，不含音素数据）。

#### `GET /api/sentence/{id}`

按 ID 获取句子的完整详情（含音素、IPA、关键短语等）。

#### `GET /api/dict/{word}`

异步查词。先查本地 ENDICT 词典，查不到则通过翻译 API 获取。

**响应**：
```json
{
  "word": "beautiful",
  "phonetic": "/ˈbjuːtɪfəl/",
  "definitions": [
    { "pos": "adj", "meaning": "美丽的，漂亮的" }
  ]
}
```

#### `GET /api/minimal-pairs`

获取 12 对最小对立对数据。

#### `GET /api/phoneme-tips`

获取 44 个音素的发音指南。

#### `GET /api/ipa-audio/{arpabet}`

获取指定音素的标准发音音频文件（MP3）。

**参数**：`arpabet` - ARPAbet 音素代码，如 `TH`, `R`, `AE`

#### `POST /api/evaluate`

上传录音进行发音评测。

**请求**：`multipart/form-data`
- `audio`: 音频文件（WebM/WAV）
- `sentence_id`: 句子 ID

**响应**：
```json
{
  "overall_score": 78.5,
  "pronunciation_score": 82.0,
  "completeness_score": 90.0,
  "fluency_score": 60.0,
  "errors": [
    {
      "expected": "TH",
      "actual": "S",
      "error_type": "substitution",
      "position": 0,
      "similarity": 0.3,
      "is_minimal_pair": true,
      "minimal_pair_detail": { "pair": "TH/S", "tip": "..." }
    }
  ],
  "word_results": [...]
}
```

#### `GET /api/tts`

获取句子的 TTS 语音文件。

**参数**：
- `text` (query): 要合成的文本
- `voice` (query, 可选): 指定语音名称

#### `GET /api/tts/phoneme`

获取单个音素的 TTS 音频。

#### `POST /api/dictation/check`

听写结果对比检查。

**请求**：
```json
{
  "sentence_id": 1,
  "user_input": "the weather is beautiful today"
}
```

**响应**：
```json
{
  "correct": true,
  "score": 100,
  "words": [
    { "expected": "the", "actual": "the", "correct": true },
    { "expected": "weather", "actual": "whether", "correct": false, "similarity": 0.8 }
  ]
}
```

#### `GET /api/translate`

翻译指定文本。

**参数**：
- `text` (query): 要翻译的英文文本

**响应**：
```json
{
  "original": "The weather is beautiful today",
  "translation": "今天天气真好",
  "source": "edge",
  "online_api_skipped": false
}
```

#### `GET /api/translate/status`

获取翻译服务状态。

### FSRS 间隔重复接口

#### `POST /api/fsrs/review`

对句子进行 FSRS 复习评级。

**请求**：
```json
{
  "card_id": "sentence_1",
  "rating": 3,
  "card_type": "sentence"
}
```

**响应**：
```json
{
  "card_id": "sentence_1",
  "rating": 3,
  "state": 2,
  "state_name": "review",
  "difficulty": 4.52,
  "stability": 3.13,
  "retrievability": 0.95,
  "scheduled_days": 3.1,
  "due": "2025-01-16T10:30:00",
  "reps": 1,
  "lapses": 0
}
```

#### `GET /api/fsrs/queue`

获取 FSRS 复习队列（到期复习 + 新卡片）。

**参数**：
- `card_type` (query, 可选): `sentence` 或 `word`，默认 `sentence`
- `new_per_day` (query, 可选): 每日新卡片上限，默认 5

#### `GET /api/fsrs/stats`

获取学习统计。

**响应**：
```json
{
  "total_cards": 52,
  "new": 10,
  "learning": 5,
  "review": 30,
  "relearning": 7,
  "due_now": 3,
  "total_reviews": 128,
  "today_reviews": 12,
  "today_avg_rating": 3.2
}
```

#### `GET /api/fsrs/next`

获取 FSRS 推荐的下一个句子。

#### `GET /api/fsrs/due-count`

获取待复习数量。

**参数**：
- `card_type` (query, 可选): `sentence` 或 `word`

#### `POST /api/fsrs/ensure`

批量创建 FSRS 卡片（如果不存在）。

**请求**：
```json
{
  "card_ids": ["sentence_1", "sentence_2"],
  "card_type": "sentence"
}
```

### 用户认证接口

#### `POST /api/auth/register`

用户注册。

**请求**：
```json
{
  "username": "learner",
  "password": "my-password",
  "display_name": "学习者"
}
```

#### `POST /api/auth/login`

用户登录。

**请求**：
```json
{
  "username": "learner",
  "password": "my-password"
}
```

**响应**：
```json
{
  "token": "uuid4-token",
  "user": {
    "id": "user_123",
    "username": "learner",
    "display_name": "学习者",
    "avatar_color": "#4f46e5"
  }
}
```

#### `POST /api/auth/logout`

用户登出（使当前令牌失效）。

**请求头**：`Authorization: Bearer <token>`

#### `GET /api/auth/me`

获取当前用户信息。

#### `PUT /api/auth/profile`

更新用户资料（显示名称等）。

#### `PUT /api/auth/password`

修改密码。

### 智能学习接口

#### `GET /api/learning/weakness-profile`

获取用户薄弱项分析。

**响应**：
```json
{
  "weak_phonemes": [
    { "phoneme": "TH", "error_rate": 0.65, "attempts": 20, "tip": "..." },
    { "phoneme": "R", "error_rate": 0.45, "attempts": 18, "tip": "..." }
  ],
  "weak_words": [
    { "word": "three", "error_rate": 0.7, "attempts": 5 }
  ]
}
```

#### `GET /api/learning/recommendations`

获取针对性练习推荐。

#### `GET /api/learning/adaptive-next`

获取自适应难度推荐的下一句。

#### `GET /api/learning/analytics`

获取详细学习分析（趋势、连续天数、每日练习量）。

#### `GET /api/stats`

获取用户完整统计（评测数据 + FSRS 状态 + 薄弱项 + 单词掌握度）。

**响应**：
```json
{
  "total_evaluations": 45,
  "avg_score": 72.5,
  "today_evaluations": 5,
  "streak_days": 3,
  "fsrs": { "due_sentences": 3, "due_words": 8 },
  "word_mastery": {
    "mastered": 15,
    "due": 8,
    "learning": 20,
    "new": 9,
    "total": 52
  },
  "weakness_profile": { ... }
}
```

#### `POST /api/learning/record-evaluation`

记录评测结果（用于薄弱分析和自适应难度）。

### 学习模式接口

#### `GET /api/mode/sequential/next`

获取顺序模式的下一句。

**参数**：
- `start_id` (query, 可选): 起始句子 ID
- `end_id` (query, 可选): 结束句子 ID

#### `POST /api/mode/sequential/set-range`

设置顺序模式的 ID 范围。

**请求**：
```json
{
  "start_id": 10,
  "end_id": 50
}
```

#### `GET /api/mode/smart/next`

获取智能模式的下一句（FSRS + 薄弱 + 自适应综合推荐）。

#### `GET /api/mode/status`

获取当前学习模式状态（含句子数据变更检测）。

**响应**：
```json
{
  "mode": "sequential",
  "sequential": {
    "start_id": 10,
    "end_id": 50,
    "current_id": 15,
    "data_hash": "abc123"
  },
  "data_changed": false
}
```

### 单词复习接口

#### `GET /api/words/review-queue`

获取单词复习队列（FSRS 到期 + 错误单词）。

**参数**：
- `limit` (query, 可选): 返回数量上限，默认 20

#### `GET /api/words/next-review`

获取 FSRS 推荐的下一个复习单词（逐个推荐）。

**响应**：
```json
{
  "word": "beautiful",
  "card_id": "word_beautiful",
  "type": "review",
  "state": 2,
  "state_name": "review",
  "difficulty": 5.2,
  "stability": 3.8,
  "retrievability": 0.85,
  "reps": 4,
  "scheduled_days": 2.5,
  "word_info": {
    "ipa": "/ˈbjuːtɪfəl/",
    "definition": "adj. 美丽的",
    "dictation_errors": 1,
    "pronunciation_errors": 0
  }
}
```

#### `POST /api/words/review`

对单词进行复习评级。

**请求**：
```json
{
  "word": "beautiful",
  "rating": 3
}
```

#### `GET /api/words/errors`

获取所有错误单词（含听写/发音分类）。

#### `POST /api/dictation/record-errors`

记录听写错误单词。

**请求**：
```json
{
  "sentence_id": 1,
  "errors": ["weather", "beautiful"]
}
```

#### `GET /api/words/error-stats`

获取单词错误统计（按类型分组，含 FSRS 状态）。

**响应**：
```json
{
  "pronunciation_errors": [
    { "word": "thought", "ipa": "θɔt", "meaning": "想", "pronunciation_errors": 3, "fsrs_state": "learning" }
  ],
  "dictation_errors": [
    { "word": "beautiful", "ipa": "ˈbjuːtɪfəl", "meaning": "美丽的", "dictation_errors": 2, "fsrs_state": "new" }
  ],
  "summary": { "total_pron_errors": 5, "total_dict_errors": 3, "total_unique_errors": 6 }
}
```

#### `GET /api/words/practice-next?mode=all|pronunciation|dictation`

获取下一个练习单词（FSRS 自动推荐，支持按错误类型过滤）。

**参数**：
- `mode`: 练习模式
  - `all`（默认）: 所有未掌握单词
  - `pronunciation`: 仅读错过的单词
  - `dictation`: 仅听写错过的单词

**响应**：
```json
{
  "word": "thought",
  "type": "error_review",
  "card_id": "word_thought",
  "fsrs_state": "learning",
  "fsrs_difficulty": 5.2,
  "fsrs_reps": 2,
  "fsrs_scheduled_days": 0.5,
  "fsrs_retrievability": 0.65,
  "pronunciation_errors": 3,
  "dictation_errors": 0,
  "total_reviewable": 5,
  "ipa": "θɔt",
  "meaning": "想，认为",
  "pos": "v./n."
}
```

#### `POST /api/words/practice-evaluate`

单词跟读练习：上传录音 → 评估发音 → 自动 FSRS 评级。

**请求**：`multipart/form-data`
- `audio`: 音频文件（WebM/WAV）
- `word`: 单词文本

**响应**：
```json
{
  "word": "thought",
  "effective_score": 75.0,
  "auto_rating": 3,
  "auto_rating_name": "Good",
  "fsrs_result": {
    "scheduled_days": 1.5,
    "state": "review"
  }
}
```

#### `POST /api/words/dictation-practice`

单词听写练习：检查拼写 → 自动 FSRS 评级。

**请求**：
```json
{ "word": "thought", "user_input": "thout" }
```

**响应**：
```json
{
  "word": "thought",
  "user_input": "thout",
  "correct": false,
  "type": "partial",
  "similarity": 0.83,
  "edit_distance": 1,
  "auto_rating": 3,
  "auto_rating_name": "Good",
  "fsrs_result": {
    "scheduled_days": 1.0,
    "state": "learning"
  }
}
```

---

## 数据库设计

Phonos 使用 3 个独立的 SQLite 数据库，按职责分离：

### 1. phonos_fsrs.db — FSRS 间隔重复

**cards 表**：

| 字段 | 类型 | 说明 |
|------|------|------|
| card_id | TEXT PK | 卡片唯一标识（如 `sentence_1`, `word_beautiful`） |
| card_type | TEXT | 卡片类型：`sentence` 或 `word` |
| user_id | TEXT PK | 用户 ID（多用户隔离） |
| difficulty | REAL | FSRS 难度值 [1, 10] |
| stability | REAL | FSRS 记忆稳定性（天） |
| state | INTEGER | 状态：0=NEW, 1=LEARNING, 2=REVIEW, 3=RELEARNING |
| due | REAL | 下次到期时间（Unix 时间戳） |
| last_review | REAL | 上次复习时间 |
| reps | INTEGER | 复习次数 |
| lapses | INTEGER | 遗忘次数（Again 评级） |
| scheduled_days | REAL | 调度间隔天数 |
| created_at | REAL | 创建时间 |

**review_log 表**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 ID |
| card_id | TEXT | 复习的卡片 ID |
| user_id | TEXT | 用户 ID |
| rating | INTEGER | 评级 1-4 |
| state | INTEGER | 复习前的状态 |
| due | REAL | 复习后的到期时间 |
| review_time | REAL | 复习时间戳 |
| elapsed_days | REAL | 距上次复习的天数 |

### 2. phonos_learning.db — 学习记录

**user_evaluations 表**：存储每次发音评测的完整结果

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 ID |
| user_id | TEXT | 用户 ID |
| sentence_id | TEXT | 句子 ID |
| overall_score | REAL | 综合评分 |
| pronunciation_score | REAL | 准确度 |
| completeness_score | REAL | 完整度 |
| fluency_score | REAL | 流利度 |
| errors | TEXT | 错误详情 JSON |
| word_scores | TEXT | 逐词评分 JSON |
| duration | REAL | 录音时长 |
| evaluated_at | REAL | 评测时间 |

**user_word_progress 表**：每个单词的学习进度

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | TEXT | 用户 ID |
| word | TEXT | 单词 |
| attempts | INTEGER | 练习次数 |
| best_score | REAL | 最高分 |
| avg_score | REAL | 平均分 |
| mastered | BOOLEAN | 是否已掌握 |

**dictation_errors 表**：听写错误记录

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | TEXT | 用户 ID |
| word | TEXT | 错误单词 |
| sentence_id | TEXT | 句子 ID |
| error_count | INTEGER | 错误次数 |

### 3. phonos_auth.db — 用户认证

**users 表**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | 用户 UUID |
| username | TEXT UNIQUE | 用户名 |
| display_name | TEXT | 显示名称 |
| password_hash | TEXT | SHA256 哈希 |
| salt | TEXT | 随机盐值 |
| avatar_color | TEXT | 头像颜色 |
| created_at | REAL | 注册时间 |

**user_sessions 表**：

| 字段 | 类型 | 说明 |
|------|------|------|
| token | TEXT PK | UUID4 令牌 |
| user_id | TEXT | 用户 ID |
| created_at | REAL | 创建时间 |
| expires_at | REAL | 过期时间（30天） |

---

## 配置说明

### 句子数据

练习句子数据存储在 `backend/sentences.json`，JSON 数组格式：

```json
[
  {
    "id": 1,
    "text": "The weather is beautiful today",
    "translation": "今天天气真好",
    "difficulty": "easy",
    "category": "daily",
    "tags": ["weather", "daily-life"],
    "key_phrases": [
      {
        "phrase": "beautiful today",
        "meaning": "今天很美",
        "note": "描述天气好的常用搭配"
      }
    ],
    "cultural_note": "英语母语者常用天气话题作为寒暄开场白"
  }
]
```

内置 100 句练习句子，覆盖 25 个主题分类，3 级难度：

| 难度 | 数量 | 示例 |
|------|------|------|
| easy | ~35 句 | 日常对话、点餐、问候 |
| medium | ~40 句 | 商务沟通、学术讨论、旅行 |
| hard | ~25 句 | 复杂句式、绕口令、文学引用 |

可以自行扩展句子数据，只需在 JSON 数组中追加新对象并确保 ID 唯一即可。

### FSRS 参数调优

如果默认的 FSRS 参数不适合你的学习节奏，可以在 `fsrs_db.py` 中修改 `DEFAULT_FSRS_PARAMS`：

```python
# 关键参数说明：
# w[0] = 0.4072  → Again 初始稳定性（越小=间隔越短）
# w[1] = 1.1829  → Hard 初始稳定性
# w[2] = 3.1262  → Good 初始稳定性
# w[3] = 15.4722 → Easy 初始稳定性（越大=间隔越长）
# w[17] = 0.8500 → 衰减因子（影响遗忘曲线形状）
```

### 翻译缓存

翻译结果缓存到 `backend/translation_cache.json`，键为原文的 MD5 哈希。缓存文件会随使用不断增长，可以安全删除以清空缓存。

---

## 部署指南

### 开发环境

```bash
cd backend
python main.py
# 服务运行在 http://localhost:8000
# 热重载：uvicorn main:app --reload --port 8000
```

### 生产部署

使用 Uvicorn + Gunicorn 部署：

```bash
pip install gunicorn
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

### Docker 部署（示例）

```dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY frontend/ ../frontend/

# 模型需通过 volume 挂载
VOLUME /app/models

EXPOSE 8000
CMD ["python", "main.py"]
```

```bash
docker build -t phonos .
docker run -p 8000:8000 -v /path/to/models:/app/models phonos
```

### Nginx 反向代理

```nginx
server {
    listen 80;
    server_name phonos.example.com;

    client_max_body_size 20M;  # 允许上传音频文件

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| **后端框架** | Python 3.10+ / FastAPI / Uvicorn | 高性能异步 Web 框架 |
| **AI 推理** | ONNX Runtime | 音素识别 (HuPER) + 翻译 (Opus-MT) |
| **数据库** | SQLite (3个) | FSRS / 学习记录 / 用户认证，按职责分离 |
| **TTS** | edge-tts / pyttsx3 / Web Speech API | 三级回退，确保语音合成可用 |
| **音频处理** | librosa / soundfile / scipy / pydub | AGC、降噪、格式转换 |
| **前端** | 原生 HTML/CSS/JS | 无框架依赖，轻量快速 |
| **文本处理** | g2p-en | 英文文本→ARPAbet 音素 |
| **翻译** | Edge JWT / MyMemory / Google / Opus-MT | 6 级回退策略 |

---

## 浏览器兼容性

| 浏览器 | 最低版本 | 说明 |
|--------|---------|------|
| Chrome | 60+ | 完全支持 |
| Firefox | 55+ | 完全支持 |
| Safari | 14+ | 完全支持 |
| Edge | 79+ | 完全支持 |

**必需 API**：
- `MediaRecorder` — 录音
- `getUserMedia` — 麦克风访问
- `SpeechSynthesis` — 浏览器 TTS
- `AudioContext` + `AnalyserNode` — 波形可视化

---

## 常见问题

### Q: 启动时提示 "ONNX recognizer: model not found"

HuPER 模型文件未放置到正确位置。将 `model.onnx` 放到 `models/` 目录下，或通过 `HUPER_MODEL_PATH` 环境变量指定路径。没有模型时，发音评测功能不可用，但其他功能（听写、单词复习、TTS）仍可正常使用。

### Q: 翻译服务一直失败

1. 检查网络连接，确保能访问外部 API
2. 翻译服务会自动回退：在线 API 失败后使用 ONNX 本地翻译
3. 如果没有 ONNX 翻译模型，会使用简易词典回退（功能词翻译，实词保留英文）
4. 在线 API 连续失败 3 次后会进入 5 分钟冷却期，冷却后自动重试

### Q: 单词掌握统计不更新

确保复习时使用了 FSRS 评级（忘了/难/模糊/会了）。评"Good"或"Easy"后，单词状态会变为 REVIEW，此时如果未到期（`due > now`），会被记为"已掌握"。评"Again"或"Hard"则进入 LEARNING 状态，记为"待加强"。

### Q: 顺序模式刷新页面后从第一句开始

已修复。顺序模式会自动保存进度到服务端，刷新后从上次的位置继续。

### Q: 录音功能不可用

1. 确保使用 HTTPS 或 localhost（浏览器安全策略要求）
2. 允许浏览器访问麦克风
3. 检查浏览器是否支持 MediaRecorder API

### Q: 如何添加自定义练习句子

编辑 `backend/sentences.json`，在数组末尾追加新对象，确保 `id` 唯一且递增。句子格式参考 [句子数据](#句子数据) 章节。修改后重启服务即可生效。

---

## License

MIT
