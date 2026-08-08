# 第二阶段：LangGraph Agent Harness

第二阶段在第一阶段已完成的Agent编排闭环上，用LangGraph承担状态图、Checkpoint和恢复，用项目自身的金融Harness承担Skill、Tool/Evidence、Policy/Budget、Memory/Context和Validator治理。

面向完整九步交付的可读架构与模块介绍见
[`docs/project-introduction/README.md`](../project-introduction/README.md)。该文档明确区分当前完成态和后续目标态。

当前已完成Step 01—09工程实现：正式运行时已经是LangGraph StateGraph +
AsyncPostgresSaver，金融Harness已包含Skill、Gateway、Policy/Budget、
Memory/Context、Completion治理，以及PostgreSQL Job API、SSE和双Worker。
Step 08的Regression、Holdout、稳定性、故障与安全评测已经通过，Step 09部署、
备份恢复、同步/异步Run和文档交付已经完成；当前只等待用户最终人工确认。

## 审核入口

- `ARCHITECTURE.md`：目标架构、边界和技术选型；
- `MASTER_PLAN.md`：九步实施路线与Gate；
- `SKILL_DESIGN.md`：Skill定义、选择、版本、发布与首批Skill；
- `MEMORY_CONTEXT_DESIGN.md`：Memory分层、Context构建、压缩与Evidence保护；
- `FRAMEWORK_COMPARISON.md`：LangGraph、LangChain Agent、Hermes、Pi与完全自研对比；
- `DECISIONS.md`：14项待审核决定；
- `CHECKLIST.md`：阶段验收清单；
- `PROGRESS.md`：总进度；
- `steps/*/PLAN.md`与`PROGRESS.md`：每步输入、任务、测试、交付物和实时进度。

当前实现说明：

- `steps/05-gateways-policy-budget/GATEWAY_DESIGN.md`：正式模型/Tool调用路径；
- `steps/05-gateways-policy-budget/POLICY_AND_SECURITY.md`：权限与脱敏边界；
- `steps/05-gateways-policy-budget/BUDGET_LEDGER.md`：事务预算语义；
- `steps/05-gateways-policy-budget/DEEPSEEK_V4_PROFILE.md`：V4 Pro 1M接入。
- `steps/06-memory-context/EVIDENCE.md`：Memory隔离、Context A/B与20题回归；
- `steps/07-api-worker-observability/API_DESIGN.md`：Job API和同步兼容；
- `steps/07-api-worker-observability/WORKER_DESIGN.md`：PostgreSQL Lease与双Worker；
- `steps/07-api-worker-observability/EVIDENCE.md`：122项测试和真实V4 Pro Job证据。
- `steps/08-reliability-evaluation/FINAL_EVALUATION_REPORT.md`：冻结评测与安全结论；
- `steps/09-acceptance/ACCEPTANCE_REPORT.md`：最终工程验收；
- `steps/09-acceptance/OPERATIONS_RUNBOOK.md`：部署、备份、Memory和保留操作；
- `steps/09-acceptance/DEMO_SCRIPT.md`：项目演示流程。

## 执行原则

1. 每个Step只实现已审核计划内的能力；
2. 小阶段只做最小可行性测试，Step末做一次全量回归；
3. 每一步必须更新对应`PROGRESS.md`，通过当步Gate才进入下一步；
4. 任何新能力都不能破坏第一阶段Tool/Evidence/Validator边界。
