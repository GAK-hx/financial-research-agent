# Step 01 — 设计规范确认

## 目标

在编码前冻结领域边界、核心Schema、命名空间、工具名单和第一阶段范围，避免下游反复返工。

## 前置条件

- 总体设计文档已阅读；
- 审核人确认以文档评审先于编码。

## 任务

1. 审核Market、Financial、Document、Indicator、Evidence、Execution、Reporting七个域；
2. 冻结`ResearchRequest → ValidationResult`核心数据流；
3. 冻结Iceberg Namespace和Milvus Collection命名；
4. 确定第一版股票池、日期范围和复权口径；
5. 确定财务报表和指标最小范围；
6. 冻结五个候选工具及第一版实际注册工具；
7. 冻结Evidence和Report Claim必需字段；
8. 确定Replan、模型失败降级和部分报告策略；
9. 将决定写入`docs/DECISIONS.md`；
10. 根据决定更新后续步骤PLAN，不写业务代码。

## 交付物

- Accepted架构决定；
- 领域/表/工具/Schema清单；
- 第一阶段明确包含与不包含范围；
- 后续步骤无互相矛盾的口径。

## 验收标准

- `11-review-checklist.md`中第一阶段关键项有明确答案；
- DECISIONS至少完成ADR-001～ADR-008；
- “正式数据”和“Simulation”边界无歧义；
- 任何开发者可根据接口规范独立实现工具而无需猜测字段。

## 不包含

- 代码实现；
- 依赖安装；
- Docker启动。
