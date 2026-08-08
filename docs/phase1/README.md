# 第一阶段实施文档

> 状态：`COMPLETED / Accepted`；第一阶段已于2026-07-15通过用户审核。

整体框架、技术栈、数据、部署和验收结果见[TECHNICAL_SUMMARY.md](TECHNICAL_SUMMARY.md)。第二阶段Harness方案位于[../phase2/](../phase2/README.md)。

第一阶段目标是完成单次研究任务的受约束Agent编排闭环：

```text
真实数据 → 类型化工具 → 结构化计划 → Evidence → 报告 → 校验
```

## 文档入口

- [MASTER_PLAN.md](MASTER_PLAN.md)：实施顺序、依赖、里程碑和验收门
- [CHECKLIST.md](CHECKLIST.md)：跨步骤总清单
- [PROGRESS.md](PROGRESS.md)：阶段级总进度
- [PROGRESS_RULES.md](PROGRESS_RULES.md)：进度记录规则

## 十个步骤

| 步骤 | 主题 | 计划 | 进度 |
|---:|---|---|---|
| 01 | 设计规范确认 | [PLAN](steps/01-contracts/PLAN.md) | [PROGRESS](steps/01-contracts/PROGRESS.md) |
| 02 | 数据管理基础 | [PLAN](steps/02-data-management/PLAN.md) | [PROGRESS](steps/02-data-management/PROGRESS.md) |
| 03 | 行情日线链路 | [PLAN](steps/03-market-ingestion/PLAN.md) | [PROGRESS](steps/03-market-ingestion/PROGRESS.md) |
| 04 | 行情与指标工具 | [PLAN](steps/04-market-tools/PLAN.md) | [PROGRESS](steps/04-market-tools/PROGRESS.md) |
| 05 | 财务数据与工具 | [PLAN](steps/05-financial-tools/PLAN.md) | [PROGRESS](steps/05-financial-tools/PROGRESS.md) |
| 06 | 研报知识库与检索 | [PLAN](steps/06-rag/PLAN.md) | [PROGRESS](steps/06-rag/PROGRESS.md) |
| 07 | Agent编排 | [PLAN](steps/07-orchestration/PLAN.md) | [PROGRESS](steps/07-orchestration/PROGRESS.md) |
| 08 | Evidence、报告与校验 | [PLAN](steps/08-reporting-validation/PLAN.md) | [PROGRESS](steps/08-reporting-validation/PROGRESS.md) |
| 09 | API与基础可观测性 | [PLAN](steps/09-api-observability/PLAN.md) | [PROGRESS](steps/09-api-observability/PROGRESS.md) |
| 10 | 测试、评测与验收 | [PLAN](steps/10-testing-acceptance/PLAN.md) | [PROGRESS](steps/10-testing-acceptance/PROGRESS.md) |

## 状态词

`NOT_STARTED`、`IN_PROGRESS`、`BLOCKED`、`IN_REVIEW`、`COMPLETED`。

步骤只有在验收证据被记录且审核通过后才能标记为`COMPLETED`。
