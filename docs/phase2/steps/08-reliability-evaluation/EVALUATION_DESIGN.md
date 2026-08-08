# Step 08评测设计

## 1. 目的

本步骤验证三件事：

1. Phase 2没有破坏Phase 1已经通过的20题能力；
2. Agent面对未用于开发调参的问题仍能选择正确Skill、Tool和Evidence；
3. Worker、模型、Tool、Policy、Budget、Memory和上下文压缩在异常条件下仍受控。

评测不以文风相似度作为核心指标。优先检查Intent、Tool参数、Skill、Evidence来源、
引用、数字一致性、完成度和预算闭合，这些指标可复算且与系统边界直接相关。

## 2. 数据集

| 数据集 | 数量 | 执行方式 |
|---|---:|---|
| Regression | 20 | 单次，和Phase 1基线比较 |
| Holdout | 30 | 封存后一次性运行，不用于Prompt调参 |
| Stability | 10×3 | 相同版本和数据Snapshot下重复三次 |

所有数据集固定`as_of_date=2026-07-15`。运行产物记录数据集SHA-256、模型、
Prompt、编排运行时和生成时间，避免修改题目后沿用旧结论。

Holdout仅使用当前真实数据底座已覆盖的`600519`和`300750`，变化来自未见问法、
时间范围、报告风格和风险关注组合，而不是用不存在的数据制造失败。

## 3. 单题评分

成功题检查：

- HTTP和结构化响应；
- Intent、股票、时间范围；
- Tool集合及Tool参数；
- Skill版本集合；
- 必需Evidence类型；
- 当前Run引用有效性；
- 报告数字可由引用Evidence复核；
- Completion Checker通过；
- Budget无未结算Reservation；
- 模型规划、Tool和报告均完成。

拒绝题检查HTTP状态和稳定错误码，不要求生成报告。

## 4. 稳定性

每题三次运行，比较：

- Skill集合；
- Tool集合；
- Evidence类型、标的、来源类型和稳定Locator；
- Evidence结构化数字；
- 报告必需字段及核心板块是否存在。

自然语言措辞、Claim/Risk/Limitations数量不要求完全一致。Evidence ID中的Run前缀、
延迟、Snapshot ID和Token估算等运行噪声不进入数字一致性比较。

## 5. 失败分类

| 类型 | 定义 | 处理 |
|---|---|---|
| SYSTEM_DEFECT | 代码、状态、Policy、Budget或恢复错误 | 修复后重跑受影响集合 |
| MODEL_VARIANCE | 合法输出但Skill、Tool或报告结构不稳定 | 检查Prompt/Schema；不改Holdout |
| DATA_GAP | 当前Iceberg或Milvus没有所需正式数据 | 记录数据范围，不伪造 |
| PROVIDER_NETWORK | 超时、限流或连接失败且重试后仍失败 | 保存原始响应，可补跑同一封存题 |
| LABEL_DEFECT | 预期标注和实际规则不一致 | 单独审查并版本化数据集 |

`FAILED_CASES.md`保存每个失败题的完整结构化响应，网络失败也不得只保留异常摘要。

## 6. A/B边界

- Skill开/关比较选择准确率和约束是否存在；
- Memory开/关比较同Session指代消解，不允许Memory替代取数；
- Compression开/关使用同一Evidence，比较Token估算和Evidence保护；
- A/B用于说明组件贡献，不用A/B结果修改已封存Holdout。
