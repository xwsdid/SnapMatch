# 4C

## 目录总览（后端核心模块）

本仓库后端以 Go 为主，按“路由/控制层/服务层/数据模型/推理与外部推理服务”分层组织。router 负责 Gin 路由与中间件装配；controller 负责 HTTP 入参解析与统一返回；service 聚合业务规则、数据库读写与推荐/统计逻辑；dao 提供数据库连接与迁移；model 定义各表结构与约束；composition 与 comp_model 分别承载构图推理实现与模型训练/导出脚本；vlm_api 是独立 Python（FastAPI）推理微服务，提供多模态能力并供 Go 侧转发调用。每个目录下均提供 readme.md（vlm_api 为 readme1.md）用于逐文件说明。