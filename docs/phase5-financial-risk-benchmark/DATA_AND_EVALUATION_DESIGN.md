# 数据与评测设计

## 1. 两类数据严格分工

| 数据 | 用途 | 可报告的结果 |
|---|---|---|
| FinanceBench、FinQA、TAT-QA | Agent效果评测 | 官方答案/证据对应的准确率、F1、执行准确率、检索指标 |
| 自有100家公司数据 | 业务演示和系统测试 | 数据覆盖、PIT、成功率、延迟、吞吐、成本、缓存和故障恢复 |

不基于自有公司数据建立 Benchmark、人工标签、私有 Holdout 或风险 Precision/Recall。现有程序化风险信号只是业务候选，不是真值。

## 2. 公开 Benchmark

### FinanceBench

- 官方公开样本150例；
- 评估财报检索、基于证据回答和引用；
- 使用公开 Gold Answer、Evidence、Justification；
- 其论文评测包含人工判断，项目自动评测需分别报告确定性数值匹配、证据召回和辅助语义判断，不能伪称官方自动分数。

### FinQA

- 使用官方 train/dev/test；
- 评估财务数值推理、支持事实和可执行推理程序；
- 使用官方 Execution Accuracy、Program Accuracy 口径。

### TAT-QA

- 使用官方 train/dev/test gold；
- 评估表格与文本联合推理、数值和量纲；
- 使用官方 Exact Match、F1 和 scale 处理。

## 3. Gold 隔离

适配层将每个官方 split 拆为：

- `inputs/`：问题、允许的文档引用或上下文；
- `gold/`：答案、证据、程序、推导和量纲，只允许评分器读取；
- `manifest.json`：官方来源、split、数量、任务和评分政策。

Agent、Tool 和 LangGraph State 不得读取 `gold/`。开发只使用官方 train/dev；最终结果使用官方 test。FinanceBench公开150例整体作为公开评测集，不再人为制造私有切分。

## 4. 自有数据分层

| 层级 | 内容 | 主要职责 |
|---|---|---|
| ODS | 原始财务响应、公告和采集批次 | 原样保存和来源追踪 |
| DWD | 标准化财务事实、披露事件和文档片段 | 统一主体、期间、单位和字段 |
| DWS | 公司—报告期风险特征、滚动值和Evidence链接 | 确定性计算和Agent输入 |
| ADS | 风险候选、报告、运行状态和缓存指标 | 业务演示和性能分析 |

自有数据始终保留 `as_of_date`、来源发布时间、系统观测时间和 Iceberg Snapshot，禁止使用截止日后的数据。

## 5. 评测输出

每次公开 Benchmark 运行保存：

- 数据集、官方 split 和原始案例ID；
- 模型、Prompt、Skill、Tool Schema和编排版本；
- Agent答案、证据、程序/计算过程和Trace；
- 官方或官方口径指标；
- 延迟、Token、模型/Tool调用和成本；
- 错误类型与一次定向修复结果。

每次自有数据测试只保存系统指标和演示结果，不与公开 Benchmark 分数混合。
