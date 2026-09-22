# 第五阶段：企业财务风险 Benchmark 与自适应多 Agent

> 状态：`STEP_03_COMPLETE_WITH_LIMITATIONS`。Step 01数据与公开Benchmark、Step 02 Agent编排和正式消融、
> Step 03历史回放、多用户复用、Spark/Iceberg性能及本地K8s恢复演练均已完成；生产化限制见最终Gate。

本阶段把项目从泛化股票分析收敛为“企业财务风险监测与证据复核”。系统以公司—报告期为分析单元，
先由确定性计算生成风险候选，再由 Supervisor 按需组织偿债、盈利质量、资产质量和披露取证子 Agent，
最后通过确定性校验和独立Evaluator生成结果。Agent效果只在公开Benchmark上评价，自有公司数据只用于业务演示与系统性能测试。

## 文档入口

- [总计划](MASTER_PLAN.md)
- [指标与验收门槛](METRICS_AND_GATES.md)
- [数据、标签与评测设计](DATA_AND_EVALUATION_DESIGN.md)
- [总清单](CHECKLIST.md)
- [总进度](PROGRESS.md)
- [Step 01：风险数据与 Benchmark 基线](steps/01-risk-data-benchmark/PLAN.md)
- [Step 02：自适应多 Agent 与证据复核](steps/02-adaptive-multi-agent/PLAN.md)
- [Step 03：历史回放、并发性能与岗位交付](steps/03-replay-performance-delivery/PLAN.md)
- [Step 03最终Gate](steps/03-replay-performance-delivery/FINAL_GATE.md)
- [Kubernetes运行报告](steps/03-replay-performance-delivery/K8S_RUNTIME_REPORT.md)

## 固定边界

- 默认使用 DeepSeek V4.1 Flash（API 模型名 `deepseek-flash`），不隐式切换 Pro；退役的 V4 Flash 别名 `deepseek-v4-flash` 只作兼容性说明，不能作为独立模型基线；
- 不生成买卖指令，不执行交易，不以短期股价涨跌作为主要正确性标签；
- 模型只能通过白名单 Tool 读取数据；
- 所有风险结论必须绑定分析截止日、数据快照和 Evidence；
- P0 安全、隔离和未来数据泄漏问题必须 100% 通过；
- GitHub 保持私有，除非用户后续明确授权改变可见性。

## 简历基准

后续只以校招版
`../简历模板/简历_data_engineering_financial_risk_agent_mart_实习.tex` 为内容基准。该文件中的
风险效果指标仍是项目完成后的目标表述；在真实 Gate 产物生成前，不因实现进度自动上调数字。
