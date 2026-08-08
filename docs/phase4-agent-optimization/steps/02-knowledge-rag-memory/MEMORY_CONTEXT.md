# 记忆分层与上下文构建

## 1. 五类信息的责任边界

| 类型 | 当前实现 | 能否作为当前事实 |
|---|---|---|
| 工作记忆 | LangGraph Checkpoint | 仅当前 Run 状态 |
| 会话记忆 | PostgreSQL Session Memory | 只能解析同会话指代 |
| 偏好记忆 | 用户明确确认后写入 | 只影响表达，不改变事实 |
| 情节记忆 | 已通过 Validator 和 Completion 的终态反思 | 否，只是历史经验 |
| 程序记忆 | Git + Skill Registry 的已发布版本 | 作为受控流程说明 |
| 语义事实 | Event Knowledge / 研报 / 行情财务 | 必须带来源和时点 |

没有新增“记忆 Agent”。程序记忆继续使用现有 Skill Registry，避免同一 Skill 同时存在文件、
注册表和通用 Memory 三份真相。

## 2. Memory 操作

Memory Manager 现在明确提供：

- `write`：校验类型、来源、敏感内容、TTL 后写入；
- `read`：按 `tenant_id + user_id + session_id` 隔离读取；
- `update`：必须携带期望版本，防止并发覆盖；
- `reflect`：只接受已验证的终态 Run；
- `forget`：软删除并审计；
- `versions`：查看不可变版本历史；
- `expire_due`：清理 TTL 到期记录。

同一 Run 的相同反思是幂等的，不会因恢复或重试产生新版本。情节记忆标记
`historical_only=true`，不能替代新的行情、财务或事件查询。

## 3. Context Builder

Context 按稳定顺序构造：

1. 原始问题和结构化 Query；
2. 已发布 Skill、Tool Schema 和预算；
3. 当前 Evidence 与 ACTIVE Knowledge；
4. 用户偏好、会话指代和已验证情节；
5. 输出结构和校验错误。

每个 Context Item 在 Manifest 中记录：

- Item ID、类型和优先级；
- 内容哈希和估算 Token；
- 来源 Locator 和版本；
- 被选择或裁剪的原因。

## 4. 压缩与输出预算

每个节点先预留输出 Token，再计算输入上限。超限时依次：

1. 去掉完全重复的可选项；
2. 按类型上限和优先级裁剪会话、情节、偏好和知识；
3. 对 Evidence 大型行集做确定性引用替换；
4. 仅在显式开启时调用 Flash 做一层 Memory 摘要；
5. 仍超限则拒绝调用模型。

Evidence 的数字、日期、Statement、来源 Locator 和归属字段参与保护哈希，摘要不能覆盖原始
Evidence。客户端只维护 Context Manifest，不实现 KV Cache；稳定前缀顺序用于利用服务商可能
提供的 Prompt/Prefix Cache。
