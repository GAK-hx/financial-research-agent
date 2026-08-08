# Skill 与受控循环

## 1. 基础框架和自定义增强

项目以 LangChain 1.3.14 提供模型与 `StructuredTool` 接口，以 LangGraph 1.2.9 保存并推进运行状态。
自定义部分集中在企业场景通常必须补齐的控制层：Tool Gateway、权限、预算、Evidence、上下文、
检查点、终止规则和审计，而不是重新实现模型 SDK 或图执行框架。

所有模型可见 Tool 都通过 LangChain `StructuredTool` 暴露 Pydantic 参数 Schema，但实际调用仍必须进入
同一个 Tool Gateway，经过 Tool 白名单、参数校验、股票/日期范围、只读策略、逻辑调用预算、尝试预算、
超时、重试、幂等和脱敏记录。

## 2. 六个 Skill 包

每个包含 `manifest.yaml`、`workflow.yaml`、Prompt 指令、数据边界、Evidence 检查和样例：

1. `single_stock_technical@1.0.0`；
2. `single_stock_fundamental@1.0.0`；
3. `cross_section_screening@1.0.0`；
4. `factor_research@1.0.0`；
5. `event_impact@1.0.0`；
6. `comprehensive_stock_analysis@1.0.0`。

旧的 `concise` 和 `risk` 不再作为分析 Skill 参与 Tool 权限交集，而是报告 Profile；因此“简洁且风险
优先”可以组合，不会错误地改变 Agent 的数据访问能力。

## 3. LangGraph 节点

```text
理解问题 → 语义对齐 → 选择 Skill → 生成并校验计划
→ 执行 Tool → 构建 Evidence → 检查证据充分性
→（可选，一次）受控补充 → 再次执行 Tool/构建 Evidence
→ 生成报告 → 确定性校验 →（可选，一次）模型修订 → 完成
```

## 4. 受控补充的边界

补充只能由结构化 `MissingEvidence` 触发：

- 总次数最多 1；
- 只能使用当前 Skill 已授权的 Tool；
- 不能新增股票、扩大日期、改变意图或改变查询实体；
- Action Hash 与已执行动作重复时拒绝；
- 补充后 Evidence 没有增加时以 `REPLAN_NO_NEW_EVIDENCE` 终止；
- 预算不足或参数 Schema 不通过时直接失败，不让 LLM 自由试错。

当前安全补充只有两类：事件检索可移除过窄关键词但保留股票和日期；研报检索可在同一范围内提高
`top_k`。因子、技术、基本面和比较分析不会让模型动态扩大数据范围。

## 5. 报告校验

- `data_as_of` 由 Harness 从 Evidence 确定性绑定，不允许模型猜测；
- 所有摘要、结论、风险、风险向量和情景引用必须指向当前 Run 的 Evidence；
- 数字必须在被引用 Evidence 中找到，并处理百分比、亿元、方向词和合理显示舍入；
- 高级分析必须有技术、基本面、事件、数据置信度四维风险向量；
- 必须有乐观、基准、压力三种情景及 Evidence；
- 报告最多修订一次，仍不合格就停止，不能无限自我修正。

## 6. 真实运行证明

Flash Gate `b454673bbac540c99ec14d1639d417cc`：

- 选择 `event_impact@1.0.0`；
- 首次关键词事件检索为空；
- Evidence Gate 只触发一次放宽关键词的补充；
- 第二次 `event_search` 获得 1 条 ACTIVE Event Evidence；
- 生成四维风险向量和三情景报告；
- 报告第一次校验通过，无模型修订；
- `completion.passed=true`，开放预算预留为 0。
