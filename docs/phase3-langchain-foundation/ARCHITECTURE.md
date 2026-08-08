# LangChain 基础框架正式架构

## 1. 分层结构

```text
API / Worker / SSE
        |
LangGraph Stateful Runtime
StateGraph / Checkpoint / Runtime / Store / Interrupt / Stream
        |
LangChain Agent Foundation
ChatModel / Runnable / Prompt / Structured Output
StructuredTool / Message / Retriever / Document / Middleware / Callback
        |
Financial Agent Enhancement Layer
ModelGateway / ToolGateway / PolicyEngine / Budget
SkillRegistry / ContextBuilder / EvidenceBuilder
MemoryManager / ReportValidator / CompletionChecker
        |
Financial Data Capabilities
Market / Financial / Indicator / Report Search
PostgreSQL / Milvus / Iceberg
```

## 2. 设计原则

1. LangChain 标准接口成为模型、工具、检索和消息的外部入口；
2. LangGraph 是唯一正式 Agent 运行时，不再维护第二套正式编排路径；
3. Tool 和 Model 的正式调用仍必须经过 Gateway；
4. LangChain Adapter 只负责格式转换，不复制业务规则；
5. Evidence、Policy、Budget、Memory、Validator 保持框架无关的领域核心；
6. API 输出和已有数据库记录保持向后兼容；
7. LangSmith 为可选集成，不成为本地运行和生产部署的强依赖；
8. 保留显式回退开关用于兼容诊断，但只有LangChain/LangGraph路径是默认生产入口。

## 3. 关键调用链

### 规划

```text
LangGraph planning node
  -> Context Middleware / ContextBuilder
  -> ChatPromptTemplate
  -> ModelGateway
  -> LangChain ChatModel/Runnable
  -> structured output: AnalysisPlan
  -> PlanValidator
```

### 工具执行

```text
AnalysisPlan
  -> dependency-aware scheduler
  -> LangChain StructuredTool
  -> ToolGateway
  -> Policy / Budget / Idempotency
  -> FinancialTool implementation
  -> ToolMessage(content + artifact)
  -> EvidenceBuilder
```

### 报告

```text
Document / ToolMessage artifact / Evidence
  -> ContextBuilder
  -> LangChain structured output: ResearchReport
  -> ReportValidator
  -> pass / revise / fail
```

## 4. 不采用的方案

- 不使用一个无约束的 `create_agent()` 循环替代完整研究工作流；
- 不允许 `ToolNode` 或 `StructuredTool` 绕过 ToolGateway；
- 不把 Evidence、Budget、Policy 全部退化为 Message 文本；
- 不用 LangChain 内置摘要直接替换 Evidence 保护和 Context Manifest；
- 不为了展示框架而重写数据管理、Iceberg、Milvus 和 PostgreSQL 业务表。

## 5. 实际接入边界

| 标准接口 | 项目实现 | 保留的领域能力 |
|---|---|---|
| `BaseRetriever` / `Document` | `LangChainReportRetriever` | Milvus过滤、Chunk定位、机构/标题/页码溯源 |
| `StructuredTool` / `ToolMessage` | `build_governed_structured_tool` | ToolGateway、白名单、预算、幂等、完整ToolResult |
| `RunnableLambda` | `context_builder_runnable` | 节点Token预算、确定性压缩、Evidence保护、Context Manifest |
| LangGraph `BaseStore` | `FinancialMemoryStore` | Tenant/User/Session隔离、TTL、版本、删除、敏感信息检查 |
| Runtime Context | `ResearchRuntimeContext` | Tenant/User/Session/Run身份一致性校验 |
| Agent Context | `skill_agent_context` | Skill版本、可见工具、Evidence要求、工作流预算 |

适配层只做标准对象与领域对象之间的转换。真实数据仍只能由受控Tool读取，
模型不能直接访问Milvus、Iceberg或PostgreSQL；LangGraph Store写入也继续委托
`MemoryManager`执行现有治理规则。

## 6. Step 03正式切换结果

- `Settings`默认值为`AGENT_FRAMEWORK=langchain`与
  `ORCHESTRATION_RUNTIME=langgraph`；
- Docker Compose的`app`、`job-api`和`job-worker`均使用默认正式路径；
- 原重复`langgraph-app`服务已删除，主API保持8000端口；
- LangChain结构化解析失败会计为失败Attempt并按模型重试策略重试；
- DeepSeek JSON模式的Prompt显式携带Pydantic输出Schema和结构示例；
- `native/legacy`仅能通过显式环境变量启用，不作为默认服务。
