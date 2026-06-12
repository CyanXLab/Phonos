# HuPER 口语练习平台

基于 HuPER-Recognizer (WavLM-Large + CTC) ONNX 模型的英语发音评测平台。

## 功能

- 🎯 **发音准确度评测** - 基于 ARPAbet 音素对齐和加权评分算法
- 📖 **完整度评测** - 检测漏读、多读的音素
- 🌊 **流利度评测** - 分析语速、停顿、节奏一致性
- 🔍 **错误诊断** - 逐音素对比，精准定位发音问题
- 💡 **改进建议** - 每个错误音素提供常见问题、口型要点、纠正方法
- 🎤 **实时录音** - 浏览器录音 + 实时音频波形可视化
- 📝 **预设句子** - 10个不同难度的英语句子

## 快速开始

### 1. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 2. 准备模型（可选）

将 HuPER ONNX 模型放置到项目目录，并设置环境变量：

```bash
export HUPER_MODEL_PATH=/path/to/your/model.onnx
```

> 如果没有模型，平台将以**演示模式**启动（使用模拟数据展示前端效果）。

### 3. 启动服务

```bash
bash start.sh
```

或手动启动：

```bash
cd backend
HUPER_MODEL_PATH=./model.onnx python main.py
```

### 4. 访问平台

打开浏览器访问: http://localhost:8000

## 项目结构

```
huper-oral-practice/
├── backend/
│   ├── main.py           # FastAPI 应用入口
│   ├── onnx_service.py   # ONNX 推理服务
│   ├── g2p_service.py    # G2P 文本转音素
│   ├── scoring.py        # 评分算法核心
│   ├── phoneme_data.py   # 音素数据、错误提示
│   └── requirements.txt  # Python 依赖
├── frontend/
│   ├── index.html        # 主页面
│   ├── style.css         # 样式
│   └── app.js            # 前端逻辑
├── start.sh              # 启动脚本
└── README.md
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/sentence` | 获取随机练习句子 |
| GET | `/api/sentences` | 获取所有句子 |
| POST | `/api/evaluate` | 上传音频评测发音 |
| POST | `/api/evaluate/demo` | 演示评测（无需音频） |

## 评分算法

### 发音准确度 (55%)
- 基于动态规划音素序列对齐
- 使用音素相似度矩阵区分"接近的错误"和"严重的错误"
- 元音权重(1.5x) > 辅音权重(1.0x)，因为元音错误更影响理解
- 清浊混淆(S/Z)惩罚 < 完全错误(S/K)惩罚
- 非线性映射防止虚高分数

### 完整度 (25%)
- 检测漏读音素（删除错误）
- 替换音素给予部分分
- 衡量是否完整读出了所有内容

### 流利度 (20%)
- 语速评估（正常: 10-15 音素/秒）
- 停顿分析（次数、时长、占比）
- 节奏一致性（音素时长变异系数）

## 浏览器兼容性

- Chrome 60+
- Firefox 55+
- Safari 14+
- Edge 79+

需要浏览器支持 `MediaRecorder` API 和 `getUserMedia` API。
