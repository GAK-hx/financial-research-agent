# Step 02 进度

- 状态：`COMPLETE`
- 前置条件：Step 01 Gate 通过
- 计划审核：已确认并实施
- 实现开始：2026-08-08
- 暂停时间：2026-08-08
- 恢复时间：2026-08-08
- Gate 结论：`TECHNICAL_GO`

## 当前状态

- Step 4 已加入多用户并发查询与后端容量治理方案；
- Step 2 的代码、数据库迁移、Docker 服务和设计文档已完成；
- `docker compose config --quiet`、Python `compileall` 和 `git diff --check` 已通过；
- Alembic、Knowledge Lake、PostgreSQL、Milvus、SQLite、HTTP 和 157 项回归均已验证；
- 最新 App、Job API、Worker 和依赖服务已恢复且健康；
- 真实 Flash Gate 已在用户授权后通过；事件 Context 到正式 Event Evidence 的升级进入 Step 03。

## 已确认设计

- [x] 真实公告/新闻来源未冻结前，只交付来源协议和可分发本地样例，不声称实时新闻；
- [x] 关键词索引使用 SQLite FTS5，与 Milvus Dense 通过 RRF 融合，不新增搜索集群；
- [x] 情节记忆默认 TTL 为 180 天，偏好记忆继续由用户显式确认；
- [x] 程序记忆继续由 Git + Skill Registry 承担，不复制到通用 Memory；
- [x] 外部事件原始层使用 Iceberg，状态、游标和版本历史使用 PostgreSQL。

## 已实现并完成确定性验证

- [x] 事件来源协议、Iceberg 原始表、PostgreSQL 游标与状态机；
- [x] ACTIVE-only 查询、冲突并存、版本和来源追踪；
- [x] 父子 Chunk、Milvus + SQLite FTS5、RRF 和增量删除；
- [x] 情节记忆、写读更新反思遗忘、版本历史与幂等反思；
- [x] Context 来源/版本/裁剪/Token Manifest 与输出预算；
- [x] Docker Knowledge Profile、RAG 评测脚本与操作文档；
- [x] 实现过程中记录来源限制、失败样例和数据质量；
- [x] 收尾时生成 Gate 报告并关闭 Step 02。

## 集中验证清单

- [x] 重建受影响的 Docker 镜像；
- [x] 执行 Alembic `20260808_0006` 迁移；
- [x] 执行知识、RAG、Memory/Context 聚焦测试；
- [x] 运行本地事件知识任务两次，核验游标和有效事件幂等；
- [x] 运行研报增量索引与 Dense/Hybrid 冻结集评测；
- [x] 执行完整确定性回归；157/157；
- [x] 使用默认 `deepseek-v4-flash` 完成一条真实模型 Gate；
- [x] 将所有失败原始输出保存到本 Step 的 Markdown 记录。
