# Step 01 Graph State与边界规范

## 1. 运行时边界

LangGraph只管理节点、边、Checkpoint、中断与恢复。现有Pydantic领域模型、Tool Registry、Planner、Evidence Builder和Validator仍是业务语义来源。

Step 01只建立旁路Spike，不替换`OrchestrationService`和`POST /analyze`。

## 2. Graph State

Graph State只保存JSON-safe值：

```text
run_id: string
thread_id: string
attempt_id: string
question: string
stage: string
query_spec: object | null
plan: object | null
planner_source: string | null
tool_results: array[object]
evidence: array[object]
report_preview: object | null
errors: array[SpikeError]
tool_execution_approved: boolean | null
```

Pydantic对象在节点入口恢复、在节点出口使用`model_dump(mode="json")`转换。Graph State禁止保存：

- 数据库连接、HTTP Client、模型Client和Tool实例；
- Pandas DataFrame、PyArrow Table和打开的文件；
- Exception对象、函数、协程、锁和Semaphore；
- API Key、Authorization Header和未脱敏Provider响应；
- 大型原始PDF、完整行情表和Embedding。

## 3. 节点

```text
START
  → interpret
  → plan
  → validate_plan
  → [review_tool_execution]
  → execute_tools
  → build_evidence
  → build_report_preview
  → END
```

`review_tool_execution`仅用于验证interrupt/resume，可以在无人工审批的正式只读路径中关闭。模型不能决定任意下一节点。

## 4. 标识映射

| 标识 | Step 01 | 后续正式语义 |
|---|---|---|
| `run_id` | 业务运行唯一ID | `runs.id` |
| `thread_id` | 默认等于`run_id` | LangGraph Checkpoint Thread |
| `attempt_id` | 默认`run_id:1` | 节点/Run执行尝试 |
| `checkpoint_id` | InMemorySaver生成 | Checkpointer内部标识，只引用不自造 |
| `idempotency_key` | `run_id:node:operation`候选格式 | Gateway副作用唯一键 |

Thread ID不代替业务Run ID，Checkpoint不代替业务审计表。

## 5. 错误分类

```text
SCHEMA_VALIDATION_ERROR
INTERPRETATION_ERROR
PLANNING_ERROR
PLAN_VALIDATION_ERROR
TOOL_EXECUTION_ERROR
EVIDENCE_BUILD_ERROR
INTERRUPT_REJECTED
STATE_SERIALIZATION_ERROR
UNKNOWN_ERROR
```

错误记录只保存`code/node/retryable/message`。不得把Exception、堆栈、密钥或完整Provider响应写入Graph State。

## 6. Checkpoint与业务Store

| 数据 | Checkpoint | 业务Store |
|---|---|---|
| 当前节点与Graph State | 主存储 | Run状态投影 |
| Pending Writes | 主存储 | 不复制 |
| Run终态和创建者 | 不作为权威源 | 权威源 |
| Model/Tool调用与费用 | 仅保留必要引用 | 权威源 |
| Skill/Policy/Prompt版本 | Run Snapshot | 权威版本与发布记录 |
| Evidence完整结构 | 当前Run必要字段/引用 | 权威源 |
| Session/Preference Memory | 不放入Run Checkpoint | 权威源 |
| Artifact | 只保存引用 | 文件/对象存储及业务元数据 |

Step 01使用`InMemorySaver`；`AsyncPostgresSaver`、状态加密与业务表进入Step 03。

## 7. 副作用与恢复

- interrupt前不执行非幂等副作用；
- Tool/Model调用后续必须通过Gateway并携带业务幂等键；
- 节点重启时从Pydantic Schema重新校验Checkpoint值；
- Resume必须使用原`thread_id`；
- 同一Run的终态只能由Completion Checker写入一次；
- LangGraph的恢复能力不能替代业务幂等与唯一约束。

## 8. Step 01依赖决定

| 组件 | 版本/范围 | Step 01决定 |
|---|---|---|
| Python | 3.11 | 与现有Docker一致 |
| LangGraph | `1.2.9` | Spike精确固定 |
| Pydantic | 现有`>=2.9,<3` | 不调整 |
| Checkpointer | LangGraph内置InMemorySaver | 仅用于Spike |
| LangChain高层Agent | 不安装 | 不需要 |
| PostgreSQL Checkpointer | 暂不安装 | Step 03再验证并固定 |

版本选择依据2026-07-24的官方安装文档与PyPI稳定版本；进入正式迁移后仍通过依赖锁和Regression验证。
