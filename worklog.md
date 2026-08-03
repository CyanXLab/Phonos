---
Task ID: 1-7
Agent: Main
Task: 修复Phonos英语口语练习平台6个主要问题

Work Log:
- 修复"需要加强的单词"显示问题：添加_clean_word函数统一过滤标点、缩写、功能词
- 修复FSRS复习调度：反转权重（新词7.0>复习3.0），排除LEARNING/RELEARNING状态避免短间隔重复
- 修复读过的句子显示为"新句"：所有句子加载API检查FSRS卡片状态，state>0标记为review
- 修复认知指标不准确：速度改用评测记录+实际活跃天数，保持率改用评测得分，覆盖率改用评测记录/sentences.json
- 修复热力图格子不显示：添加weekday对齐偏移，修复CSS月份标签偏移，添加7天标签
- 添加针对性建议：增加音素薄弱项和单词发音/听写针对性建议
- 增强成就系统：新增6个成就（300次练习、14天连续、50词掌握、50音素、听写入门/达人）

Stage Summary:
- 修改文件：learning_algorithm.py, fsrs_db.py, main.py, metacognition.py, app.js, style.css
- 核心修复：_clean_word统一过滤、FSRS权重反转、句子类型检查、认知指标重算、热力图渲染修复
