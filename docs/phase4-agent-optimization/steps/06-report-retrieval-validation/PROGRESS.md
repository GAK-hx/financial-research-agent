# Step 06 进度

## 当前状态

- 状态：`COMPLETE`
- 当前任务：Step 06 Gate 已通过，下一步进入 Step 07 实现前检查
- 开始日期：2026-08-08
- 默认模型：`deepseek-v4-flash`
- 是否已开始业务编码：是，已完成
- 是否已执行测试：是，专项 6/6、全量离线 164/164（另有 23 项环境跳过）

## 已完成

- [x] 审查现有 `report_search`、RAG 数据模型和混合检索链路
- [x] 审查 QueryInterpreter、Planner、PlanValidator 和 Skill Evidence 要求
- [x] 审查 LangGraph 当前节点、状态和 Evidence Sufficiency 补充策略
- [x] 审查 ContextBuilder、Evidence 保护与报告校验规则
- [x] 审查现有 RAG、编排、报告和上下文测试覆盖
- [x] 确认当前数据源为已登记 PDF 研报索引，不假设实时供应商 API
- [x] 完成 `PLAN.md`、`ARCHITECTURE.md` 和 `CHECKLIST.md`
- [x] 拆分候选 Tool 与受控正文 Tool，旧 `report_search` 仅保留内部兼容类
- [x] 增加 LangGraph 请求解析、候选校验、深度决策和正文检索节点
- [x] 增加按租户/用户/会话和 TTL 保存的最近候选集
- [x] 增加候选清单/深析上下文范围与 Context Manifest 记录
- [x] 增加目标价、评级、预测等 `ReportFact` 及来源链校验
- [x] 将研报自然语言数字校验收窄到高风险结构化事实
- [x] API 输出候选范围、选中文档、缺失文档和类型化事实
- [x] 更新 Skill、LangChain Tool、评测集和旧工具轨迹
- [x] 专项测试 6/6；全量离线回归 164 通过、23 项环境跳过
- [x] Ruff 与 `git diff --check` 通过
- [x] DeepSeek V4 Flash 合成证据 Gate 通过，0 错误、0 警告
- [x] 完成 `RUNBOOK.md`、`GATE_REPORT.md` 和在线原始输出记录

## 已确定的设计结论

- 保持单 Agent、单 LangGraph，不增加通用多 Agent；
- 拆分 `report_candidate_search` 与 `report_content_search`；
- 默认 90 天 Top 5，文档少于 3 份时扩大到 180 天；
- 候选清单不把完整父块正文送入模型；
- 正文读取只能针对当前或同会话受控候选集；
- 普通深析最多 3 份，机构分歧/预测对比最多 5 份；
- 候选 Evidence 不能支持目标价、预测或详细观点；
- 研报关键数字改用类型化事实，普通叙述不再统一严格正则；
- 不增加 Docker 服务，不在本 Step 重写最终 README。

## 已确认的实现参数

1. 少于 3 份才从 90 天扩大到 180 天；
2. 普通深析最多 3 份、跨机构比较最多 5 份；
3. 候选列表只给 160 字以内命中摘要，不调用模型生成摘要；
4. 同会话保存带 TTL 的最近候选集，以支持“分析第 2 份”；
5. 本 Step 先复用现有块索引去重，不立即新建文档级 Milvus collection。

## 与 Step 07 的衔接

- Step 06 先产出可序列化的候选集、正文 Evidence 和类型化事实；
- Step 07 再将查询、分析与输出分离，并增加持久化、版本键和跨用户复用；
- Step 06 不直接依赖 Elasticsearch，避免改变现有 PDF RAG 的稳定链路。

## 进度记录

| 日期 | 状态 | 记录 |
|---|---|---|
| 2026-08-08 | DESIGN_REVIEW | 完成现状审查和 Step 06 详细方案，等待审核 |
| 2026-08-15 | READY_FOR_IMPLEMENTATION | 用户确认开始；补充与统一检索缓存架构的衔接边界 |
| 2026-08-15 | COMPLETE | 两级研报链路、分层上下文与类型化事实校验完成；离线和 Flash Gate 通过 |
