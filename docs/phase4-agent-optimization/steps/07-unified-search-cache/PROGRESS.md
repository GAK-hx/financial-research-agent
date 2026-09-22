# Step 07 进度

## 当前状态

- 状态：`PASS_PARTIAL_ONLINE`
- 已完成：业务代码、数据库迁移、LangGraph 接入、离线并发 Gate、真实 ES、Flash 最小在线 Gate、全量回归
- 未完成：真实 Tavily -> Elasticsearch -> DeepSeek Flash 联合在线 Gate
- 默认模型：`deepseek-v4-flash`
- Docker 状态：本项目 app/job-api/PostgreSQL/ES 健康，Worker 正常运行

## 已实现

- [x] 查询、分析、输出三层模型与 LangGraph 节点
- [x] PostgreSQL 原子工作单元、Job 依赖、快照、分析产物与依赖表
- [x] 数据库 single-flight、租约心跳、过期接管和幂等完成
- [x] 公共跨用户复用与 tenant 私有键隔离
- [x] Tavily Provider、受控 `web_search` StructuredTool 和结构化失败
- [x] URL 规范化、content hash、文档版本与 BM25/过滤查询
- [x] ES 9.3.6 可选容器、官方 Python client 9.3.0、mapping/alias/初始化命令
- [x] 24 小时回看增量、水位推进、TTL、stale-if-error
- [x] AnalysisArtifact 校验、版本键、依赖失效与 PresentationEnvelope
- [x] API/SSE 缓存决策、刷新状态、数据截止时间和产物链路
- [x] 5 用户 × 5 股票、11 个去重标的的离线交叉查询 Gate
- [x] 全量回归：168 passed，23 skipped
- [x] PostgreSQL migration `20260815_0008` 真实升级
- [x] Elasticsearch 9.3.6 真实索引、版本化 upsert 与检索
- [x] DeepSeek V4 Flash 模型规划、Tool、Skill、报告与校验流程
- [x] 8 个发生实现变化的内置 Skill 升级为 `1.1.0`
- [x] Docker 依赖构建增加长超时、重试与 wheel cache

## 本轮验证结果

| 项目 | 结果 |
|---|---:|
| 首轮逻辑检索 | 25 |
| 首轮唯一外部工作 | 11 |
| 首轮 inflight join | 14 |
| 首轮外部调用节省率 | 56% |
| 第二轮 5 股票（3 重叠 + 2 新增） | 仅 2 次新增工作 |
| TTL 人工过期 3 股票 | 3 次 stale refresh |
| AnalysisArtifact 依赖变化 | 仅相关产物失效 |
| 全量离线测试 | 168 passed / 23 skipped |
| Ruff / compile / Alembic offline SQL | 通过 |
| PostgreSQL 真实迁移与新增表 | 通过 |
| ES new / unchanged / updated / search | 1 / 1 / 1 / 1，版本=2 |
| Flash Agent 最小在线流程 | HTTP 200，报告完成，校验通过 |
| 未配置搜索 Provider | `WEB_SEARCH_NOT_CONFIGURED`，符合预期 |

## 在线 Gate 前仍需要

1. `WEB_SEARCH_API_KEY`（当前实现为 Tavily）；
2. 允许向 Tavily 发送一组不含私有数据的测试查询。

没有搜索 key 时，不能把 fake Provider 结果写成“在线网络搜索已通过”。

## 进度记录

| 日期 | 状态 | 记录 |
|---|---|---|
| 2026-08-15 | PLANNED | 完成统一检索与缓存架构计划 |
| 2026-08-15 | IMPLEMENTED_OFFLINE | 完成代码、迁移、离线并发 Gate 与全量回归；Docker 未启动，在线 Gate 待 key |
| 2026-08-16 | PASS_PARTIAL_ONLINE | PostgreSQL、ES 与 Flash 真实流程通过；Tavily 联合 Gate 因缺 key 待验证 |
