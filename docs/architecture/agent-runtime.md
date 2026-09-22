# Agent运行时

## LangChain与LangGraph

LangChain统一ChatModel、Structured Output、StructuredTool、Message和Retriever接口。LangGraph负责状态图、
条件路由、并行fan-out、Checkpoint和恢复。领域模型与Tool Schema不依赖具体图节点，便于替换模型或编排实现。

一次任务的主要状态流为：

```text
QuerySpec
  → TeamPlan
  → ToolCalls
  → Evidence
  → SubAgentEvaluation
  → RiskAssessmentArtifact
  → ValidationResult
```

## Harness

Harness是模型之外的受控执行层，负责：

- Tool白名单和Pydantic参数校验；
- 模型、Tool、Evidence和修订预算；
- 超时、有限网络重试、取消与租约；
- 幂等调用、并发上限和终态唯一写入；
- Trace、事件、失败分类和完成条件。

网络错误可以按退避策略重试；已经得到的无效结构化响应不会原样盲重试，而是保存失败信息并交给上层决定
是否执行一次定向修复。

## Tool、Skill与Evidence

Tool是受控数据操作，包含结构化输入、结构化结果、数据域、超时和审计信息。Skill声明适用意图、允许Tool、
预算和工作流，不能绕过Tool Gateway。

Evidence统一保存主体、声明、来源、数据日期、快照和定位信息。Evaluator检查证据支持、反向证据、数值、
单位、时间口径和冲突。最终报告中的重要结论必须引用当前运行Evidence。

## 团队选择

- 简单问答和FinanceBench类型默认单Agent；
- FinQA复杂程序题默认固定团队；
- TAT-QA复杂算术和table-text任务可启用动态团队；
- Supervisor的模型调用也计入成本，因此只有质量或成本证据支持时才启用动态编排。

## 上下文与记忆

Context Builder按节点预算选择问题、计划、Tool结果、记忆和Evidence，并记录保留、压缩和删除项。原始Evidence
不可被摘要覆盖。会话与偏好记忆按tenant/user/session隔离；公共分析缓存不包含用户身份。

上下文压缩减少输入Token，但不直接管理第三方模型服务端KV Cache。
