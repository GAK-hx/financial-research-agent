# 相较 LangChain 默认能力的项目优化点

## 1. 依赖感知的受控工具执行

LangChain 默认 Agent/ToolNode 适合模型产生 Tool Call 后执行工具。项目进一步支持：

- `AnalysisPlan` 中显式 `depends_on`；
- 独立任务并行、依赖任务按拓扑顺序执行；
- Tool 白名单与参数二次校验；
- 调用预算预留、提交和回滚；
- 幂等键、重复调用抑制和失败分类；
- Tool 只能通过 ToolGateway 访问真实数据。

迁移后这些能力包装为 LangChain `StructuredTool` 和受控执行节点的增强，不删除。

## 2. 金融数据证据链

LangChain 的 `Document.metadata` 和 `ToolMessage.artifact` 能携带来源，但不会自动验证结论。
项目进一步提供：

- 当前 Run 内唯一 Evidence ID；
- Source Locator、观察时间、数据日期、报告机构、页码和 Chunk；
- Iceberg Snapshot 或数据版本信息；
- Tool Result 到 Evidence、Evidence 到 Claim 的映射；
- 引用是否属于当前 Run 的检查。

## 3. 节点级上下文构建与可追溯压缩

LangChain 提供消息摘要和上下文编辑；项目进一步提供：

- Interpret、Plan、Report、Revise 分节点内容白名单；
- 每个节点独立 Token 输入预算和输出预留；
- 批量行情行确定性折叠，原始数据保留在来源位置；
- Evidence 数字、单位、来源和归因字段保护；
- Context Manifest 记录本次模型实际看到的内容；
- 模型摘要失败时的确定性回退。

## 4. 分层、可治理记忆

在 LangGraph Checkpoint/Store 基础上，项目增加：

- Tenant、User、Session 复合隔离；
- Session 与 Preference Memory 分层；
- TTL、删除、版本冲突和来源记录；
- Preference 显式确认；
- API Key 和敏感信息拒绝写入；
- 历史记忆不能替代本次真实 Tool/Evidence。

## 5. 金融报告业务校验与修复

LangChain Structured Output 保证结构，项目进一步检查：

- Claim 引用的 Evidence ID 是否存在；
- Claim 数字是否出现在同一引用证据；
- 研报观点是否包含正确机构归因；
- 日期、股票代码和数据范围是否一致；
- 风险、限制和免责声明是否完整；
- 校验失败后有限次数修订并再次验证。

## 6. Skill、Policy 和 Completion

项目将 LangChain 的动态 Tool/Middleware 能力扩展为：

- 有版本和生命周期的 Skill Registry；
- 多 Skill 合并时采用权限交集和最小预算；
- Skill 不能扩大基础 Tool 权限；
- Evidence 数量和类型要求；
- CompletionChecker 统一判断是否满足交付条件。

## 7. 可恢复执行与业务审计

除 LangGraph Checkpoint 外，项目保留独立业务记录：

- Run、Node Attempt、Model Call、Tool Call、Budget Ledger；
- API/Worker 解耦与租约；
- 中断、恢复和终态幂等；
- 模型、Prompt、Policy、Skill 和 Context 版本可追踪。

## 简历和面试中的统一表述

> 项目基于 LangChain 与 LangGraph 构建，并针对金融分析场景扩展了受控工具执行、
> 节点级上下文工程、可验证证据链、分层记忆及报告事实校验。

不能将这些增强描述成 LangChain 的默认能力，也不再将整个系统描述成完全自研 Agent 框架。
