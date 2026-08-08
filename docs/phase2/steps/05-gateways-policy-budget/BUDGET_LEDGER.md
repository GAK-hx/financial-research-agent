# Step 05 Budget Ledger

## 1. 预算不是普通计数器

并行Tool如果采用“先读取计数、再加一”，两个Worker可能同时看到剩余额度并共同
超限。因此预算放在PostgreSQL事务中，锁定Run Budget行后执行：

```text
Reserve → 执行外部动作 → Commit
                     └→ 失败 → Release
```

`reservation_key`唯一，重复请求必须保持Run、资源和数量一致。

## 2. 资源类型

| 资源 | 含义 |
|---|---|
| `model_calls` | 完成或可复用的逻辑模型调用 |
| `model_attempts` | 实际发出的HTTP尝试，包括失败重试 |
| `tool_calls` | 成功完成的逻辑Tool调用 |
| `tool_attempts` | 实际Tool执行尝试 |
| `evidence` | 进入当前Run的Evidence数量 |
| `report_revisions` | 成功生成的报告修订 |
| `replan` | 当前固定为0 |
| `tokens` | Provider返回或估算的总Token |
| `cost_microunits` | 按配置价格计算的人民币微元 |

失败逻辑调用Release，因此不挤占后续可成功的业务调用；已经发生的外部尝试不可撤销，
所以Attempt始终Commit。

## 3. 预算来源

Run开始时生成不可变Budget Snapshot：

```text
有效上限 = min(系统配置, 当前Skill Workflow Constraints)
```

Token和费用默认不凭空设置硬上限；未配置时仍记录Usage和费用。模型调用次数、
Tool次数、并行数、Evidence、修订和重试已有硬上限。

当前系统候选默认仍以现有稳定配置为准：

| 项目 | 系统上限 | Skill可进一步收紧 |
|---|---:|---|
| 模型逻辑调用 | 3 | 是 |
| Tool逻辑调用 | 8 | 是 |
| 并行Tool | 4 | 是 |
| Evidence | 40 | 是 |
| 报告修订 | 1 | 是 |
| Replan | 0 | 固定 |
| Model Attempt | 9 | 按调用数和重试共同收紧 |
| Tool Attempt | 24 | 按调用数和重试共同收紧 |

原计划中的5次模型/12次Tool是候选容量，不直接覆盖已实测的3/8配置。后续真实
复杂问题证明不足时，再通过压测和失败样本调整。

## 4. Token与费用

优先使用DeepSeek官方Usage：

- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `prompt_cache_hit_tokens`
- `prompt_cache_miss_tokens`

费用分别按缓存命中输入、缓存未命中输入和输出价格计算。Provider缺失Usage时采用
保守字符估算并标记`estimated=true`，不能与官方Usage混为一谈。

Token和费用的精确值只有请求返回后才能获得；当前实现将它们作为调用后的不可逆
Usage核算。若以后启用严格的Run Token/费用硬上限，需要在请求前按Prompt和
`max_tokens`预留上界，并根据实际Usage核销，不能只做事后拒绝。

## 5. Completion Check

正式终态前检查：

- 成功研究必须有Evidence；
- 成功研究必须完成报告；
- 成功报告必须通过Validator；
- 不能同时出现失败编排和成功报告；
- 所有Budget Reservation必须已结算。

受控失败也可以通过一致性检查；`completion.passed=true`表示终态内部一致，不表示
研究请求成功。
