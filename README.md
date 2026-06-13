# Phonos

> 基于 AI 语音识别 + FSRS-6 间隔重复 + 元认知的英语发音评测与词汇记忆平台

Phonos 是一款面向中文学习者的英语口语练习工具，融合语言学（最小对立对、ARPAbet/IPA 双音标、语义场搭配）与认知科学（FSRS-6 间隔重复、元认知镜像、预测校准、探索-利用权衡）理念，帮助用户系统性地提升英语发音和词汇记忆。

**核心特色**：不是简单的朗读打分，而是从音素级别精准定位发音问题，结合 FSRS-6 间隔重复算法科学安排复习，再通过元认知镜像帮助用户认识自己的学习模式，形成「评测 → 诊断 → 练习 → 复习 → 反思」的完整闭环。

---

## 目录

- [功能概览](#功能概览)
- [FSRS-6 间隔重复](#fsrs-6-间隔重复)
- [元认知层](#元认知层)
- [语义场词汇网络](#语义场词汇网络)
- [技术架构](#技术架构)
- [快速开始](#快速开始)
- [API 文档](#api-文档)
- [前端架构](#前端架构)
- [配置说明](#配置说明)
- [文件结构](#文件结构)
- [License](#license)

---

## 功能概览

### 核心功能

- 🗣️ **发音评测** — HuPER ONNX 音素识别 + DP 对齐 + 三维评分（准确度/完整度/流利度）
- 📝 **听写练习** — Levenshtein 词对齐 + 4 类错误检测（拼写/漏写/多写/顺序错误）
- 🧠 **FSRS-6 间隔重复** — 21 参数官方算法，每 30 次自动拟合，科学调度复习
- 🔍 **词汇网络** — 基于语义场理论和搭配强度的词汇关联图谱
- 🪞 **元认知镜像** — 认知画像、预测校准、策略推荐
- 🎯 **探索-利用权衡** — UCB1 算法平衡复习与新内容探索

### 发音评测

Phonos 的发音评测深入到每个音素级别进行精细分析：

- **三维评分体系**：综合发音准确度(55%)、完整度(25%)、流利度(20%)三个维度计算总分
  - **准确度**：基于动态规划音素对齐，逐音素对比用户发音与标准发音，计算相似度加权得分
  - **完整度**：检测用户是否遗漏了音素（如把 "three" 读成 "tree"），衡量发音的完整性
  - **流利度**：分析语速、停顿次数和停顿时长，评估说话的自然程度

- **音素级诊断**：评测结果精确定位到每个错误的音素，告知用户"你把 /θ/ 发成了 /s/"，而非笼统地说"发音不准"

- **音素相似度矩阵**：区分"接近的错误"（如 /ɪ/ → /iː/，轻微偏差）和"严重的错误"（如 /θ/ → /f/，完全替代），给予不同权重的扣分

- **12 对最小对立对检测**：自动识别中国学习者最常混淆的 12 对音素
  - L/R 混淆（light → right）
  - TH/S 混淆（think → sink）
  - V/W 混淆（vine → wine）
  - SH/S 混淆（she → see）
  - 以及 TH/T、V/F、ZH/J、AE/E、IY/I、UW/U、AO/O、N/NG 等

- **44 音素完整指南**：每个英语音素都有详细的发音指导，包含常见错误及原因分析、纠正方法和练习技巧、口型要点（舌位、唇形）、练习词汇列表

- **IPA 可点击发音**：点击音标即可听到该音素的标准人声录音（来自维基百科 IPA 音频库），双元音/塞擦音自动拆分组合播放

### 听写模式

- **先听后写**：系统先通过 TTS 播放句子，用户在输入框中逐词听写
- **三档倍速控制**：0.5x / 0.75x / 1x 三种语速，初学者可从慢速开始
- **Levenshtein 编辑距离算法**：智能对比用户的听写结果与原文，避免级联错误
- **4 类错误检测**：
  - `substitution` — 完全拼写错误（相似度 < 0.6）
  - `partial` — 部分正确（相似度 0.6~0.8，有大体拼写框架）
  - `near_correct` — 小拼写错误（相似度 ≥ 0.8 或短词编辑距离 ≤ 1）
  - `deletion` — 漏写单词
- **跳过听写**：如果只想练口语，可以一键跳过听写直接进入发音练习
- **自动隐藏原文**：听写模式下自动隐藏英文原文，防止偷看
- **错误单词自动追踪**：听写错误的单词会被记录，自动进入单词复习队列

### 其他功能

- **Wikipedia IPA 真人音素发音** — 24 个辅音 + 15 个元音的真人录音，双元音/塞擦音自动拆分顺序播放
- **5 级 TTS 回退** — edge-tts → pyttsx3 → 浏览器 SpeechSynthesis，确保总能听到发音
- **5 级翻译回退** — Edge Translator → MyMemory → Google → ONNX (Opus-MT) → 简易词典，确保总能获得翻译
- **50K 端查词典 + G2P 回退** — 本地 ENDICT 5 万高频词，查不到自动调用 MyMemory API，G2P 使用 g2p-en (ARPAbet) + 回退词典
- **双学习模式** — 智能模式（薄弱分析 + FSRS 推荐）和顺序模式（按 ID 顺序推进，支持范围设定）
- **单词多维练习** — 复习队列（FSRS + 错误词）、跟读练习（发音评测 + 自动 FSRS 评级）、听写练习（拼写检查 + 自动评级）
- **用户认证系统** — 注册/登录/会话管理，跨浏览器数据同步

---

## FSRS-6 间隔重复

### 从 FSRS-4.5 到 FSRS-6 的升级

Phonos 从 FSRS-4.5（18 参数）升级到 FSRS-6（21 参数），实现了更精确的记忆建模：

| 特性 | FSRS-4.5 | FSRS-6 |
|------|----------|--------|
| 参数数量 | 18 (w[0]~w[17]) | 21 (w[0]~w[20]) |
| DECAY 参数 | 常量 -0.5 | 可学习参数 -w[20] |
| 初始难度 D0(G) | 线性: clamp(w[4]-w[5]×(G-3), 1, 10) | 指数: clamp(w[4]-exp(w[5]×(G-1))+1, 1, 10) |
| 遗忘稳定性 | w[11]×D^(-w[12])×((S+1)^w[13]-1)×exp(w[14]×(1-R)) | 新增下限: min(S_recall, S/exp(w[17]×w[18])) |
| 短期稳定性 | 无 | S×exp(w[17]×(G-3+w[18]))×S^(-w[19]) |
| 参数拟合 | 无 | 每 30 次复习自动梯度下降拟合 |
| 区间扰动 | 无 | Fuzzing 避免卡片堆积 |
| 每用户参数 | 全局共享 | 独立存储 + 自定义 |

### 核心改进详解

#### 1. 可学习 DECAY 参数

FSRS-4.5 中 DECAY 固定为 -0.5，意味着遗忘曲线的衰减速率对所有用户相同。FSRS-6 将 DECAY 变为 -w[20]（可学习），系统会根据每个用户的实际复习数据自动调整遗忘曲线的形状。

#### 2. 指数初始难度

FSRS-4.5 使用线性公式计算初始难度，FSRS-6 改用指数形式 `D0(G) = clamp(w[4] - exp(w[5]×(G-1)) + 1, 1, 10)`，使得 Again 和 Hard 之间的难度差异更显著，而 Good 和 Easy 之间的差异更平缓，更符合认知规律。

#### 3. 短期稳定性（同日复习）

FSRS-6 新增短期稳定性公式 `S_short = S × exp(w[17] × (G-3+w[18])) × S^(-w[19])`，专门处理同日内多次复习的情况。这解决了 FSRS-4.5 中同日复习间隔增长过快的问题。

#### 4. 遗忘稳定性下限

FSRS-6 为遗忘后的稳定性增加了下限 `S/exp(w[17]×w[18])`，防止遗忘后稳定性降得过低，避免出现"忘了就永远在学"的困境。

#### 5. 自动参数拟合

每 30 次复习后自动触发梯度下降拟合，基于用户的实际复习记录优化 21 个参数。拟合使用 BFGS 优化器，最小化预测可回忆率与实际结果之间的交叉熵损失。拟合结果存储到用户参数表，后续复习使用个性化参数。

#### 6. 区间扰动（Fuzzing）

在计算的复习间隔上施加随机扰动，避免大量卡片在同一天到期。扰动范围为 `[-interval×0.05, interval×0.05]`，且最小间隔保证 ≥ 1 天。

### 评级按钮

| 评级 | 名称 | 含义 | FSRS 评分 |
|------|------|------|-----------|
| 🔴 Again | 完全忘记 | 完全不记得，需要重新学习 | 1 |
| 🟠 Hard | 困难回忆 | 想了很久才想起来 | 2 |
| 🟢 Good | 犹豫想起 | 有些犹豫但最终想起来了 | 3 |
| 🔵 Easy | 轻松回忆 | 毫不费力，完全记住 | 4 |

### 自动评级

单词练习中系统根据表现自动评级：

- **跟读练习**：准确率 ≥ 90% → Easy，≥ 70% → Good，≥ 50% → Hard，< 50% → Again
- **听写练习**：完全正确 → Easy，near_correct → Good，partial → Hard，substitution/deletion → Again

---

## 元认知层

元认知层帮助用户"认识自己的学习"，从单纯的"学什么"升级到"如何学"。

### 认知镜像

系统将用户归入 5 种学习原型，实时追踪学习指标：

| 原型 | 特征 | 典型表现 |
|------|------|----------|
| 🏃 囫囵吞枣型 | 高速度、低保持率 | 快速刷完大量卡片，但遗忘率高 |
| 💎 完美主义型 | 高准确率、低覆盖面 | 反复练习少数卡片，不愿接触新内容 |
| 📈 稳健进步型 | 均衡的速度与保持率 | 速度与保持率平衡，稳步推进 |
| 😤 高自信低准确型 | 高信心评级但实际得分低 | 自认为掌握了，实际评测分数低 |
| 😰 焦虑型 | 高 Again 率、低 Easy 使用 | 不敢给自己好评级，过度谨慎 |

**追踪指标**：学习速度（卡片/天）、保持率（到期复习正确率）、覆盖面（已学/总卡片）、信心准确度差距（自我评级 vs 实际表现）、FSRS 参数偏好。

### 预测校准

针对过度自信的用户（尤其是"高自信低准确型"），系统启用预测校准：

1. **做题前预测**：用户在练习前输入预测分数（0-100）
2. **对比实际结果**：练习后对比预测分数与实际评测分数
3. **校准统计**：追踪预测偏差、校准分数、偏差趋势
4. **自动启用**：当认知画像检测到用户为"高自信低准确型"时，自动开启预测校准功能

校准分数越接近 0 表示预测越准确，正值表示过度自信，负值表示低估自己。

### 策略推荐

基于认知画像推送针对性训练建议和 FSRS 参数调整：

- **囫囵吞枣型** → 提高期望保持率至 0.92，减少每日新卡片数
- **完美主义型** → 降低期望保持率至 0.85，增加每日新卡片数
- **焦虑型** → 减少 Hard 评级使用，更多使用 Good
- **高自信低准确型** → 启用预测校准，关注错误模式

### 学习质量评估

- **僵尸学习检测**：识别低参与度学习会话（短时间大量 Again 评级）
- **会话质量追踪**：记录每次学习会话的时长、练习数量、正确率
- **效率趋势**：展示学习效率变化曲线，帮助用户识别疲劳/倦怠期

---

## 语义场词汇网络

### 4 种关系类型

| 关系类型 | 说明 | 示例 |
|----------|------|------|
| 搭配词 (COOCCURRENCE) | 基于语料共现频率，PMI 计算搭配强度 | "make" ↔ "decision" |
| 相似词 (SEMANTIC_SIMILARITY) | 语义相近的可替换词 | "big" ↔ "large" |
| 同位词 (SYNTAGMATIC) | 组合关系，同一语法槽位的词 | "eat" → "breakfast/lunch/dinner" |
| 近义词 (PARADIGMATIC) | 聚合关系，同一语义场的词 | "happy" ↔ "glad/joyful" |

### PMI 搭配强度计算

使用点互信息 (PMI) 计算词汇搭配强度：

```
PMI(w1, w2) = log2(P(w1,w2) / (P(w1) × P(w2)))
```

从 sentences.json 语料中提取共现关系，结合 dict/endict/common.json 的词频数据，自动构建搭配网络。

### 25+ 语义场分类

基于句子类别定义语义场：daily（日常）、greeting（问候）、travel（旅行）、ordering（点餐）、shopping（购物）、weather（天气）、work（工作）、education（教育）、health（健康）、emotion（情感）等 25+ 个语义场。

### 认知最优学习路径

基于三个原则生成最优学习顺序：

1. **语义启动 (Semantic Priming)** — 相关词汇一起学习，利用扩散激活效应
2. **干扰最小化 (Interference Minimization)** — 避免同时学习过多相似词，减少前摄/倒摄抑制
3. **渐进复杂度 (Progressive Complexity)** — 高频词优先于低频词，简单搭配优先于复杂搭配

### UCB1 探索-利用权衡

使用 UCB1 (Upper Confidence Bound 1) 算法平衡复习已知内容与探索新内容：

```
score = expected_value + c × √(ln(total_reviews) / card_reviews)
```

- **高保持率 (>85%)** → 自动增加探索率，引入新内容
- **低保持率 (<60%)** → 自动增加利用，专注复习旧内容
- **探索率可调** — 默认 0.3，用户可在设置中调整 (0.0~1.0)

### 语义场覆盖度追踪

- 追踪用户在各语义场的学习进度
- 识别未探索的语义场，优先推荐
- 在增强统计中展示覆盖度热力图

---

## 技术架构

### 后端

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| AI 音素识别 | ONNX Runtime (HuPER: WavLM-Large + CTC) |
| 间隔重复 | FSRS-6 (21 参数, 自动拟合) |
| 元认知 | 自研 (5 种画像 + 预测校准 + 策略推荐) |
| 语义网络 | PMI 搭配 + 语义场 + UCB1 探索利用 |
| G2P | g2p-en (ARPAbet) + 回退词典 |
| TTS | edge-tts → pyttsx3 → 浏览器 SpeechSynthesis |
| 翻译 | Edge → MyMemory → Google → ONNX (Opus-MT) → 简易词典 |
| 词典 | ENDICT 50K + MyMemory API + G2P |
| 音频处理 | NumPy + SciPy (AGC, 频谱降噪, 预加重) |
| 认证 | SQLite + SHA256 + UUID4 Token |
| 数据库 | SQLite (4 个 DB: fsrs / learning / metacognition / semantic) |

### 前端

| 组件 | 技术 |
|------|------|
| UI | Vanilla HTML/CSS/JS |
| 动画 | Animate.css |
| 图表 | Chart.js |
| 拖拽 | SortableJS |
| 音频 | Web Audio API + MediaRecorder |
| 语音 | Browser SpeechSynthesis API |

---

## 快速开始

### 前置依赖

- Python 3.11+
- ffmpeg（音频处理）
- ONNX Runtime（可选，GPU 支持需 onnxruntime-gpu）

### 安装

```bash
cd backend
pip install -r requirements.txt
python main.py
```

访问 http://localhost:8000

首次启动会自动：
1. 初始化 G2P 服务和词典服务（延迟加载）
2. 后台加载 ONNX 模型（不阻塞启动）
3. 后台更新音素缓存
4. 初始化 FSRS 数据库
5. 初始化认证服务
6. 检查 TTS 可用性

---

## API 文档

### 系统状态

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/health | 系统健康检查（模型状态、G2P/TTS/FSRS/翻译可用性） |

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/auth/register | 用户注册（username, password, display_name） |
| POST | /api/auth/login | 用户登录，返回 Bearer Token |
| POST | /api/auth/logout | 用户登出，销毁 Token |
| GET | /api/auth/me | 获取当前用户信息 |
| PUT | /api/auth/profile | 更新用户资料（display_name, settings） |
| PUT | /api/auth/password | 修改密码（old_password, new_password） |

### 句子

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/sentence | 获取练习句子（FSRS 优先，混合复习和新句子），参数: force_new |
| GET | /api/sentences | 获取所有句子列表（含音素信息） |
| GET | /api/sentence/{sentence_id} | 按 ID 获取句子详情 |
| GET | /api/minimal-pairs | 获取 12 对最小对立对数据 |
| GET | /api/phoneme-tips | 获取 44 个音素的发音指南 |

### 发音评测

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/evaluate | 上传音频文件进行发音评测（multipart/form-data） |

### FSRS 间隔重复

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/fsrs/review | 记录复习评级（card_id, rating 1-4, card_type） |
| GET | /api/fsrs/queue | 获取复习队列（card_type, new_per_day） |
| GET | /api/fsrs/stats | 获取 FSRS 统计（含学习分析） |
| GET | /api/fsrs/next | 获取下一个 FSRS 推荐句子 |
| GET | /api/fsrs/due-count | 获取到期复习数量（含 pending/total_reviewable/new_count） |
| POST | /api/fsrs/ensure | 批量创建 FSRS 卡片（card_ids, card_type） |

### 学习模式

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/mode/sequential/next | 顺序模式：按 ID 顺序获取下一个句子 |
| POST | /api/mode/sequential/set-range | 设置顺序模式 ID 范围（start_id, end_id） |
| GET | /api/mode/smart/next | 智能模式：基于薄弱分析 + FSRS 推荐 |
| GET | /api/mode/status | 获取当前学习模式状态 |

### 学习算法

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/learning/weakness-profile | 获取用户薄弱项分析 |
| GET | /api/learning/recommendations | 获取针对性练习推荐 |
| GET | /api/learning/adaptive-next | 获取自适应难度推荐句子 |
| GET | /api/learning/analytics | 获取学习分析数据 |
| POST | /api/learning/record-evaluation | 记录评测结果 |

### 词汇

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/words/review-queue | 获取单词复习队列（FSRS + 错误词），参数: limit |
| GET | /api/words/next-review | 获取下一个需复习的单词（FSRS 推荐） |
| POST | /api/words/review | 单词复习评级（word, rating 1-4） |
| GET | /api/words/errors | 获取所有错误单词（含词典信息） |
| GET | /api/words/error-stats | 获取单词错误统计（按发音/听写分类，含 FSRS 状态） |
| GET | /api/words/practice-next | 获取下一个练习单词，参数: mode(all/pronunciation/dictation) |
| POST | /api/words/practice-evaluate | 单词跟读练习（音频评测 + 自动 FSRS 评级） |
| POST | /api/words/dictation-practice | 单词听写练习（拼写检查 + 自动 FSRS 评级） |

### 听写

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/dictation/check | 听写检查（Levenshtein 词对齐 + 4 类错误检测） |
| POST | /api/dictation/record-errors | 记录听写错误单词（支持编辑距离容错等级） |

### 词典与翻译

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/dict/{word} | 异步查询单词（本地 + 网络 API 回退） |
| GET | /api/translate | 翻译英文到中文，参数: text, force, detail |
| GET | /api/translate/status | 获取翻译服务状态（各引擎可用性） |

### TTS 与 IPA 音频

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/tts | 文本转语音，参数: text |
| GET | /api/tts/phoneme | 音素发音，参数: phoneme |
| GET | /api/tts/check | 检查 TTS 引擎可用性 |
| GET | /api/ipa-audio/{arpabet} | 获取 IPA 音素音频文件（Wikipedia 真人录音） |
| GET | /api/ipa-audio-info | 获取可用 IPA 音频列表 |

### 元认知

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/metacognition/profile | 获取认知画像（学习原型、各项指标） |
| GET | /api/metacognition/strategies | 获取策略推荐（基于认知画像） |
| POST | /api/metacognition/prediction | 记录预测校准（card_id, predicted_score, actual_score） |
| GET | /api/metacognition/calibration | 获取预测校准统计 |
| POST | /api/metacognition/session | 记录学习会话 |
| GET | /api/metacognition/session-quality | 获取学习质量指标 |

### 语义网络

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/semantic/network/{word} | 获取词汇网络，参数: depth |
| GET | /api/semantic/collocations/{word} | 获取搭配词，参数: min_strength |
| GET | /api/semantic/related/{word} | 获取关联词，参数: relation_type, limit |
| GET | /api/semantic/optimal-path | 认知最优学习路径，参数: target_words |
| GET | /api/semantic/explore-next | 探索-利用下一卡片，参数: card_type |
| GET | /api/semantic/field-coverage | 语义场覆盖度统计 |
| GET | /api/semantic/unexplored-fields | 未探索语义场列表 |
| POST | /api/semantic/rebuild | 重建语义网络（从数据文件重新构建） |

### 设置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/settings | 获取用户设置（FSRS 参数 + 扩展设置） |
| PUT | /api/settings | 更新用户设置 |
| GET | /api/settings/defaults | 获取默认设置 |
| POST | /api/settings/reset | 重置为默认设置 |
| POST | /api/settings/fsrs-fit | 手动触发 FSRS 参数拟合 |
| GET | /api/settings/fsrs-params | 获取当前 FSRS 参数（默认 + 用户自定义） |

### 统计

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/stats | 基础统计（评测记录、FSRS 状态、单词进度、错误音素） |
| GET | /api/stats/enhanced | 增强统计（含认知画像、语义场覆盖、校准分数、会话质量趋势） |

---

## 前端架构

### 单页应用架构

前端采用 Vanilla HTML/CSS/JS 构建的单页应用，无框架依赖：

- **`index.html`** — 页面结构和组件模板
- **`app.js`** — 全部前端逻辑（~3800 行）
- **`style.css`** — 完整样式定义

### 状态管理

使用全局状态对象 `S` 管理所有前端状态：

```javascript
const S = {
    sentence: null,           // 当前句子
    recording: false,         // 录音状态
    mode: 'dictation',        // 听写/练习模式
    learningMode: 'smart',    // 智能/顺序模式
    user: null,               // 当前用户
    authToken: null,          // Bearer Token
    fsrsRated: false,         // FSRS 评级状态
    predictionScore: null,    // 预测校准分数
    calibrationEnabled: false,// 预测校准开关
    settings: null,           // 用户设置缓存
    wordReviewQueue: [],      // 单词复习队列
    serverStats: null,        // 服务端统计数据
    weaknessProfile: null,    // 薄弱项分析
    // ...
};
```

所有统计数据存储在服务端数据库中，跨浏览器自动同步，不再使用 localStorage 存储统计。

### 核心组件

| 组件 | 功能 |
|------|------|
| **句子卡片** | 展示英文/中文句子、难度标签、新/复习标记 |
| **TTS 工具栏** | 标准美式发音、IPA 音标、倍速控制 |
| **听写输入** | 逐词输入框、实时检查、错误标记 |
| **录音波形** | Web Audio API 实时可视化、录音计时 |
| **评测结果** | 三维评分环形图、音素对比、错误诊断、最小对立对 |
| **FSRS 评级** | Again/Hard/Good/Easy 四级按钮、下次复习时间 |
| **认知镜像** | 学习原型雷达图、指标仪表盘、策略卡片 |
| **学习统计** | Chart.js 得分趋势图、错误音素分布、FSRS 状态饼图 |
| **单词复习** | 复习队列、跟读/听写切换、掌握度进度条 |
| **音素指南** | 44 音素网格、IPA 发音播放、发音技巧、最小对立对 |
| **设置面板** | FSRS 参数调节、探索率、预测校准开关 |

### API 通信

所有请求使用相对路径，通过 `Authorization: Bearer <token>` 头部认证。未登录时自动使用默认用户。

---

## 配置说明

### FSRS-6 参数（21 个）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| w[0] | 0.212 | S0(Again) — Again 评级的初始稳定性 |
| w[1] | 1.2931 | S0(Hard) — Hard 评级的初始稳定性 |
| w[2] | 2.3065 | S0(Good) — Good 评级的初始稳定性 |
| w[3] | 8.2956 | S0(Easy) — Easy 评级的初始稳定性 |
| w[4] | 6.4133 | D0 基础难度 — 初始难度公式的基础值 |
| w[5] | 0.8334 | D0 指数系数 — 控制初始难度的指数增长率 |
| w[6] | 3.0194 | 难度变化系数 — 复习时难度调整的幅度 |
| w[7] | 0.001 | 难度均值回归系数 — 控制难度向均值回归的速度 |
| w[8] | 1.8722 | 回忆稳定性增长系数 — 成功回忆时稳定性增长的幅度 |
| w[9] | 0.1666 | 回忆稳定性衰减指数 — 稳定性对增长率的衰减 |
| w[10] | 0.796 | 回忆稳定性回忆率系数 — 可回忆率对稳定性增长的影响 |
| w[11] | 1.4835 | 遗忘稳定性系数 — 遗忘后新稳定性的基础值 |
| w[12] | 0.0614 | 遗忘稳定性难度衰减指数 — 难度对遗忘后稳定性的影响 |
| w[13] | 0.2629 | 遗忘稳定性稳定性增长指数 — 旧稳定性对遗忘后稳定性的影响 |
| w[14] | 1.6483 | 遗忘稳定性回忆率系数 — 可回忆率对遗忘后稳定性的影响 |
| w[15] | 0.6014 | Hard 惩罚系数 — Hard 评级对稳定性增长的折扣 |
| w[16] | 1.8729 | Easy 奖励系数 — Easy 评级对稳定性增长的加成 |
| w[17] | 0.5425 | 短期稳定性系数 / 遗忘稳定性下限系数 1 |
| w[18] | 0.0912 | 短期稳定性偏移 / 遗忘稳定性下限系数 2 |
| w[19] | 0.0658 | 短期稳定性衰减指数 |
| w[20] | 0.1542 | DECAY — 可学习衰减参数（FSRS-4.5 中为常量 0.5） |

参数每 30 次复习自动拟合，也可通过 `POST /api/settings/fsrs-fit` 手动触发。

### 可调设置

| 设置项 | 范围 | 默认值 | 说明 |
|--------|------|--------|------|
| desired_retention | 0.8~0.99 | 0.9 | 期望保持率，越高复习越频繁 |
| new_per_day | 1~20 | 5 | 每日新卡片数量 |
| maximum_interval | 1~36500 | 36500 | 最大复习间隔（天） |
| learning_steps | — | [1, 10] | 学习步骤（分钟） |
| relearning_steps | — | [10] | 重新学习步骤（分钟） |
| exploration_rate | 0.0~1.0 | 0.3 | 探索-利用权衡的探索率 |
| enable_prediction_calibration | auto | true | 是否启用预测校准（auto = 根据认知画像自动决定） |

---

## 文件结构

```
backend/
├── main.py              # FastAPI 服务器 (73+ API 端点)
├── fsrs_db.py           # FSRS-6 间隔重复 (21参数, 自动拟合)
├── learning_algorithm.py # 智能学习 (薄弱分析, 自适应难度, 顺序模式)
├── metacognition.py     # 元认知层 (认知画像, 预测校准, 策略推荐)
├── semantic_network.py  # 语义网络 (词汇关联, 探索利用, 最优路径)
├── scoring.py           # 发音评测核心 (DP对齐 + 三维评分)
├── onnx_service.py      # HuPER ONNX 音素识别 (WavLM-Large + CTC)
├── audio_processor.py   # 音频预处理 (AGC, 频谱降噪, 预加重)
├── g2p_service.py       # 文本→音素转换 (g2p-en + 回退词典)
├── phoneme_data.py      # 44音素提示 + 最小对立体 + ARPAbet/IPA映射
├── tts_service.py       # TTS 5级回退 (edge-tts → pyttsx3 → 浏览器)
├── translate_service.py # 翻译 5级回退 (Edge → MyMemory → Google → ONNX → 词典)
├── dict_service.py      # 动态词典 (ENDICT 50K + MyMemory API)
├── auth_service.py      # 用户认证 (注册/登录/Token管理)
├── sentences.json       # 100+ 练习句子 (含分类和难度)
├── dict/
│   └── endict/
│       └── common.json  # 50K 词典 (音标、释义、词性、词频)
└── ipa_audio/           # Wikipedia IPA 音频文件
    ├── consonants/      # 辅音真人录音 (24个)
    └── vowels/          # 元音真人录音 (15个)

frontend/
├── index.html           # 单页应用
├── app.js               # 前端逻辑 (~3800行)
└── style.css            # 样式

数据库文件 (运行时自动创建):
├── phonos_fsrs.db           # FSRS 卡片和复习记录
├── phonos_learning.db       # 评测记录、单词进度、错误统计
├── phonos_metacognition.db  # 认知画像、预测校准、会话质量
└── phonos_semantic.db       # 语义网络、词汇关系、覆盖度
```

---

## License

MIT
