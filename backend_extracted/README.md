# Phonos - 英语口语练习平台

基于 HuPER-Recognizer (WavLM-Large + CTC) ONNX 模型的英语发音评测与词汇记忆平台。

融合语言学（最小对立对、ARPAbet/IPA 双音标、词组搭配）与认知科学（FSRS 间隔重复、主动回忆、错误模式追踪、自适应难度）理念。

## 功能亮点

### 发音评测
- **三维评分** - 发音准确度(55%) + 完整度(25%) + 流利度(20%)
- **动态规划音素对齐** - 精准定位每个音素错误
- **音素相似度矩阵** - 区分"接近的错误"和"严重的错误"
- **最小对立对检测** - 自动识别 L/R、TH/S、V/W 等中国学习者常见混淆
- **44 音素完整指南** - 每个音素含：常见错误、纠正方法、口型要点、练习词
- **IPA 可点击发音** - 点击音标即可听该音素的孤立发音（标准人声录音）

### 听写模式
- **先听后写** - TTS 播放句子后，逐词听写
- **倍速控制** - 0.5x / 0.75x / 1x 三种语速
- **Levenshtein 编辑距离** - 智能对比算法，避免级联错误
- **跳过听写** - 可直接进入口语练习模式
- **句子隐藏** - 听写时自动隐藏原文，防止作弊

### 双学习模式
- **顺序模式** - 按 sentences.json 顺序逐句学习，支持手动指定 ID 范围（如从第 10 句开始）
- **智能模式** - 基于 FSRS + 薄弱分析 + 难度自适应的综合推荐，自动调整下一句
- **数据变更检测** - 句子数据更新时自动检测，提示用户重新指定起始位置
- **模式切换** - 头部一键切换，选择自动保存到本地

### 智能学习系统
- **薄弱音素分析** - 自动追踪用户的音素错误率，识别高频错误音素
- **自适应难度** - 根据历史表现动态调整推荐句子难度（easy/medium/hard）
- **针对性练习推荐** - 基于薄弱项推荐包含目标音素/单词的练习句子
- **FSRS 评分驱动推荐** - 智能模式结合 FSRS 卡片难度、记忆稳定性、薄弱项重叠度综合打分
- **学习趋势分析** - 得分趋势、连续学习天数、每日练习量统计
- **单词掌握追踪** - 追踪每个单词的练习次数、最高分、平均分、是否掌握

### 单词复习
- **FSRS 单词复习队列** - 听写错误和发音错误的单词自动进入 FSRS 复习
- **4 级评级** - 忘了/难/模糊/会了，驱动间隔重复调度
- **错误追踪** - 自动记录听写错误和发音错误（准确度 < 60% 的单词）
- **错误分类** - 区分听写错误和发音错误，分别计数
- **单词详情卡片** - 展示 IPA 音标、释义、词性、错误次数

### 用户认证
- **注册/登录** - 用户名 + 密码，SHA256 + 随机盐值加密
- **会话管理** - UUID4 令牌，30 天有效期
- **跨设备同步** - 所有学习数据存储在服务端 SQLite，跨浏览器自动同步
- **访客模式** - 无需注册即可使用，数据保存为默认用户

### 词汇学习
- **ENDICT 动态词典** - 5 万高频词（英美音标、释义、例句）
- **多级翻译回退** - Edge Translator JWT → MyMemory → Google → ONNX 本地模型 → 简易词典
- **ONNX 离线翻译** - 在线 API 连续失败时自动切换至本地 Seq2Seq 模型（Opus-MT ONNX）
- **延迟加载** - 词典按需加载，启动快
- **自动翻译** - 缺少翻译的句子自动从词典拼接

### 认知科学
- **FSRS-4.5 间隔重复** - 先进的记忆算法，4 级评级
- **复习队列** - 自动安排到期复习和新句子
- **学习统计** - 练习次数、复习进度、平均评分、连续学习天数
- **API 失败冷却** - 在线翻译 API 连续失败 3 次后进入 5 分钟冷却期

### 语言学
- **IPA + ARPAbet 双音标** - 同时展示国际音标和 ARPAbet
- **最小对立对训练** - 12 对中国学习者最易混淆的音素对
- **绕口令练习** - 专项绕口令训练

## 快速开始

### 1. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 2. 放置模型

将 HuPER ONNX 模型文件放到项目根目录的 `models/` 文件夹中：

```
Phonos/
├── models/
│   ├── model.onnx              ← 标准模型（或 model_quantized.onnx）
│   └── onnx_quant/             ← ONNX 翻译模型（可选，用于离线翻译）
├── backend/
├── frontend/
└── README.md
```

> 翻译模型目录需包含 `*.onnx` 文件和 tokenizer 配置（如 Opus-MT-en-zh 的 ONNX 导出版本）。没有翻译模型时，系统自动回退到在线 API 或简易词典。

### 3. 启动

```bash
cd backend
python main.py
```

服务将在 http://localhost:8000 启动。

> 也可以指定模型路径：`HUPER_MODEL_PATH=/path/to/model.onnx python main.py`
>
> 指定翻译模型路径：`PHONOS_TRANSLATE_MODEL_PATH=/path/to/translation_model python main.py`

### 4. 访问

打开浏览器访问 http://localhost:8000

## 可选：增强词典

项目已内置 ENDICT 高频词典（`backend/dict/endict/common.json`），包含 5 万最常用英语单词。

查不到的词会自动通过免费网络 API（Edge Translator → MyMemory → Google）翻译，无需额外配置。在线 API 不可用时，自动回退至 ONNX 本地翻译模型或简易词典。

## 项目结构

```
Phonos/
├── models/                      ← ONNX 模型（音素识别 + 翻译）
├── backend/
│   ├── main.py                  # FastAPI 应用（路由、启动逻辑）
│   ├── onnx_service.py          # HuPER ONNX 音素识别推理
│   ├── onnx_translate_service.py # ONNX 翻译模型（Opus-MT 本地离线翻译）
│   ├── g2p_service.py           # G2P 文本→音素 + IPA
│   ├── scoring.py               # 三维评分算法（准确度/完整度/流利度）
│   ├── audio_processor.py       # 音频处理（AGC + 降噪）
│   ├── phoneme_data.py          # 语言学数据（音素指南、最小对立对）
│   ├── tts_service.py           # TTS 语音合成（edge-tts / pyttsx3）
│   ├── fsrs_db.py               # FSRS-4.5 间隔重复引擎
│   ├── dict_service.py          # 动态词典（ENDICT + 网络 API）
│   ├── translate_service.py     # 翻译服务（Edge JWT → MyMemory → Google → ONNX → 词典）
│   ├── auth_service.py          # 用户认证（注册/登录/会话管理）
│   ├── learning_algorithm.py    # 智能学习算法（薄弱分析/自适应/推荐）
│   ├── sentences.json           # 预设句子数据
│   ├── requirements.txt         # Python 依赖
│   ├── dict/endict/
│   │   └── common.json          # 高频词典（5 万词）
│   └── ipa_audio/               # 标准音素发音音频
│       ├── consonants/          # 辅音录音
│       └── vowels/              # 元音录音
├── frontend/
│   ├── index.html               # 主页面
│   ├── style.css                # UI 样式
│   └── app.js                   # 前端逻辑
└── README.md
```

## API

### 基础

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/sentence` | 随机句子（FSRS 优先） |
| GET | `/api/sentences` | 所有句子（基本信息） |
| GET | `/api/sentence/{id}` | 按 ID 获取句子（完整详情） |
| GET | `/api/dict/{word}` | 异步查词（本地 + 网络 API） |
| GET | `/api/minimal-pairs` | 最小对立对数据 |
| GET | `/api/phoneme-tips` | 44 音素发音指南 |
| GET | `/api/ipa-audio/{arpabet}` | 音素标准发音音频 |
| POST | `/api/evaluate` | 上传音频评测 |
| GET | `/api/tts` | TTS 语音合成 |
| GET | `/api/tts/phoneme` | 单音素 TTS |
| POST | `/api/dictation/check` | 听写对比检查 |

### FSRS 间隔重复

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/fsrs/review` | FSRS 复习评级（1-4） |
| GET | `/api/fsrs/queue` | FSRS 复习队列 |
| GET | `/api/fsrs/stats` | 学习统计（含智能学习分析） |
| GET | `/api/fsrs/next` | 获取下一个推荐句子 |
| GET | `/api/fsrs/due-count` | 待复习数量 |
| POST | `/api/fsrs/ensure` | 批量创建 FSRS 卡片 |

### 用户认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 用户注册 |
| POST | `/api/auth/login` | 用户登录 |
| POST | `/api/auth/logout` | 用户登出 |
| GET | `/api/auth/me` | 获取当前用户信息 |
| PUT | `/api/auth/profile` | 更新用户资料 |
| PUT | `/api/auth/password` | 修改密码 |

### 智能学习

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/learning/weakness-profile` | 薄弱项分析（音素/单词） |
| GET | `/api/learning/recommendations` | 针对性练习推荐 |
| GET | `/api/learning/adaptive-next` | 自适应难度推荐句子 |
| GET | `/api/learning/analytics` | 详细学习分析（趋势/连续天数） |
| GET | `/api/stats` | 用户完整统计（评测/FSRS/薄弱项） |
| POST | `/api/learning/record-evaluation` | 记录评测结果 |

### 学习模式

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/mode/sequential/next` | 顺序模式下一句（支持 `start_id`/`end_id` 参数） |
| POST | `/api/mode/sequential/set-range` | 设置顺序模式 ID 范围 |
| GET | `/api/mode/smart/next` | 智能模式下一句（FSRS+薄弱+自适应综合推荐） |
| GET | `/api/mode/status` | 学习模式状态（含数据变更检测） |

### 单词复习

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/words/review-queue` | 单词复习队列（FSRS 到期 + 错误单词） |
| POST | `/api/words/review` | 单词复习评级（1-4） |
| GET | `/api/words/errors` | 获取所有错误单词（含听写/发音分类） |
| POST | `/api/dictation/record-errors` | 记录听写错误单词 |

## 翻译服务优先级

```
1. 本地缓存（已翻译过的句子）
2. Microsoft Edge Translator（免费 JWT 认证 + 官方 API，最稳定）
3. MyMemory Translation API（免费，每天 5K 字符匿名额度）
4. Google Translate（需安装 googletrans，可能不稳定）
   ↳ 连续失败 ≥ 3 次后，进入 5 分钟冷却期
5. ONNX 本地翻译模型（Opus-MT Seq2Seq + ONNX Runtime，完全离线）
6. 简易词典回退（功能词翻译，实词保留英文）
```

## 技术栈

- **后端**: Python 3.10+ / FastAPI / Uvicorn
- **前端**: 原生 HTML/CSS/JS（无框架依赖）
- **AI 模型**: HuPER-Recognizer (WavLM-Large CTC) ONNX / Opus-MT ONNX
- **数据库**: SQLite（FSRS 复习 + 用户认证 + 学习记录）
- **TTS**: edge-tts (Microsoft Edge) / pyttsx3 (本地) / Web Speech API (浏览器)
- **音频处理**: librosa / soundfile / scipy / pydub

## 浏览器兼容性

Chrome 60+ / Firefox 55+ / Safari 14+ / Edge 79+

需支持 MediaRecorder + getUserMedia + SpeechSynthesis

## License

MIT
