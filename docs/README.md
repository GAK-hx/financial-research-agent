# Financial Research Agent 文档索引

> 最初设计、前三阶段实现和第四阶段优化方案均保留在本目录。当前待审核入口为
> [phase4-agent-optimization/README.md](phase4-agent-optimization/README.md)。

## 文档目标

这套文档先回答“系统由哪些板块组成、板块之间如何协作、数据和记忆如何管理、两步分别实现什么”，待审核完成后再将设计拆成编码任务。

## 阅读顺序

1. [01-overall-architecture.md](01-overall-architecture.md) — 总体架构与两步边界
2. [02-domain-boundaries.md](02-domain-boundaries.md) — 业务域、数据域和代码域划分
3. [03-data-management.md](03-data-management.md) — 数据采集、存储、质量、血缘和生命周期
4. [04-memory-management.md](04-memory-management.md) — 会话、运行、工作、证据和长期记忆
5. [05-agent-orchestration.md](05-agent-orchestration.md) — 问题理解、计划、执行和报告
6. [06-tools-and-evidence.md](06-tools-and-evidence.md) — 工具接口、权限与Evidence模型
7. [07-rag-and-knowledge.md](07-rag-and-knowledge.md) — 研报摄取、索引、召回和引用
8. [08-reliability-and-governance.md](08-reliability-and-governance.md) — 预算、错误、恢复和完成条件
9. [09-observability-and-evaluation.md](09-observability-and-evaluation.md) — Trace、指标、测试集和评测
10. [10-deployment-and-resources.md](10-deployment-and-resources.md) — Docker、资源与部署边界
11. [11-review-checklist.md](11-review-checklist.md) — 待审核决策清单
12. [DECISIONS.md](DECISIONS.md) — 审核结论与架构决策记录
13. [phase1/README.md](phase1/README.md) — 第一阶段分步实施计划、清单和逐步进度记录
14. [phase2/README.md](phase2/README.md) — LangGraph Harness阶段
15. [phase3-langchain-foundation/README.md](phase3-langchain-foundation/README.md) — LangChain基础框架调整
16. [phase4-agent-optimization/README.md](phase4-agent-optimization/README.md) — 教程复盘与四步Agent能力优化计划

## 两步实施边界

| 板块 | 第一步：Agent编排 | 第二步：完整Harness |
|---|---|---|
| 数据管理 | 日线、研报、基础财务、质量规则 | 调度、补数、血缘、版本与生命周期治理 |
| Agent编排 | Query → Plan → Tools → Evidence → Report | 可持续任务、动态Replan、暂停恢复 |
| 记忆管理 | 单次Run内的工作记忆和Evidence | Session、Workspace、长期记忆、上下文压缩 |
| 工具治理 | 固定白名单、只读工具、Schema校验 | Policy、动态可用性、权限与人工审批 |
| 可靠性 | 超时、有限重试、一次修订 | 幂等、断点恢复、降级、Completion Checker |
| 可观测性 | 结构化日志和基础timing | 完整Trace、运行回放、在线监控 |
| 评测 | 20题最小离线集 | 30～50题回归、版本对比、线上反馈闭环 |

## 当前约束

- 正式行情以AkShare日线为主；
- Iceberg满足日线及中长期分析，暂不引入ClickHouse；
- Mock Kafka/Flink链路仅用于实验，不进入正式Evidence；
- 模型不能直接访问存储或执行任意SQL/Python；
- 第四阶段方案审核完成前，不开始新的业务功能实现。
