# 09 可观测性与评测

## 1. Trace结构

```text
ResearchRun
├── InterpretQuery
├── CreatePlan
├── ValidatePlan
├── ExecuteTasks
│   ├── MarketTool
│   ├── IndicatorTool
│   └── ReportSearchTool
├── BuildEvidence
├── GenerateReport
└── ValidateReport
```

## 2. 每个Span记录

- run_id/task_id；
- 开始/结束时间；
- 状态和错误类型；
- 模型/Prompt版本；
- 工具名和脱敏参数；
- 输入输出数量摘要；
- Token和延迟；
- Evidence数量；
- 重试次数。

不得把API Key或完整敏感配置写入Trace。

## 3. 第一步日志

使用结构化JSON日志和timing即可，端到端示例保存Run结果。OpenTelemetry/Langfuse可在闭环后接入，避免先被平台集成阻塞。

## 4. 评测层次

### 数据评测

完整率、重复率、异常率、增量写入正确性。

### Tool评测

参数校验、数值正确性、错误边界和耗时。

### Retrieval评测

Recall@5、MRR、股票过滤准确率、页码正确率。

### Agent评测

Intent Accuracy、Tool Selection、Argument Accuracy和Trajectory。

### Report评测

Citation Accuracy、Numeric Consistency、Evidence Groundedness、风险覆盖和任务成功率。

## 5. 第一步最小数据集

至少20题：行情5、指标5、研报5、综合3、异常2。每题记录预期QuerySpec、必要工具集合、关键Evidence和最低报告要求。

## 6. 第二步

- 扩展到30～50题；
- 不同模型/Prompt版本对比；
- 失败Trace回灌评测集；
- 在线反馈；
- 回归门禁；
- P95延迟和单次成本监控。

## 7. 待审核决策

- 是否使用Langfuse作为Trace平台？建议先用OpenTelemetry兼容结构，平台后选。
- 报告质量是否使用LLM Judge？建议仅作辅助，数字和引用仍由代码校验。
- 第一版评测数据是否允许基于现有6份研报人工标注？建议允许。

