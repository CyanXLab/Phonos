"""Phonos 商业级升级包结构。

此包为 Phonos v3 升级模块，包含：
- core: 配置、日志、安全、中间件
- api: APIRouter 拆分后的路由模块
- schemas: Pydantic v2 数据模型
- services: PronunciationProvider 抽象、强制对齐、VAD、Whisper 等
- models: 数据库 ORM（SQLAlchemy 2）
- db: 数据库会话与初始化

设计原则：
1. 不破坏性重写：原 backend/*.py 模块继续工作，新模块通过 register_* 接入
2. 渐进迁移：原 main.py 通过 lifespan 加载新模块，路由通过 include_router 引入
3. 本地优先：所有新功能默认本地推理；商业 API 默认关闭，需用户主动启用
4. 隐私安全：默认不上传用户音频，所有联网功能需显式开关
"""

__version__ = "3.0.0"
