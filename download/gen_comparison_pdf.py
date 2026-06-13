#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate Phonos vs Echoic comparison report PDF"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus.flowables import Flowable
import os

# ========== Font Registration ==========
font_dir = "/usr/share/fonts/truetype"
pdfmetrics.registerFont(TTFont('NotoSansSC', os.path.join(font_dir, 'chinese/SarasaMonoSC-Regular.ttf')))
pdfmetrics.registerFont(TTFont('NotoSerifSC', os.path.join(font_dir, 'noto-serif-sc/NotoSerifSC-Regular.ttf')))
pdfmetrics.registerFont(TTFont('NotoSerifSC-Bold', os.path.join(font_dir, 'noto-serif-sc/NotoSerifSC-SemiBold.ttf')))

# ========== Palette ==========
PAGE_BG       = colors.HexColor('#f4f5f6')
SECTION_BG    = colors.HexColor('#eaeced')
CARD_BG       = colors.HexColor('#ebeef0')
TABLE_STRIPE  = colors.HexColor('#eef0f1')
HEADER_FILL   = colors.HexColor('#3d4d55')
COVER_BLOCK   = colors.HexColor('#415159')
BORDER        = colors.HexColor('#c0cbd0')
ICON          = colors.HexColor('#3e6578')
ACCENT        = colors.HexColor('#9c3143')
ACCENT_2      = colors.HexColor('#7d37af')
TEXT_PRIMARY   = colors.HexColor('#181a1a')
TEXT_MUTED     = colors.HexColor('#868c8f')
SEM_SUCCESS   = colors.HexColor('#417753')
SEM_WARNING   = colors.HexColor('#8f7644')
SEM_ERROR     = colors.HexColor('#92534d')
SEM_INFO      = colors.HexColor('#3f6993')

# ========== Styles ==========
styles = getSampleStyleSheet()

title_style = ParagraphStyle(
    'CNTitle', fontName='NotoSerifSC-Bold', fontSize=24, leading=32,
    alignment=TA_CENTER, textColor=TEXT_PRIMARY, spaceAfter=6*mm
)

h1_style = ParagraphStyle(
    'CNH1', fontName='NotoSerifSC-Bold', fontSize=16, leading=24,
    textColor=ACCENT, spaceBefore=8*mm, spaceAfter=4*mm
)

h2_style = ParagraphStyle(
    'CNH2', fontName='NotoSerifSC-Bold', fontSize=13, leading=20,
    textColor=HEADER_FILL, spaceBefore=5*mm, spaceAfter=3*mm
)

body_style = ParagraphStyle(
    'CNBody', fontName='NotoSansSC', fontSize=10.5, leading=18,
    alignment=TA_JUSTIFY, textColor=TEXT_PRIMARY, spaceAfter=3*mm,
    wordWrap='CJK'
)

body_bold_style = ParagraphStyle(
    'CNBodyBold', fontName='NotoSerifSC-Bold', fontSize=10.5, leading=18,
    alignment=TA_JUSTIFY, textColor=TEXT_PRIMARY, spaceAfter=3*mm,
    wordWrap='CJK'
)

muted_style = ParagraphStyle(
    'CNMuted', fontName='NotoSansSC', fontSize=9, leading=14,
    textColor=TEXT_MUTED, spaceAfter=2*mm, wordWrap='CJK'
)

th_style = ParagraphStyle(
    'CNTH', fontName='NotoSerifSC-Bold', fontSize=10, leading=15,
    textColor=colors.white, alignment=TA_CENTER, wordWrap='CJK'
)

td_style = ParagraphStyle(
    'CNTD', fontName='NotoSansSC', fontSize=9.5, leading=15,
    textColor=TEXT_PRIMARY, alignment=TA_LEFT, wordWrap='CJK'
)

td_center_style = ParagraphStyle(
    'CNTDCenter', fontName='NotoSansSC', fontSize=9.5, leading=15,
    textColor=TEXT_PRIMARY, alignment=TA_CENTER, wordWrap='CJK'
)

accent_style = ParagraphStyle(
    'CNAccent', fontName='NotoSerifSC-Bold', fontSize=10.5, leading=18,
    textColor=SEM_SUCCESS, spaceAfter=3*mm, wordWrap='CJK'
)

warning_style = ParagraphStyle(
    'CNWarning', fontName='NotoSerifSC-Bold', fontSize=10.5, leading=18,
    textColor=SEM_ERROR, spaceAfter=3*mm, wordWrap='CJK'
)

info_style = ParagraphStyle(
    'CNInfo', fontName='NotoSerifSC-Bold', fontSize=10.5, leading=18,
    textColor=SEM_INFO, spaceAfter=3*mm, wordWrap='CJK'
)

# ========== Helper Functions ==========
def make_table(headers, rows, col_widths=None):
    """Create a styled table"""
    header_row = [Paragraph(h, th_style) for h in headers]
    data = [header_row]
    for row in rows:
        data.append([Paragraph(str(c), td_style) for c in row])
    
    if col_widths is None:
        col_widths = [160*mm / len(headers)] * len(headers)
    
    t = Table(data, colWidths=col_widths, repeatRows=1)
    
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_FILL),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'NotoSerifSC-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]
    
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(('BACKGROUND', (0, i), (-1, i), TABLE_STRIPE))
    
    t.setStyle(TableStyle(style_cmds))
    return t

def make_comparison_table(headers, rows, col_widths=None):
    """Create comparison table with accent highlighting for winners"""
    header_row = [Paragraph(h, th_style) for h in headers]
    data = [header_row]
    for row in rows:
        data.append([Paragraph(str(c), td_style) for c in row])
    
    if col_widths is None:
        col_widths = [160*mm / len(headers)] * len(headers)
    
    t = Table(data, colWidths=col_widths, repeatRows=1)
    
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_FILL),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'NotoSerifSC-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]
    
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(('BACKGROUND', (0, i), (-1, i), TABLE_STRIPE))
    
    t.setStyle(TableStyle(style_cmds))
    return t

def hr():
    return HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=3*mm, spaceBefore=3*mm)

# ========== Build Document ==========
output_path = "/home/z/my-project/download/Phonos_vs_Echoic_对比分析.pdf"

doc = SimpleDocTemplate(
    output_path,
    pagesize=A4,
    leftMargin=25*mm,
    rightMargin=25*mm,
    topMargin=25*mm,
    bottomMargin=20*mm,
)

story = []

# ========== Title Page ==========
story.append(Spacer(1, 30*mm))
story.append(Paragraph("Phonos vs Echoic", title_style))
story.append(Paragraph("英语口语练习平台深度对比分析", ParagraphStyle(
    'SubTitle', fontName='NotoSansSC', fontSize=14, leading=22,
    alignment=TA_CENTER, textColor=TEXT_MUTED, spaceAfter=10*mm
)))
story.append(hr())
story.append(Spacer(1, 5*mm))

intro_text = """
本报告对两个开源英语口语练习平台 Phonos 和 Echoic 进行全方位对比分析。Phonos 是一个基于 AI 语音识别（HuPER-Recognizer）和 FSRS 间隔重复算法的英语发音评测与词汇记忆平台，
而 Echoic 是一个 AI 驱动的口语练习应用，支持导入任意音频进行逐句练习和音素级发音评分。两者虽然在"英语口语练习"这一大方向上相似，但在技术架构、功能定位、学习模型和适用场景上存在显著差异。
以下将从技术栈、核心功能、发音评估、学习系统、内容管理、用户体验、部署方式等多个维度进行详细对比，并给出综合评价和适用场景建议。
"""
story.append(Paragraph(intro_text.strip(), body_style))

story.append(Spacer(1, 8*mm))

# Quick overview table
overview_data = [
    ["项目定位", "英语发音评测 + 词汇记忆 + 间隔重复", "AI 口语练习 + 音频导入 + 发音评分"],
    ["核心AI模型", "HuPER (WavLM-Large + CTC) ONNX", "WhisperX (faster-whisper + CTranslate2)"],
    ["学习算法", "FSRS-4.5 间隔重复算法", "无内置间隔重复算法"],
    ["前端技术", "Vanilla HTML/CSS/JS", "React 18 + Vite + Tailwind CSS v4 + shadcn/ui"],
    ["后端技术", "FastAPI + SQLite", "FastAPI + PostgreSQL + SQLAlchemy + Alembic"],
    ["部署方式", "手动安装 Python 依赖", "Docker Compose 一键部署"],
    ["多语言支持", "仅英语", "9 种语言（英/日/韩/法/德/西/意/葡/俄）"],
    ["GitHub Stars", "新建项目", "38 stars"],
    ["开源协议", "未明确", "MIT"],
]

story.append(make_comparison_table(
    ["对比维度", "Phonos", "Echoic"],
    overview_data,
    col_widths=[30*mm, 65*mm, 65*mm]
))

# ========== Section 1: Tech Stack ==========
story.append(Spacer(1, 5*mm))
story.append(Paragraph("一、技术架构对比", h1_style))

story.append(Paragraph("1.1 后端技术栈", h2_style))

tech_backend = [
    ["Web框架", "FastAPI + Uvicorn", "FastAPI + Uvicorn"],
    ["数据库", "SQLite（轻量，零配置）", "PostgreSQL 16（生产级，需独立部署）"],
    ["ORM", "原生 SQL", "SQLAlchemy + Alembic 迁移"],
    ["ASR 识别", "HuPER ONNX (WavLM-Large + CTC)", "WhisperX (faster-whisper + CTranslate2)"],
    ["音素对齐", "g2p-en (ARPAbet) + 内置回退", "wav2vec2 强制对齐"],
    ["发音评分", "自研 DP 对齐 + 三维评分", "wav2vec2 + phonemizer"],
    ["TTS", "edge-tts / pyttsx3 / 浏览器回退", "无内置 TTS（依赖原始音频）"],
    ["翻译", "5 级回退链（Edge/Google/ONNX/离线）", "OpenAI / Ollama（LLM 句子分析）"],
    ["认证", "SQLite + SHA256 + UUID4 Token", "无内置用户系统"],
    ["容器化", "无 Docker 支持", "完整 Docker Compose"],
]

story.append(make_comparison_table(
    ["组件", "Phonos", "Echoic"],
    tech_backend,
    col_widths=[28*mm, 66*mm, 66*mm]
))

story.append(Paragraph(
    "Phonos 采用了「零外部依赖」的设计哲学，使用 SQLite 作为唯一存储引擎，无需安装和配置独立的数据库服务，这对于个人用户或小团队来说部署门槛极低。"
    "其 ASR 引擎基于 HuPER 模型的 ONNX 推理版本，使用 WavLM-Large 作为特征提取器配合 CTC 贪心解码，在音素识别精度上表现良好，且 ONNX 格式的推理速度明显快于 PyTorch 原生推理。"
    "翻译服务采用了 5 级回退链设计，从在线 API 到本地 ONNX 模型再到简易词典，确保在任何网络环境下都能提供翻译功能。"
    "这种多级回退的架构贯穿了 Phonos 的各个模块——TTS、翻译、词典服务都是如此，体现了极强的离线优先和容错设计理念。",
    body_style
))

story.append(Paragraph(
    "Echoic 则选择了更工业化的技术栈，PostgreSQL + SQLAlchemy + Alembic 构成了完整的数据层，具备事务安全、并发处理和数据库迁移能力。"
    "其 ASR 使用 WhisperX（基于 faster-whisper 和 CTranslate2），这是一个更重量级但功能更全面的方案，支持多种语言和更大的模型尺寸选择。"
    "发音评分采用 wav2vec2 + phonemizer 的组合，利用 Meta 的 wav2vec2 模型进行强制对齐，再通过 phonemizer 转换为国际音标进行比对。"
    "Docker Compose 的一键部署是 Echoic 的一大亮点，用户只需 docker compose up 即可启动整个系统，"
    "但代价是需要安装 Docker 并下载约 1GB 的模型文件。",
    body_style
))

story.append(Paragraph("1.2 前端技术栈", h2_style))

tech_frontend = [
    ["框架", "Vanilla HTML/CSS/JS（无框架）", "React 18 + Vite"],
    ["UI组件", "手写 CSS（CSS 变量 + glassmorphism）", "shadcn/ui + Tailwind CSS v4"],
    ["音频可视化", "Web Audio API + Canvas 波形", "WaveSurfer.js 专业波形"],
    ["国际化", "中文界面", "7 语言 UI（英/中/日/韩/法/德）"],
    ["暗色模式", "无", "支持（浅色/深色/跟随系统）"],
    ["键盘快捷键", "无", "Space/R/Enter/箭头/Esc"],
    ["代码量", "app.js 2000+ 行 / style.css 2000+ 行", "React 组件化，模块化拆分"],
]

story.append(make_comparison_table(
    ["维度", "Phonos", "Echoic"],
    tech_frontend,
    col_widths=[28*mm, 66*mm, 66*mm]
))

story.append(Paragraph(
    "前端技术栈的差异是两个项目最显著的分水岭。Phonos 选择原生 HTML/CSS/JS 开发，所有逻辑集中在单一的 app.js 和 style.css 中，"
    "没有使用任何前端框架。这种方式的优点是零构建依赖、学习成本低、可以直接用浏览器打开运行，但缺点也很明显：2000+ 行的单文件难以维护，"
    "缺乏组件化导致代码复用困难，状态管理完全依赖全局变量和 DOM 操作。"
    "Echoic 采用了 React 18 + Vite + shadcn/ui + Tailwind CSS v4 的现代前端栈，具备组件化开发、热更新、类型安全等优势。"
    "WaveSurfer.js 提供了专业的音频波形显示和交互能力，支持缩放、选区、标注等高级功能，远超 Phonos 的简易 Canvas 波形绘制。"
    "此外，Echoic 的 7 语言 UI 翻译、暗色模式、键盘快捷键等特性展示了更成熟的用户体验设计。",
    body_style
))

# ========== Section 2: Core Features ==========
story.append(Paragraph("二、核心功能对比", h1_style))

story.append(Paragraph("2.1 发音评估系统", h2_style))

pronunciation_data = [
    ["评分维度", "三维评分：准确度(55%) + 完整度(25%) + 流利度(20%)", "三维评分：准确度(50%) + 流利度(30%) + 完整度(20%)"],
    ["评分权重", "固定权重（可调需改代码）", "可配置权重（环境变量调整）"],
    ["音素对齐", "自研 DP 对齐 + 音素相似度矩阵", "wav2vec2 强制对齐 + phonemizer"],
    ["音素体系", "ARPAbet（39 音素 + 特殊标记）", "IPA 国际音标（espeak-ng 输出）"],
    ["最小对立体", "12 对中国学习者常见混淆音素", "无内置最小对立体检测"],
    ["诊断提示", "详细：错误描述 + 纠正方法 + 口型指导 + 练习词", "基础：音素颜色标记 + 准确率百分比"],
    ["词级评分", "支持，逐词准确率 + 错误高亮", "支持，逐词准确率 + 颜色编码"],
    ["流利度分析", "详细：语速 + 停顿检测 + 停顿比率 + 时长方差", "基础：基于 wav2vec2 时间戳"],
    ["音素音频", "Wikipedia IPA 真人录音 + TTS 回退", "无独立音素发音功能"],
]

story.append(make_comparison_table(
    ["维度", "Phonos", "Echoic"],
    pronunciation_data,
    col_widths=[28*mm, 66*mm, 66*mm]
))

story.append(Paragraph(
    "发音评估是两个项目的核心功能，但实现深度差异巨大。Phonos 在发音诊断方面做得更加深入和贴心，尤其是对中国英语学习者的针对性设计："
    "12 对最小对立体（L/R、TH/S、V/W 等）覆盖了中国学习者最常犯的音素混淆错误，每对都配备了具体的错误描述、纠正方法、口型指导和练习词汇。"
    "流利度分析考虑了语速（5-18 音素/秒为最优区间）、停顿检测（大于 0.15 秒的空白段）、停顿比率和时长方差等多个维度，提供了比 Echoic 更细致的流利度评价。"
    "Wikipedia IPA 真人录音是一个独特且实用的功能，学习者点击音素标记即可听到对应音素的标准发音，对纠正发音非常有帮助。",
    body_style
))

story.append(Paragraph(
    "Echoic 的优势在于其 wav2vec2 强制对齐技术，这是一种基于深度学习的音素级时间戳对齐方法，理论上精度更高，"
    "且支持 9 种语言的音素评分，而 Phonos 仅支持英语。Echoic 的评分权重可通过环境变量灵活调整，"
    "而 Phonos 的权重是硬编码的（虽然修改代码也不复杂）。"
    "不过 Echoic 在诊断深度上有所不足，缺乏最小对立体检测和针对性的错误纠正建议，音素颜色编码虽然直观但信息量有限。",
    body_style
))

story.append(Paragraph("2.2 学习与复习系统", h2_style))

learning_data = [
    ["间隔重复", "FSRS-4.5（18 参数，科学记忆模型）", "无内置间隔重复算法"],
    ["复习队列", "FSRS 调度：到期复习 > 新卡 > 随机", "手动标记：收藏 / 掌握"],
    ["学习模式", "智能模式（弱点+FSRS）+ 顺序模式（ID范围）", "顺序练习（逐句）"],
    ["弱点分析", "音素弱点画像 + 自适应难度推荐", "词级错误汇总（跨所有会话）"],
    ["词汇管理", "独立词汇模块：复习队列 + 错误词 + 听写练习", "仅句子级别，无独立词汇管理"],
    ["掌握判定", "FSRS 状态 = REVIEW 且 due > now 且 scheduled_days >= 1", "手动标记「已掌握」"],
    ["学习分析", "趋势分析 + 连续天数 + 改进预测 + 音素统计", "练习热力图（365 天活动日历）"],
    ["记忆模型", "基于稳定性、难度、可检索性的指数衰减", "无"],
]

story.append(make_comparison_table(
    ["维度", "Phonos", "Echoic"],
    learning_data,
    col_widths=[28*mm, 66*mm, 66*mm]
))

story.append(Paragraph(
    "学习系统是 Phonos 最核心的差异化优势。FSRS-4.5 是目前开源间隔重复算法中最先进的实现之一，"
    "其 18 参数模型基于大规模记忆实验数据拟合，能够精确预测用户的记忆衰减曲线，"
    "在最优时间点安排复习，最大化学习效率。Phonos 将 FSRS 应用于句子和词汇两个层级，"
    "配合智能模式（弱点驱动 + FSRS 优先级排序）和顺序模式（按 ID 范围顺序学习），"
    "构成了完整的「评测 - 诊断 - 练习 - 复习」闭环。"
    "弱点分析模块会自动追踪用户在每个音素上的错误率，推荐针对性练习句子，并根据历史表现动态调整难度，"
    "这种自适应学习能力在同类产品中非常罕见。",
    body_style
))

story.append(Paragraph(
    "Echoic 在学习系统方面相对简单，没有内置间隔重复算法，学习进度管理依赖用户手动标记句子的收藏和掌握状态。"
    "其 365 天练习热力图是一个很好的学习激励功能，视觉化展示练习频率和连续性，但缺乏 Phonos 那种基于科学记忆模型的自动调度能力。"
    "词级错误汇总功能可以跨会话聚合单词准确率，帮助用户识别薄弱词汇，但不如 Phonos 的独立词汇管理系统完整——"
    "Phonos 的词汇模块包含了复习队列、错误词统计、听写练习和发音练习等多个子功能。",
    body_style
))

story.append(Paragraph("2.3 听写与内容系统", h2_style))

dictation_data = [
    ["听写练习", "完整：Levenshtein 词对齐 + 逐词评分 + 错误分类", "无独立听写功能"],
    ["错误分类", "拼写错误/漏写/多写/顺序错误", "无"],
    ["听写速度", "0.5x / 0.75x / 1x 三档", "0.5x - 2x 可调"],
    ["句子来源", "内置 100+ 句（sentences.json）", "导入任意音频（本地/URL/VOA/BBC）"],
    ["内容管理", "预设句子库 + 分类 + 难度标签", "收藏集 + 搜索 + 句子状态管理"],
    ["翻译", "5 级回退链（在线+离线）", "LLM 翻译 + 语法分析（OpenAI/Ollama）"],
    ["词典", "50K 词端查词典 + G2P 回退", "无内置词典"],
    ["文化注释", "每句附带文化注释和关键短语", "无"],
]

story.append(make_comparison_table(
    ["维度", "Phonos", "Echoic"],
    dictation_data,
    col_widths=[28*mm, 66*mm, 66*mm]
))

story.append(Paragraph(
    "听写功能是 Phonos 独有的特色模块，基于 Levenshtein 距离的词级对齐算法能够精确识别拼写错误、漏写、多写和顺序错误，"
    "特别是顺序错误检测防止了用户随意排列单词也能得分的漏洞。这种细致的错误分类不仅帮助学习者了解自己的具体薄弱点，"
    "还将错误词自动纳入 FSRS 复习队列，实现听写与词汇复习的联动。"
    "50K 词的端查词典提供了单词释义、词性和 IPA 音标，G2P 回退确保即使词典中没有的词也能获取发音信息。"
    "每个句子附带的翻译、关键短语和文化注释则为语言学习提供了丰富的上下文。",
    body_style
))

story.append(Paragraph(
    "Echoic 在内容管理方面更灵活和开放，最大的优势是支持导入任意音频——用户可以上传本地文件、粘贴音频 URL，"
    "或直接从 VOA Learning English 和 BBC Learning English 的内容库中导入节目。"
    "WhisperX 自动转录音频为文本，wav2vec2 自动对齐音素时间戳，整个过程完全自动化。"
    "LLM 驱动的句子分析（翻译 + 语法分解）是 Echoic 的亮点功能，虽然需要配置 OpenAI 或 Ollama，"
    "但分析深度远超 Phonos 的简单翻译。收藏集管理、句子搜索、掌握状态标记等功能也为大量内容的组织提供了便利。",
    body_style
))

story.append(Paragraph("2.4 口语练习模式", h2_style))

oral_data = [
    ["朗读评测", "支持（音素级评分 + FSRS 评级）", "支持（音素级评分 + A/B 对比）"],
    ["情景对话", "无", "支持（AI 生成情景 + LLM 评价）"],
    ["独白练习", "无", "支持（自由发言约1分钟 + LLM 评分）"],
    ["A/B 对比", "无", "支持（一键播放原音+录音对比）"],
    ["FSRS 评级", "Again / Hard / Good / Easy 四级", "无"],
    ["自动评级", "根据发音分数自动映射 FSRS 评级", "无"],
]

story.append(make_comparison_table(
    ["模式", "Phonos", "Echoic"],
    oral_data,
    col_widths=[28*mm, 66*mm, 66*mm]
))

story.append(Paragraph(
    "Echoic 在口语练习模式上更加丰富，除了基础的朗读评测外，还提供了情景对话和独白练习两种模式，"
    "均由 LLM 驱动评价。情景对话模式下，AI 生成一个场景（如在餐厅点餐），用户用英语回应，"
    "LLM 评价内容的恰当性、相关性和表达质量。独白模式要求用户就给定话题自由发言约一分钟，"
    "LLM 进行综合评分和反馈。A/B 对比功能可以一键连续播放原音和用户录音，帮助学习者通过对比发现差距。"
    "这些功能使 Echoic 在口语综合训练方面比 Phonos 更全面，尤其是 LLM 参与的内容评价维度是 Phonos 完全不具备的。",
    body_style
))

# ========== Section 3: Deployment ==========
story.append(Paragraph("三、部署与运维对比", h1_style))

deploy_data = [
    ["安装复杂度", "中（Python 依赖 + ONNX 模型 + 音频工具链）", "低（Docker Compose 一键启动）"],
    ["外部依赖", "ffmpeg, espeak-ng（可选）", "Docker, ffmpeg, espeak-ng, PostgreSQL"],
    ["数据库", "SQLite（零配置，文件级存储）", "PostgreSQL（需独立部署或 Docker）"],
    ["模型下载", "首次启动自动下载 ONNX 模型", "首次使用自动下载 ASR+对齐模型（约1GB）"],
    ["生产部署", "uvicorn 启动 FastAPI 服务", "make build + make run（前端打包到后端）"],
    ["数据备份", "复制 SQLite 文件 + JSON 缓存", "Docker 卷备份（postgres_data + storage）"],
    ["环境配置", "无需 .env 文件（所有配置有默认值）", "需要配置 .env（至少 DATABASE_URL）"],
    ["跨平台", "Windows/macOS/Linux", "Docker 支持（Linux/macOS/Windows）"],
]

story.append(make_comparison_table(
    ["维度", "Phonos", "Echoic"],
    deploy_data,
    col_widths=[28*mm, 66*mm, 66*mm]
))

story.append(Paragraph(
    "部署体验是 Echoic 明显领先的领域。Docker Compose 一键部署使得从零开始运行整个系统只需要三条命令（clone、cd、docker compose up），"
    "数据库、模型下载、前端构建全部自动化。而 Phonos 的手动安装流程需要用户自行安装 Python 依赖、ffmpeg、音频处理工具链，"
    "还需确保 ONNX Runtime 的正确安装（包括可选的 GPU 支持），对非技术用户来说门槛较高。"
    "不过 Phonos 的 SQLite 架构也有其优势：数据备份只需复制一个 .db 文件，无需维护数据库服务，"
    "对于个人学习工具来说，这种极简架构反而更加适合。所有配置都有默认值，无需创建 .env 文件即可运行。",
    body_style
))

# ========== Section 4: Multi-language ==========
story.append(Paragraph("四、多语言与国际化对比", h1_style))

i18n_data = [
    ["学习语言", "仅英语", "9 种语言（英/日/韩/法/德/西/意/葡/俄）"],
    ["UI 语言", "中文", "7 种 UI 语言"],
    ["音素系统", "ARPAbet（英语专用）", "IPA 国际音标（多语言通用）"],
    ["ASR 多语言", "英语专用模型", "自动下载语言对应 ASR 模型"],
    ["音素评分多语言", "仅英语", "9 种语言自动适配"],
]

story.append(make_comparison_table(
    ["维度", "Phonos", "Echoic"],
    i18n_data,
    col_widths=[28*mm, 66*mm, 66*mm]
))

story.append(Paragraph(
    "多语言支持是 Echoic 相对于 Phonos 的最大优势之一。支持 9 种学习语言和 7 种 UI 语言使得 Echoic 能够服务更广泛的用户群体，"
    "尤其是对日语、韩语、法语、德语等语言学习者来说，Echoic 是目前少有的开源多语言口语练习平台。"
    "基于 espeak-ng 和 wav2vec2 的多语言音素评分方案，虽然单语言精度可能不如 Phonos 针对英语优化的方案，"
    "但其通用性和可扩展性远超 Phonos。Phonos 的 ARPAbet 音素体系是英语专用的，"
    "如果要支持其他语言需要从头实现新的音素对齐和评分逻辑，工作量巨大。",
    body_style
))

# ========== Section 5: Unique Features ==========
story.append(Paragraph("五、各自独有功能", h1_style))

story.append(Paragraph("5.1 Phonos 独有功能", h2_style))

phonos_unique = [
    ["FSRS-4.5 间隔重复", "科学记忆模型驱动的自动复习调度，最大化学习效率"],
    ["听写练习", "Levenshtein 词对齐 + 4 类错误检测 + FSRS 联动"],
    ["最小对立体检测", "12 对中国学习者常见混淆音素，附纠正指导"],
    ["音素真人发音", "Wikipedia IPA 真人录音，点击即听"],
    ["弱点画像与自适应", "自动追踪音素弱点，推荐针对性练习句子"],
    ["独立词汇管理", "复习队列 + 错误词统计 + 听写/发音练习"],
    ["5 级翻译回退", "在线 API 到离线 ONNX 到简易词典的全链路覆盖"],
    ["50K 词典 + G2P", "大规模词典 + 自动音素转换回退"],
    ["用户认证系统", "注册/登录/会话管理，支持多用户"],
    ["文化注释", "每句附带英语文化背景和关键短语解析"],
]

story.append(make_table(
    ["独有功能", "说明"],
    phonos_unique,
    col_widths=[40*mm, 120*mm]
))

story.append(Paragraph("5.2 Echoic 独有功能", h2_style))

echoic_unique = [
    ["任意音频导入", "上传本地文件、URL 导入、VOA/BBC 内容库浏览"],
    ["情景对话模式", "AI 生成情景，LLM 评价内容相关性和表达"],
    ["独白练习模式", "自由发言约1分钟，LLM 综合评分和反馈"],
    ["A/B 对比", "一键连续播放原音和录音，对比发现差距"],
    ["LLM 句子分析", "翻译 + 语法分解（OpenAI / Ollama）"],
    ["9 种学习语言", "英/日/韩/法/德/西/意/葡/俄"],
    ["7 种 UI 语言", "英/简中/繁中/日/韩/法/德"],
    ["暗色模式", "浅色/深色/跟随系统三种主题"],
    ["键盘快捷键", "Space/R/Enter/箭头/Esc 免提操作"],
    ["练习热力图", "365 天活动日历，可视化练习频率"],
    ["Docker 部署", "Docker Compose 一键启动完整系统"],
    ["数据库迁移", "Alembic 管理 schema 变更"],
    ["句子搜索", "在音频文件中按文本搜索句子"],
]

story.append(make_table(
    ["独有功能", "说明"],
    echoic_unique,
    col_widths=[40*mm, 120*mm]
))

# ========== Section 6: Comprehensive Score ==========
story.append(Paragraph("六、综合评分对比", h1_style))

score_data = [
    ["发音评估深度", "9 / 10", "6 / 10"],
    ["学习系统完善度", "9 / 10", "4 / 10"],
    ["内容灵活性", "5 / 10", "9 / 10"],
    ["多语言支持", "2 / 10", "9 / 10"],
    ["用户体验/交互", "5 / 10", "8 / 10"],
    ["代码工程质量", "5 / 10", "8 / 10"],
    ["部署便利性", "5 / 10", "9 / 10"],
    ["离线能力", "9 / 10", "4 / 10"],
    ["中国学习者针对性", "9 / 10", "4 / 10"],
    ["口语综合训练", "5 / 10", "8 / 10"],
    ["可扩展性", "4 / 10", "8 / 10"],
    ["社区成熟度", "3 / 10", "6 / 10"],
]

story.append(make_comparison_table(
    ["评分维度", "Phonos", "Echoic"],
    score_data,
    col_widths=[40*mm, 60*mm, 60*mm]
))

# ========== Section 7: Conclusion ==========
story.append(Paragraph("七、综合评价与适用场景", h1_style))

story.append(Paragraph("7.1 总体结论", h2_style))

story.append(Paragraph(
    "Phonos 和 Echoic 是两个定位不同的项目，不能简单地说哪个「更好」，而应该根据使用场景来判断哪个更适合。",
    body_style
))

story.append(Paragraph(
    "Phonos 的核心竞争力在于其深度优化的英语学习闭环：FSRS-4.5 间隔重复算法提供了科学的复习调度，"
    "12 对最小对立体检测为中国学习者量身定制了发音纠错方案，听写练习模块填补了口语练习平台中听写训练的空白，"
    "弱点画像与自适应推荐实现了真正的个性化学习路径。Phonos 更像是一个「英语发音诊疗师」，"
    "它不仅告诉你对错，还告诉你为什么错、怎么改、什么时候复习，整个系统围绕「科学记忆 + 精准诊断」构建。",
    body_style
))

story.append(Paragraph(
    "Echoic 的核心竞争力在于其开放性和通用性：支持导入任意音频意味着学习内容无限制，"
    "9 种语言支持使其成为多语言学习者的通用工具，Docker 部署和 React 前端展示了更专业的工程实践，"
    "情景对话和独白模式提供了超越朗读的口语综合训练，LLM 驱动的句子分析带来了更深入的语言理解。"
    "Echoic 更像是一个「口语练习工作台」，提供了灵活的工具和丰富的素材，让学习者自由探索。",
    body_style
))

story.append(Paragraph("7.2 适用场景推荐", h2_style))

scene_data = [
    ["中国英语学习者（专注发音纠错）", "Phonos", "最小对立体 + 口型指导 + FSRS 复习"],
    ["多语言学习者", "Echoic", "9 种语言支持，音素评分自动适配"],
    ["需要科学复习计划的人", "Phonos", "FSRS-4.5 间隔重复，自动调度"],
    ["想练习特定音频/视频内容", "Echoic", "支持导入任意音频"],
    ["听写训练需求", "Phonos", "完整听写模块 + 错误分类"],
    ["口语综合训练（对话/独白）", "Echoic", "情景对话 + 独白 + LLM 评价"],
    ["离线使用场景", "Phonos", "全链路离线回退，SQLite 零依赖"],
    ["团队/多用户部署", "Echoic", "PostgreSQL + Docker 适合多用户"],
    ["快速上手体验", "Echoic", "Docker 一键部署"],
    ["深度发音诊断", "Phonos", "音素级诊断 + 真人发音 + 口型指导"],
]

story.append(make_comparison_table(
    ["使用场景", "推荐", "原因"],
    scene_data,
    col_widths=[50*mm, 22*mm, 88*mm]
))

story.append(Paragraph("7.3 Phonos 的改进方向", h2_style))

story.append(Paragraph(
    "如果 Phonos 要在整体竞争力上超越 Echoic，最迫切需要改进的几个方向包括："
    "第一，前端重构——将 Vanilla JS 迁移到 React 或 Vue 等现代框架，实现组件化和模块化，这是后续所有功能扩展的基础。"
    "第二，Docker 部署支持——提供 Docker Compose 配置，大幅降低部署门槛，这是吸引更多用户的关键。"
    "第三，多语言支持——至少支持日语和韩语，扩大用户群体。"
    "第四，音频导入功能——允许用户导入自己的学习素材，打破预设句子库的限制。"
    "第五，暗色模式和键盘快捷键——提升用户体验的基础功能。"
    "第六，LLM 集成——在翻译和句子分析中引入 LLM，提供更深入的语言理解。"
    "在这些改进中，前端重构和 Docker 部署是最优先的，因为它们决定了项目的可维护性和用户获取成本。",
    body_style
))

story.append(Paragraph("7.4 Echoic 可借鉴 Phonos 之处", h2_style))

story.append(Paragraph(
    "同样，Echoic 也可以从 Phonos 中借鉴一些优秀设计："
    "第一，间隔重复算法——这是 Echoic 最缺乏的功能，引入 FSRS 或 SM-2 将大幅提升学习效果。"
    "第二，最小对立体检测——为每种语言添加常见音素混淆对，提供针对性纠错建议。"
    "第三，听写练习——这是一个被大多数口语练习平台忽视的功能，但对词汇记忆和听力理解非常有价值。"
    "第四，独立词汇管理——将词级错误汇总升级为完整的词汇复习系统。"
    "第五，用户认证系统——支持多用户独立学习进度追踪。"
    "第六，离线能力——减少对在线 API 的依赖，提供本地回退方案。"
    "其中，间隔重复算法的缺失是 Echoic 最大的功能性短板，因为口语练习本质上是记忆训练，"
    "没有科学的复习调度，用户容易遗忘之前学过的内容，学习效率大打折扣。",
    body_style
))

# ========== Build ==========
doc.build(story)
print(f"PDF generated: {output_path}")

import os
size = os.path.getsize(output_path)
print(f"File size: {size / 1024:.1f} KB")
