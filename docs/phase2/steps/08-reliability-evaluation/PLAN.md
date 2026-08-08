# Step 08 — 恢复、安全、Regression与Holdout评测

## 目标

通过故障注入、攻击性测试、未见题和重复稳定性测试，证明第二阶段不只是“能跑”，而是可恢复、受约束、可量化。

## 前置条件

- Gate 07已通过；
- 固定代码、配置、Skill、Prompt、模型和数据Snapshot版本；
- Holdout未用于开发调参。

## 评测集

| 集合 | 数量 | 用途 |
|---|---:|---|
| Phase 1 Regression | 20 | 验证不退化 |
| Phase 2 Holdout | 至少30 | 验证未见问题泛化 |
| Stability Set | 10题×3次 | 验证路径、Skill、Evidence和结论稳定性 |
| Fault Cases | 按类型覆盖 | 验证恢复与幂等 |
| Security Cases | 按策略覆盖 | 验证越权、注入、隔离和脱敏 |

## 子任务

1. 封存评测问题、预期Intent、允许Tool、必需Evidence和评分规则；
2. 定义正确性、完整性、引用、Skill选择、Policy、Budget、稳定性和恢复指标；
3. 注入Worker Kill、API重启、DB短断、模型超时/限流、Tool失败和SSE断开；
4. 验证副作用幂等、Checkpoint恢复、Lease回收和唯一终态；
5. 测试Prompt Injection、越权Tool、参数越界、Skill升权、Memory污染和跨租户访问；
6. 测试Budget耗尽、并发Reserve竞态、重试风暴和费用上限；
7. 运行20题Regression并与第一阶段基线对比；
8. 一次性运行至少30题Holdout，区分系统缺陷、数据缺口和评测标注问题；
9. 运行10题各3次，计算Skill、Tool集合、Evidence集合、数字和报告结构一致性；
10. 分别运行Memory开/关、Compression开/关和Skill开/关A/B；
11. 采集成功率、P50/P95、Token、费用、DB增长、峰值内存和CPU；
12. 产出失败分类、修复清单和验收阈值结论，不隐藏未通过项。

## 核心指标

- 合法终态率和恢复成功率；
- 重复副作用率和重复Evidence率；
- Intent/Skill选择准确率；
- Tool成功率、Evidence覆盖率、引用有效率；
- Policy攻击拦截率和误拦率；
- Budget超限率；
- Compression数字/来源保留率；
- 稳定性集的Skill/Tool/Evidence/数字一致性；
- 延迟、Token、费用和资源。

## 交付物

- 版本化Regression/Holdout/Stability数据集；
- 故障注入和安全测试套件；
- 完整评测报告、原始指标和失败分类；
- 待修复项与Step 09候选验收阈值；
- 已更新的`PROGRESS.md`。

## Gate 08

- 已完成20 + 30 + 10×3全部评测；
- 副作用重复、越权成功、跨租户泄漏和Evidence来源丢失均为0；
- 所有关键阈值已用实测数据固定；
- 严重缺陷已清零，其余问题有明确风险与计划；
- 用户审核评测方法和结果。

## 停止条件

任何越权、跨租户泄漏、重复副作用或Evidence来源丢失都是阻断性缺陷，不得进入阶段验收。
