# 04 Gateway、Policy、Budget、Memory与Context

## 1. 为什么需要Gateway

如果每个Graph节点直接调用模型或工具，重试、权限、预算、日志和错误处理会分散在
各处，难以证明没有绕过路径。当前正式路径把所有模型和Tool调用收口到两个Gateway。

## 2. Model Gateway

Model Gateway 提供统一的：

- Provider Adapter 与能力声明；
- 结构化 Request/Response；
- 超时和仅针对瞬时错误的有界重试；
- Usage、Token 和费用记录；
- Prompt、模型和 Adapter 版本；
- 日志脱敏；
- 幂等键和调用审计；
- Provider 错误标准化。

当前 Step 03 已增加 45 秒单次超时、2 次网络重试和 2/4 秒退避；Step 05 将其正式纳入 Gateway、预算和 Provider Capability。

不会重试：

- Pydantic/JSON 校验错误；
- Validator 拒绝；
- 参数越权；
- 普通 4xx；
- Budget 或 Policy 拒绝。

## 3. Tool Gateway

Tool Gateway 调用前依次执行：

```text
Registry存在
  → Skill允许
  → Policy允许
  → Pydantic参数通过
  → 只读/域/日期/行数检查
  → Budget Reserve
  → 幂等占用
  → Tool执行
  → Result Schema检查
  → Budget Commit或Release
  → 审计
```

Graph 节点只接收 `ToolResult`，不能拿到 Repository、数据库客户端或任意 HTTP Client。

## 4. Policy Engine

Policy 的输入包括：

- 用户、租户、Session；
- Intent 和股票范围；
- Skill 与版本；
- Tool、数据域和参数；
- 当前 Run 状态；
- 数据来源 formal/simulation 标记；
- 当前预算和调用历史。

输出是结构化的 `allow/deny`、规则版本和原因码。Deny 不交给模型“说服”或自行修改。

典型规则：

- 研究工具全部只读；
- 禁止任意 SQL、Shell、Python；
- 日期和行数有硬上限；
- Simulation 数据不能成为正式 Evidence；
- Skill 不得扩大租户权限；
- 跨租户 Run、Memory 和 Artifact 不可见。

## 5. Budget Ledger

预算不是 Prompt 文字，而是数据库事务。

```text
Reserve
  ├── 成功调用 → Commit实际用量
  └── 失败/未执行 → Release
```

候选默认值：

| 项目 | 候选上限 |
|---|---:|
| Run总时间 | 180–240秒，最终按实测冻结 |
| 模型调用 | 5 |
| Tool调用 | 12 |
| 并行Tool | 4 |
| Evidence | 60 |
| 报告修订 | 1 |
| Replan | 0 |

Token 和费用上限必须读取 DeepSeek 真实 Usage 后再冻结。并发 Worker 使用原子 Reserve，不能通过竞态突破上限；重试也计入预算。

## 6. Memory分类

| 类型 | 内容 | 权威性 |
|---|---|---|
| Run Memory | 当前Graph State与Checkpoint | 当前Run状态 |
| Working Memory | 当前节点临时Context | 临时视图 |
| Evidence Memory | 当前Run事实与来源 | 报告事实入口 |
| Session Memory | 已确认的会话上下文 | 有TTL |
| Preference Memory | 用户明确确认的稳定偏好 | 可删除、可版本化 |
| Skill Memory | 版本化流程知识 | 人工发布 |

历史研究结论不作为长期事实直接复用。新问题涉及行情、财务或研报时，仍必须重新调用当前 Tool 并生成当前 Run Evidence。

## 7. Memory写入与隔离

Memory 使用 `tenant_id + user_id + session_id` 复合隔离键，并包含：

- 来源消息和确认方式；
- 类型与敏感等级；
- 创建时间、TTL 和版本；
- 删除状态与审计；
- 写入它的规则/模型版本。

候选 Memory 先分类，再执行敏感检查。Preference 只有用户明确确认后才持久化。API Key、凭证、Authorization Header 和隐藏推理永不进入 Memory。

## 8. Context Builder

不同节点看到不同内容：

| 节点 | 允许内容 |
|---|---|
| Interpret | 当前问题、必要Session上下文 |
| Select Skill | QuerySpec、Skill元数据 |
| Plan | QuerySpec、Tool Schema、Skill约束 |
| Report | QuerySpec、当前Run Evidence、报告格式 |
| Revise | 原报告、Validator错误、相关Evidence |

Planner 不需要看到完整研报，Report 节点不需要看到数据库连接或无关历史 Trace。

## 9. Context Compression

压缩顺序：

1. 去重；
2. 删除无关字段；
3. 按优先级裁剪；
4. 对结构化数据做确定性聚合；
5. 仍超限时才允许一次模型摘要；
6. Evidence 保护校验；
7. 生成 `ContextManifest`。

允许压缩：

- 重复对话；
- 已完成节点的冗长描述；
- 非关键检索文本；
- 重复 Trace。

禁止丢失或改写：

- Evidence ID；
- 数字、单位和日期；
- Source Locator、Snapshot、页码和机构；
- 公式版本；
- Validator错误；
- Policy和Budget结果。

摘要失败时回退到确定性裁剪，并显式记录 Warning，不允许递归摘要。

## 10. Completion Checker

Completion Checker 是最后一道程序化门槛。即使模型已经生成一份“看起来完整”的报告，只要出现以下任一情况都不能成功：

- 缺少 Skill 要求的 Evidence；
- Claim 引用不存在；
- 数字不受引用 Evidence 支持；
- Policy 或 Budget 未通过；
- 有未核销 Reserve；
- Artifact 未写入；
- Run 状态冲突。

这保证“模型说完成”与“系统确认完成”是两件不同的事。
