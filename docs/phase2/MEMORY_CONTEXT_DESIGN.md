# 第二阶段Memory与Context Compression设计

## 1. 为什么分开Memory和Context

Memory解决“什么内容可被持久保存和再次使用”；Context解决“某个节点此刻给模型看什么”。两者不与Evidence合并，也不能替代实时取数。

## 2. 分层模型

| 层 | 内容 | 存储 | 生命周期 | 能否作为事实 |
|---|---|---|---|---|
| Run State | 节点、计划、引用ID、错误、预算快照 | LangGraph Checkpoint | Run/审计保留期 | 仅结构化字段 |
| Working Context | 当前节点组装的模型输入 | 内存+可追溯摘要 | 节点/Run | 否 |
| Evidence Memory | ToolResult转换的结构化事实 | 业务Store/Artifact | Run保留期 | 是，但必须带来源 |
| Session Memory | 本会话已确认的实体、时间和未完成上下文 | PostgreSQL | 默认30天 | 否，仅辅助解释 |
| Preference Memory | 用户显式确认的输出偏好 | PostgreSQL | 直到删除/过期 | 否 |
| Skill Memory | 版本化的研究流程与压缩策略 | Skill Registry | 版本生命周期 | 程序性知识 |

## 3. 允许和禁止记忆的内容

### 可以记忆

- 用户已确认的标的代码、报告语言、输出长度和风险偏好；
- 同一Session内的追问指代和已确认时间区间；
- 未完成Run的恢复信息；
- Skill版本、Context Policy和Prompt版本。

### 不能当作长期事实

- “该公司增长强”类历史研究结论；
- 不带Snapshot和Source Locator的历史数字；
- 模型推测、隐藏推理或未验证摘要；
- 跨用户或跨租户共享的个人偏好；
- API Key、凭证和原始敏感请求头。

## 4. Memory写入流程

```text
Candidate Memory
  ↓ 分类（Session / Preference / Reject）
  ↓ Schema、租户、敏感信息和TTL校验
  ↓ Preference必要时要求用户显式确认
Memory Record + Source + Version + Expiry
```

- 模型可以提议Candidate Memory，不能直接写表；
- 所有写入经Memory Manager并记录原始来源；
- Preference默认不从单次行为隐式推断；
- 更新使用版本号与乐观锁，删除保留审计事件；
- 用户可查询和删除Session/Preference Memory。

## 5. Context Builder

每个模型节点只接收必要子集：

| 节点 | 必需Context | 不应加载 |
|---|---|---|
| Interpret | 用户问题、Session指代、实体规则 | 完整Tool Trace、历史报告 |
| Select Skill | QuerySpec、候选Skill摘要、Policy | 全部Skill Prompt，原始数据 |
| Plan | QuerySpec、选中Skill、Tool Schema摘要、Budget | 无关会话和报告全文 |
| Report | 经验证Evidence、缺口、Report Skill | 原始长Trace、未校验Tool输出 |
| Revise | 原报告、Validator错误、对应Evidence | 重新加载所有非相关Evidence |

Context Builder输出`ContextManifest`：节点、Skill/Policy版本、包含的条目、被裁剪的条目、Token估算、摘要引用和构建时间。

## 6. Compression Pipeline

```text
确定性删重
  → 按优先级裁剪
  → 结构化聚合
  → 必要时模型摘要
  → 数字/引用/来源验证
  → Token预算复检
```

优先使用确定性压缩，仅在长文本无法通过裁剪满足预算时调用模型摘要。摘要是派生视图，不覆盖原文或Evidence。

## 7. Evidence保护红线

压缩不能删除或改写：

- Evidence ID与Claim-Evidence关系；
- 数值、单位、币种、期间和公式版本；
- Source Locator、数据Snapshot、页码、发布机构和报告期；
- Tool版本、调用时间和数据质量警告；
- Validator Error及对应修订状态。

报告节点只能引用结构化Evidence或其带引用的派生视图；摘要中的新数字不能自动晋升为Evidence。

## 8. 上下文预算

每个Skill引用`ContextPolicy`，定义：

- 节点最大Token和预留输出Token；
- Evidence、Session、Tool Schema、历史消息的优先级；
- 每类条目数量上限和时间范围；
- 允许的摘要器、Prompt版本和最大摘要层数；
- 超限时是降级、拒绝还是要求澄清。

第一版最多一层模型摘要，禁止摘要再摘要导致无法追溯。

## 9. 评测

- 压缩前后结构化数字和引用一致率100%；
- Evidence来源保留率100%；
- 不同用户/Session内存隔离通过；
- TTL、删除、版本冲突和敏感信息拦截通过；
- Context Token降低幅度、质量变化和额外费用可量化；
- 同题压缩开/关A/B下，Validator通过率不显著退化；
- Memory不会使过期数据跳过正式Tool调用。

## 10. 用户权利与运维

- 提供Session/Preference Memory查询与删除API；
- 记录写入原因、来源、版本和过期时间；
- 定时执行TTL清理并记录数量；
- 敏感信息脱敏后才进日志；
- 备份和恢复不能绕过租户隔离与删除策略。
