# Step 02 公开 Benchmark 基线 Canary

## 结论

已使用 DeepSeek V4.1 Flash（API 模型名 `deepseek-flash`）在 Docker 内完成三个公开
Benchmark 的 20 题开发 Canary。Gold 答案、Gold Evidence 和 Gold Program 均未进入推理输入；
评分阶段才读取官方参考答案。

该结果只用于发现系统问题和建立后续 A/B/C/D 对照线，不是最终全量成绩，也不作为简历指标。

| Benchmark | 当前路径 | 样本 | 推理成功率 | 公开评分结果 |
|---|---|---:|---:|---|
| FinanceBench | 单 Agent：检索计划→页级检索→回答 | 20 | 100% | 数值准确率 45%；证据 Recall 70%；证据 Precision 55% |
| FinQA | 直接回答 | 20 | 100% | 官方 Execution 40%；Program 35% |
| TAT-QA | 直接回答 | 20 | 100% | 官方 EM 30%；F1 48.25；Scale 85% |

## 已发现的问题

1. FinanceBench 的主要瓶颈已从“能否找到页面”转为“能否基于证据选择正确数字并完成计算”。
2. FinQA 有 7 题程序结构错误，说明需要受控计算工具和程序执行反馈，而不是继续增加提示词。
3. TAT-QA 对完整 span、多 span 和表格—文本联合推理较弱，适合增加专门的表格推理与复核角色。
4. 首轮 5 个结构化输出失败不是网络错误：2 个检索计划多给了候选查询，3 个回答使用了题意相关但不符合统一字段的 JSON。

## 本轮修正

- 生成层允许 Supervisor 多给候选检索词，Harness 只执行前三个，从执行预算处控制行为；
- LangChain JSON 模式显式把 Pydantic 输出结构传给模型；
- 常见代码块/前后文本由本地确定性解析恢复，不额外调用模型；
- 网络、限流和服务端错误继续按原重试策略处理；结构错误不再把同一请求机械重试四次；
- 支持保存原始输出，并仅重跑失败题。修正后 5 题均完成，三组 Canary 推理成功率均为 100%。

## 下一步

以这组真实弱项驱动多 Agent，而不是先堆角色：

1. 建立类型化的 TeamPlan、子 Agent 结果、Evaluator 裁决和最终 Artifact；
2. Supervisor 只在需要时选择检索、表格推理、计算和证据复核角色；
3. Harness 校验工具白名单和执行预算，但不因为多给候选就直接判整题失败；
4. 首先在同一批公开题上运行固定团队和动态团队，确认增量后再扩展公开 split。

## 产物位置

- `artifacts/phase5_step02/baseline_canary20/financebench_single_agent/`
- `artifacts/phase5_step02/baseline_canary20/finqa_direct/`
- `artifacts/phase5_step02/baseline_canary20/tatqa_direct/`
