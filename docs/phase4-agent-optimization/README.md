# 第四阶段：Agent 能力优化

> 状态：Step 01～05 技术实现与私有发布前 Gate 已完成；等待创建私有 GitHub 仓库  
> 制定日期：2026-08-08  
> 默认模型：`deepseek-v4-flash`

本阶段不是推翻已完成的 LangChain/LangGraph 改造，而是在现有可运行链路上补齐四类能力：

1. 先修正语义、证据和评测口径，建立可复现的 Git 交付基线；
2. 建立事件知识、RAG、记忆和上下文的完整闭环；
3. 增加股票分析、截面与因子能力，并允许一次受控修正；
4. 完成交付、可观测性、可选 MCP 边界和演示界面。

## 文档导航

- [教程结论与项目映射](TUTORIAL_REVIEW.md)
- [目标架构](TARGET_ARCHITECTURE.md)
- [四步总计划](MASTER_PLAN.md)
- [总清单](CHECKLIST.md)
- [阶段进度](PROGRESS.md)
- [Step 01：正确性、评测与 Git 基线](steps/01-correctness-eval-git/PLAN.md)
- [Step 02：知识、RAG、记忆与上下文](steps/02-knowledge-rag-memory/PLAN.md)
- [Step 03：分析工具、Skill 与受控循环](steps/03-analysis-skills-loop/PLAN.md)
  - [分析数据与计算链路](steps/03-analysis-skills-loop/ANALYSIS_PIPELINE.md)
  - [Skill 与受控循环](steps/03-analysis-skills-loop/SKILLS_AND_CONTROLLED_LOOP.md)
  - [运行手册](steps/03-analysis-skills-loop/RUNBOOK.md)
  - [Gate 报告](steps/03-analysis-skills-loop/GATE_REPORT.md)
- [Step 04：多租户并发、交付与演示](steps/04-delivery-interoperability/PLAN.md)
  - [并发交付架构](steps/04-delivery-interoperability/ARCHITECTURE.md)
  - [并发 Gate](steps/04-delivery-interoperability/CONCURRENCY_GATE.md)
  - [MCP 决策](steps/04-delivery-interoperability/MCP_DECISION.md)
  - [运行手册](steps/04-delivery-interoperability/RUNBOOK.md)
  - [Gate 报告](steps/04-delivery-interoperability/GATE_REPORT.md)
- [Step 05：私有发布前验证](steps/05-private-publish-readiness/PLAN.md)
  - [多用户 Gate](steps/05-private-publish-readiness/GATE_REPORT.md)
  - [研报两级工作流](steps/05-private-publish-readiness/RESEARCH_REPORT_WORKFLOW.md)
  - [进度](steps/05-private-publish-readiness/PROGRESS.md)

每一步均有独立 `PROGRESS.md`，实现时只记录该步的范围、证据、问题和 Gate 结论。

## 已确定的工程原则

- 以 LangChain 作为模型、Tool、Retriever、Message 和结构化输出接口层；
- 以 LangGraph 作为有状态工作流与恢复运行时；
- 保留现有 Gateway、Policy、Budget、Evidence、Memory/Context 和报告校验作为金融领域增强层；
- 工作流优先，模型只在问题理解、计划、证据解释和报告生成中发挥作用；
- 所有真实数据访问必须经过受控 Tool，不开放任意 SQL、Python 或交易动作；
- 默认统一使用正式版 `deepseek-v4-flash`，不再把 Pro 作为生产默认或自动降级目标；
- 知识记录外部事实，记忆记录任务经历和用户偏好，两者分别治理；
- 每个 Step 内只做必要冒烟，集中测试和修正在 Step 收尾进行。

## 本阶段明确不做

- 不引入通用多 Agent 团队；
- 不引入 GraphRAG 或图数据库；
- 不做分钟级实时行情、自动交易或高频系统；
- 不开放模型执行任意代码、任意 SQL 或外部写操作；
- 不为了简历堆叠 Kafka、Flink、Kubernetes、A2A 等无实际必要的组件；
- 不在缺少可靠 `available_at/announced_at` 数据前声称完成历史财务因子时点回测。
