# TAT-QA 复杂子集 B/C/D 对照

## 结论

在冻结的20道TAT-QA公开复杂题上，固定团队（C）和动态团队（D）均明显优于单Agent（B）。
D的Exact Match / F1 / Scale Accuracy为60.0 / 63.35 / 85.0，比C分别高5 / 5 / 5个百分点；
同时D相对C减少7.8% Token和27.5%子Agent，但端到端耗时高25.8%。因此D进入复杂题候选路径，
简单题仍使用B；这些结果是20题开发集工程证据，不包装为大样本统计结论。

## 数据与隔离

- 数据：TAT-QA 官方 `dev` split；
- 子集：10 道 `arithmetic` + 10 道 `multi-span`；
- 清单：`artifacts/phase5_step02/complex_subset_v1/manifest.jsonl`；
- 清单只包含 Case ID、官方题型等选择元数据，不包含答案；
- 两条路径推理阶段均不读取评测 Gold；
- 评分使用项目内保存的官方 TAT-QA Evaluator。

## 总体结果

| 指标 | B：单Agent | C：固定团队 | D：动态团队 |
|---|---:|---:|---:|
| 推理成功率 | 100% | 100% | 100% |
| Exact Match | 30.0% | 55.0% | 60.0% |
| F1 | 37.90 | 58.35 | 63.35 |
| Scale Accuracy | 70.0% | 80.0% | 85.0% |
| 平均Token / 题 | 1,164 | 7,401 | 6,827 |
| 平均端到端耗时 / 题 | 1.06s | 4.40s | 5.53s |
| 平均研究子Agent | 1.0 | 2.0 | 1.45 |
| 平均工具调用 | 0 | 2.0 | 1.45 |

## 分题型结果

官方 Evaluator 的细分结果如下：

| 题型 / 来源 | B EM | D EM | B F1 | D F1 |
|---|---:|---:|---:|---:|
| arithmetic / table（9题） | 33.3% | 55.6% | 33.3 | 55.6 |
| arithmetic / table-text（1题） | 0% | 100% | 0 | 100 |
| multi-span / table（5题） | 40.0% | 20.0% | 53.8 | 33.4 |
| multi-span / table-text（5题） | 20.0% | 100% | 37.8 | 100 |

动态团队的总体优势主要来自算术题和 table-text 多跨度题；纯表格 multi-span 反而退化。
这说明触发条件不能只写成“TAT-QA 使用多 Agent”，还需要结合答案类型与证据来源进一步路由。

## 团队行为与成本

- 平均每题 1.45 个子 Agent；
- 表格推理角色 20 次，量化分析角色 9 次；
- 子 Agent 工具调用总计 29 次；
- Evaluator：18 题 `ACCEPT`，2 题 `ACCEPT_WITH_LIMITATIONS`；
- 定向修复 0 次。

## 决策

1. TAT-QA复杂题允许D晋级候选路径；D相对C仅小幅提高质量，核心价值是按题裁剪角色；
2. arithmetic 和 table-text multi-span 优先触发动态团队；
3. 纯 table multi-span 暂时保留 B，后续修正完整跨度保留与综合输出退化后再评估；
4. 简单题仍默认 B，避免为无必要任务支付约 5.86 倍 Token；
5. 正式 Gate 使用官方 EM、F1、Scale Accuracy 和成本联合判断。

## 产物

- B：`artifacts/phase5_step02/complex_subset_v1/single_agent/tatqa/`；
- C：`artifacts/phase5_step02/complex_subset_v1/fixed_team/tatqa/`；
- D：`artifacts/phase5_step02/complex_subset_v1/dynamic_team/tatqa/`；
- 三条路径均保存逐题结果、失败记录和官方评分输出。
