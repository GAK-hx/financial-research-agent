# B/C/D 消融 Canary 报告

## 结论

本轮使用三个公开 Benchmark 的相同前5题，对比：

- B：共享相同检索与公开训练 Skill 的单 Agent；
- C：不做任务判断、固定运行完整研究角色的多 Agent；
- D：由 Supervisor 选择最小研究团队的动态多 Agent。

15题均由 DeepSeek V4.1 Flash 在 Docker 内运行。推理阶段未读取评测 split 的答案、
Gold Evidence 或 Gold Program。样本很小，只用于开发诊断，不是最终项目指标。

当前结论是：这些偏简单的公开题上，单 Agent 性价比最好；动态团队尚未证明整体质量优势。
动态编排的价值主要体现在相对固定团队减少不必要子 Agent，而不是相对单 Agent 降低成本。

## 质量结果

| Benchmark | 指标 | B 单Agent | C 固定团队 | D 动态团队 |
|---|---|---:|---:|---:|
| FinanceBench | 语义正确率（同模型裁判） | 80% | 100% | 80% |
| FinanceBench | 数值诊断准确率 | 60% | 60% | 80% |
| FinanceBench | Evidence Recall | 93.3% | 93.3% | 93.3% |
| FinanceBench | Evidence Precision | 60.0% | 80.0% | 78.3% |
| FinQA | Execution Accuracy | 80% | 80% | 80% |
| FinQA | Program Accuracy | 60% | 80% | 80% |
| TAT-QA | Exact Match | 40% | 40% | 40% |
| TAT-QA | F1 | 58.8 | 58.8 | 58.2 |

FinanceBench 的候选模型和裁判模型均为 `deepseek-flash`，存在同源偏差；数值诊断又会要求
开放式参考答案中的全部数字。因此两者都只能作为开发信号，不能单独作为最终结论。

## 成本结果

| Benchmark | 配置 | 平均研究Agent数 | 平均模型调用 | 平均工具调用 | 平均Token |
|---|---|---:|---:|---:|---:|
| FinanceBench | B 单Agent | 1.0 | 3.0 | 3.2 | 18,041 |
| FinanceBench | C 固定团队 | 3.0 | 5.0 | 5.2 | 50,179 |
| FinanceBench | D 动态团队 | 1.6 | 4.6 | 3.4 | 31,187 |
| FinQA | B 单Agent | 1.0 | 1.0 | 0.0 | 1,437 |
| FinQA | C 固定团队 | 2.0 | 4.0 | 4.0 | 8,014 |
| FinQA | D 动态团队 | 2.0 | 5.0 | 4.0 | 9,377 |
| TAT-QA | B 单Agent | 1.0 | 1.0 | 0.0 | 808 |
| TAT-QA | C 固定团队 | 2.0 | 4.0 | 2.0 | 6,182 |
| TAT-QA | D 动态团队 | 1.4 | 4.4 | 1.4 | 5,495 |

相对固定团队，动态团队在15题合计：

- 研究子 Agent 数减少28.6%；
- Token 减少28.5%；
- 工具调用减少21.4%，未达到25%暂定目标；
- 因为多了一次 Supervisor 调用，总模型调用并未减少。

FinQA 每题都需要表格理解和程序计算，Supervisor 无法裁掉固定角色，反而产生额外开销；
这类任务应直接路由到固定的两角色图。TAT-QA 与 FinanceBench 中的简单查找题可以减少子 Agent，
但相对单 Agent 仍然昂贵。

## 检索覆盖修复

FinanceBench 增加了“首轮检索—覆盖检查—最多一次补查”，并把最终上下文继续限制在12页。
覆盖模型只提出缺失概念；代码规则在 `missing_concepts` 非空时强制执行一次补查，避免模型同时输出
`COMPLETE` 和缺失项时跳过查询。

同题5例中，动态团队 Evidence Recall / Precision 从修复前的60.0% / 46.7% 提升至
93.3% / 78.3%。`financebench_id_00499` 的单例语义结果可从错误修正为正确，但多次生成仍有
定性措辞波动，因此整体语义正确率仍为80%。

## 下一轮冻结方案

不再针对当前5题调参。下一轮从官方 split 中按公开结构字段预先冻结复杂子集：

1. FinanceBench：至少需要两个证据页或跨报表计算的问题；
2. FinQA：官方程序至少包含两个连续操作的问题；
3. TAT-QA：官方 `arithmetic` 或 `multi-span` 类型问题。

Gold 仅用于离线选层和最终评分，选中的答案、证据和程序不得进入 Agent 输入。先比较 B 与 D；
只有复杂子集出现稳定质量增量，再投入完整 C/D 大样本和三次重复稳定性测试。
