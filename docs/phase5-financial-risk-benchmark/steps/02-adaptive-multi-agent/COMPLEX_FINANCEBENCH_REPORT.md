# FinanceBench 复杂子集 B/D 对照

## 结论

在冻结的 20 道 FinanceBench 公开复杂题上，单 Agent（B）与动态团队（D）均完成 20/20 推理，
且推理阶段均未读取评测 Gold。动态团队没有提高确定性数值准确率或证据召回，证据精确率下降，
Token 开销接近翻倍。因此 FinanceBench 暂不将动态团队晋级为默认路径，默认继续使用单 Agent。

事后同模型语义 Judge 给出 D 比 B 高 10 个百分点的开发信号，但只对应额外答对 2 道题，且候选模型
与 Judge 都是 `deepseek-flash`。该指标仅用于错误分析，不作为正式效果结论。

## 数据与隔离

- 数据：FinanceBench `open_source` split；
- 子集：20 道官方 Gold 至少需要 2 个证据页的题目；
- 清单：`artifacts/phase5_step02/complex_subset_v1/manifest.jsonl`；
- 清单不包含问题答案或 Gold 证据正文；
- 检索输入仅来自官方 10-K PDF 页面索引；
- Gold 只在两条推理路径结束后由本地评分器读取。

## 结果

| 指标 | B：单 Agent | D：动态团队 | 变化 |
|---|---:|---:|---:|
| 推理成功率 | 100% | 100% | 0pp |
| 确定性数值准确率 | 45.0% | 45.0% | 0pp |
| 完全字符串匹配 | 25.0% | 25.0% | 0pp |
| Gold 证据页 Recall | 62.5% | 62.5% | 0pp |
| Gold 证据页 Precision | 66.3% | 60.3% | -5.9pp |
| 同模型语义 Judge | 55.0% | 65.0% | +10.0pp |
| 平均 Token / 题 | 17,073 | 33,401 | +95.6% |
| 平均端到端耗时 / 题 | 5.10s | 11.76s | +130.8% |

动态团队 20 题共选择 39 个子 Agent：量化分析 18 次、文档检索 13 次、表格推理 7 次、
披露审计 1 次。平均每题 1.95 个子 Agent，子 Agent 工具调用共 73 次，未触发定向修复。

## 同模型 Judge 差异题

只有两题由 B 的 `INCORRECT` 变为 D 的 `CORRECT`：

- `financebench_id_10420`：D 给出与参考答案等价的 ROA 百分比表达；
- `financebench_id_03069`：D 找到 D&A 与收入并完成 4.18% 计算。

没有题目由 B 的 `CORRECT` 退化为 D 的 `INCORRECT`。但确定性数值评分没有净提升，说明同模型
Judge 对单位表达与舍入更宽容；这一差异必须保留为评价限制，不能直接解释为动态团队稳定提升。

## 决策

1. FinanceBench 默认路径保留 B：检索覆盖检查 + 单 Agent 回答；
2. D 不进入默认在线路径，也不以本轮结果宣称动态团队优于单 Agent；
3. 后续若保留动态团队，只允许由明确复杂度信号触发，并须先改善证据精确率与成本；
4. 正式 Gate 同时报告确定性指标和同模型 Judge，但晋级主要依据确定性数值、证据指标和公开官方评分。

## 产物

- B：`artifacts/phase5_step02/complex_subset_v1/single_agent/financebench/`；
- D：`artifacts/phase5_step02/complex_subset_v1/dynamic_team/financebench/`；
- 两条路径均保存逐题结果、失败记录、确定性评分与语义评分。
