# 指标与验收门槛

## 1. 数据底座

| 指标 | 目标 |
|---|---:|
| 100家公司覆盖 | 100/100 |
| 关键值完整率 | >= 99% |
| 原始响应程序化对账率 | >= 99.5% |
| 业务主键重复 | 0 |
| 相同输入重复写入 | 0 |
| Point-in-Time泄漏 | 0 |
| Iceberg快照可复现 | 100% |
| 已知Schema变更发现 | 100% |

这些指标只证明自有数据工程质量，不证明Agent分析准确率。

## 2. 公开 Benchmark 指标

| 数据集 | 主指标 | 补充指标 |
|---|---|---|
| FinanceBench | Gold答案正确性、Evidence Recall@K | 数值匹配、引用精确率、拒答率 |
| FinQA | Execution Accuracy、Program Accuracy | Gold Evidence Recall、单位错误率 |
| TAT-QA | Exact Match、F1 | Scale Accuracy、表格/文本分组结果 |

采用官方评分脚本或与官方口径等价的封装。LLM Judge只可辅助判断FinanceBench自由文本等价性，必须同时保留确定性数值/证据指标，不能由Judge替代标准答案。

## 3. Agent对比

统一比较：直接模型、单Agent+Tool、固定多Agent、动态LangGraph+Evaluator。所有配置使用同一官方split、输入、预算和评分器，Gold不得进入模型上下文。

报告每个公开数据集的官方指标、任务子集结果、延迟、Token、成本、失败类型，以及上下文压缩、缓存、Evaluator和修复的消融结果。

绝对效果目标在单Agent公开基线完成后确定；不得在实测前编写高分。研究目标是复杂子集相对单Agent有稳定增益，同时简单任务不因强制多Agent明显退化。

## 4. 自有场景与并发指标

| 指标 | 目标 |
|---|---:|
| 端到端运行成功率 | >= 95% |
| PIT泄漏 | 0 |
| 未授权Tool调用 | 0 |
| 超预算/无进展循环 | 0 |
| 1/5/20/50用户吞吐与p50/p95/p99 | 报告完整分布 |
| 热缓存p95相对冷查询 | 下降 >= 30% |
| 重叠查询外部调用 | 下降 >= 50% |
| 跨用户数据读取 | 0 |
| Job丢失或重复终态 | 0 |
| Worker驱逐任务恢复率 | 100% |

自有场景不得报告风险Precision、Recall、F1或人工一致性。

## 5. Gate

- Step 01：数据底座通过；三个公开Benchmark的官方数据、split和Gold隔离适配完成；评分入口可运行；
- Step 02：公开Benchmark完成单Agent与动态Agent对比、消融和失败报告；
- Step 03：自有数据的并发、缓存、Docker/K8s、恢复和成本报告完成；
- 网络或Provider失败必须保存失败记录，不能计为业务通过；
- 只有报告、原始汇总和失败案例同时存在时才能标记Step完成。
