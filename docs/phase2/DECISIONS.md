# 第二阶段架构决定

| ID | 主题 | 推荐决定 | 状态 |
|---|---|---|---|
| P2-ADR-001 | 运行时 | 使用LangGraph StateGraph，不使用LangChain高层通用Agent | Accepted |
| P2-ADR-002 | Checkpoint | 使用`AsyncPostgresSaver`，生产状态加密 | Accepted |
| P2-ADR-003 | 业务持久化 | PostgreSQL + SQLAlchemy Async + asyncpg + Alembic | Accepted |
| P2-ADR-004 | Skill | 参考Hermes，建立声明式Skill Registry；模型只能生成DRAFT | Accepted |
| P2-ADR-005 | Tool | 现有Pydantic Tool接口保留，所有正式调用迁入Tool Gateway | Accepted |
| P2-ADR-006 | API | FastAPI Job API + SSE，保留同步`/analyze`兼容 | Accepted |
| P2-ADR-007 | Worker | API/Worker拆分；第一版PostgreSQL领取Run，不加Celery/Redis | Accepted |
| P2-ADR-008 | Memory | Session 30天TTL；Preference显式确认；不保存研究结论 | Accepted |
| P2-ADR-009 | Context | 按节点/Skill压缩模型视图，原始Evidence不可被摘要覆盖 | Accepted |
| P2-ADR-010 | 权限 | 所有研究工具继续只读；Skill不能扩大权限 | Accepted |
| P2-ADR-011 | Replan | 仍为0，LangGraph预留受控扩展边 | Accepted |
| P2-ADR-012 | 默认预算 | 180秒、模型5次、工具12次、并行4、修订1次 | Accepted |
| P2-ADR-013 | 评测 | 20题Regression + 30题Holdout + 10题三次稳定性 | Accepted |
| P2-ADR-014 | Hermes/Pi | 只参考设计，不引入其完整运行时依赖 | Accepted |

审核记录：2026-07-24，用户回复“继续”，据此按总计划进入Step 01；若后续调整决定，新增Superseded记录，不覆盖历史。
