# 第二阶段：LangGraph Agent Harness架构

## 1. 定位

第一阶段解决了单次研究请求的受约束编排；第二阶段使用LangGraph把编排过程状态化，并在图运行时外增加金融领域的Skill、Tool、Evidence、Policy、Budget、Memory和Completion治理。

```text
Client
  ↓
FastAPI Job API / SSE
  ↓
Harness Control Plane
├── Policy Engine
├── Budget Manager
├── Skill Registry
├── Memory Manager
├── Completion Checker
└── Run/Event Metadata
  ↓
LangGraph Runtime
├── StateGraph
├── AsyncPostgresSaver
├── Interrupt / Resume
├── Streaming
└── Durable Execution
  ↓
Graph Nodes
├── Interpret
├── Select Skill
├── Build Context
├── Plan / Validate Plan
├── Tool Gateway
├── Build Evidence
├── Report / Validate Report
└── Complete
  ↓
PostgreSQL + Iceberg + Milvus + Artifact Volume
```

## 2. 框架分工

### LangGraph负责通用运行时

- 图状态和节点迁移；
- Checkpoint与Pending Writes；
- 中断、继续和失败恢复；
- 图级Streaming；
- 并行节点和任务结果复用；
- Thread/Checkpoint历史。

### 金融Harness负责领域治理

- QuerySpec、AnalysisPlan、ToolResult、Evidence、ResearchReport等Pydantic模型；
- Skill Registry与Skill生命周期；
- Model/Tool Gateway；
- Policy、Budget和权限；
- Evidence来源与报告Validator；
- Session/Preference Memory规则；
- Context选择与压缩；
- Completion Checker；
- 业务Run、费用、事件和审计信息。

LangGraph不能替代幂等、权限、费用、Evidence和金融校验。任何模型/API调用都封装为可Checkpoint的Task，并使用业务幂等键。

## 3. 为什么不直接使用LangChain高层Agent

当前项目已有确定的Intent、工具轨迹、Evidence Schema和报告校验。第二阶段使用LangGraph低层运行时，不采用通用ReAct Agent接管规划：

- 保留Structured Planner与规则降级；
- 保留现有只读Tool Registry；
- 只按需要使用`langchain-core`基础类型；
- 模型Adapter继续可替换，不绑定单一Provider SDK。

## 4. Hermes与Pi的使用边界

### Hermes

参考其Skills、Memory、Context Compression和Gateway思想，但不引入完整Hermes运行时。金融Skill必须声明允许工具、Evidence要求、Policy、Budget和Validator，且不能自动激活。

### Pi

参考其Agent Session、事件流和Context Compaction设计。由于Pi主体是TypeScript Coding Agent生态，不作为本Python金融项目依赖。

## 5. Graph State

Graph State只保存可序列化、可恢复的数据，不保存数据库连接、DataFrame或模型客户端：

```text
run_id / user_id / session_id / thread_id
request / query_spec
selected_skill_ids / skill_versions
plan / node_status / attempt
evidence_ids / evidence_summaries
report / validation
budget_snapshot / policy_version
errors / warnings
completion_status
```

完整Evidence结构保存在业务Store或Checkpoint的受保护字段；大表、PDF全文和原始模型客户端不进入Graph State。

## 6. Graph节点

```text
START
  ↓
interpret
  ↓
select_skill
  ↓
build_planner_context
  ↓
plan → validate_plan
  ↓
execute_tools（Send/并行）
  ↓
build_evidence
  ↓
build_report_context
  ↓
generate_report → validate_report
                     ├── pass → completion_check
                     └── fail且预算允许 → revise_report → validate_report
  ↓
END
```

模型不能直接选择下一任意节点。条件边由程序根据Schema、Policy、Budget和Validation决定。

## 7. Skill层

Skill是版本化研究流程，不是可任意执行的代码：

```text
SkillDefinition
├── id / version / status
├── triggers
├── allowed_tools
├── required_evidence
├── workflow_constraints
├── context_policy
├── report_sections
├── validator_profile
└── budget_profile
```

第一版Skill：

- `market_trend_analysis`
- `financial_growth_analysis`
- `profitability_analysis`
- `research_report_review`
- `comprehensive_stock_research`
- `concise_research_report`
- `risk_focused_report`

生命周期：`DRAFT → REVIEWED → ACTIVE → DEPRECATED`。模型只能提出Skill草稿，不能自动启用或扩大工具权限。

## 8. Tool规范化

现有Tool接口继续作为领域核心，统一通过Tool Gateway：

- Pydantic Input/Output；
- ToolDefinition包含版本、域、只读、超时、行数和幂等策略；
- Skill只能使用`allowed_tools`；
- Policy再次检查formal/simulation域和参数；
- 调用前Budget Reserve，调用后Commit/Release；
- LangGraph Task只返回ToolResult；
- 成功ToolResult经Evidence Builder生成Evidence。

Skill不能直接访问Iceberg、Milvus或HTTP数据源。

## 9. 持久化

同一PostgreSQL实例分两类存储：

### LangGraph Checkpointer

- `AsyncPostgresSaver`管理图Checkpoint、Writes和Thread历史；
- Checkpoint Serializer只接受安全可序列化对象；
- 生产配置启用状态加密；
- Thread ID映射业务Run ID，但不代替业务审计表。

### 业务Harness Store

- Run元数据与终态；
- Skill版本和激活记录；
- Policy/Budget Ledger；
- Model/Tool调用审计；
- Session/Preference Memory；
- 用户操作、Cancel/Resume和最终Artifact引用。

使用SQLAlchemy Async、asyncpg和Alembic维护业务表。LangGraph Checkpointer表不由业务Alembic修改。

## 10. Memory与Context Compression

### Memory分类

- Run Memory：LangGraph State和Checkpoint；
- Working Memory：当前节点动态Context；
- Evidence Memory：当前Run事实唯一入口；
- Session Memory：跨请求已确认上下文；
- Preference Memory：用户明确确认的稳定偏好；
- Skill Memory：版本化Procedural Memory。

### Context Manager

按节点和Skill Context Policy选择信息，执行去重、裁剪、摘要和Token预算检查。

允许压缩：历史消息、重复Trace、已完成节点描述、非关键检索文本。

禁止丢失：Evidence ID、结构化数字、Source Locator、Snapshot、页码、机构、公式版本和Validator错误。

摘要必须记录输入范围、生成模型、Prompt版本、时间和原始引用。Session默认30天TTL；Preference显式确认；不保存研究结论作为长期事实。

## 11. Policy与Budget

建议默认Profile：

| 项目 | 默认值 |
|---|---:|
| Run总时长 | 180秒 |
| 模型调用 | 5次 |
| 工具调用 | 12次 |
| 并行工具 | 4 |
| Evidence | 60条 |
| 报告修订 | 1次 |
| Replan | 0 |

Token和费用上限根据DeepSeek真实Usage预检后冻结。Budget使用Reserve/Commit/Release账本；模型无权修改预算。

## 12. 服务与Docker部署

| 服务 | 职责 | 建议内存 |
|---|---|---:|
| `api` | Job API、查询、SSE、Cancel/Resume | 512MiB |
| `worker` | LangGraph执行、BGE检索、Gateway | 1200MiB |
| `postgres` | Checkpoint与业务Harness数据 | 512MiB |
| `milvus` | 研报向量索引 | 1800MiB |
| `etcd` | Milvus元数据 | 256MiB |

第一阶段`app`拆为`api`与`worker`，保留Iceberg、Milvus、模型缓存和Artifact Volume。第一版不增加Redis、Celery、MinIO、Kafka或Kubernetes。

## 13. API

```text
POST   /runs
GET    /runs/{run_id}
GET    /runs/{run_id}/events
POST   /runs/{run_id}/cancel
POST   /runs/{run_id}/resume
GET    /runs/{run_id}/trace
GET    /skills
GET    /skills/{skill_id}
GET    /sessions/{session_id}/memory
DELETE /sessions/{session_id}/memory
POST   /analyze 兼容接口
```

SSE只发布阶段、节点、工具和最终状态，不暴露模型隐藏推理或未校验草稿。

## 14. 明确不做

- 自动交易和外部写操作；
- 多Agent角色聊天；
- Skill自动激活和自我修改权限；
- 模型任意SQL/Shell/Python；
- 无限Replan；
- Memory替代实时数据和Evidence；
- 为框架展示而引入无用中间件。
