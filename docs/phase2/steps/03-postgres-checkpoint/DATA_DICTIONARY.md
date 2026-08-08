# Step 03业务数据字典

## 责任分离

以下7张表属于Harness业务Schema，由Alembic版本`20260724_0001`管理。`checkpoints`、`checkpoint_blobs`、`checkpoint_writes`和`checkpoint_migrations`属于LangGraph，不进入业务Alembic。

## `runs`

Run权威元数据和状态投影。

| 字段 | 说明 |
|---|---|
| `id` | Run ID，主键 |
| `thread_id` | LangGraph Thread ID，唯一 |
| `question` | 原始问题 |
| `status` | `running/interrupted/completed/failed` |
| `runtime` | 当前为`langgraph` |
| `cancel_requested` | 节点安全边界取消标记 |
| `event_sequence` | 下一Event序列的原子计数 |
| `last_checkpoint_id` | 最近Checkpoint引用 |
| `version` | 终态写入时递增的乐观版本 |

## `run_events`

Run审计事件。`(run_id, sequence)`唯一，事件Payload只放结构化诊断信息，不放密钥、隐藏推理或完整Provider响应。

## `node_attempts`

节点执行尝试。`(run_id, node_name, attempt_no)`唯一；状态为`running/completed/failed/cancelled`。

## `model_calls`

模型调用幂等和审计记录。

- `idempotency_key`全局唯一；
- `request_hash`防止相同Key复用不同输入；
- `result_payload`只保存结构化Plan或Report；
- `lease_owner/lease_expires_at`支持Worker故障接管；
- 不保存API Key、Authorization Header或原始HTTP响应。

## `tool_calls`

Tool调用幂等和结果复用记录。

- `(run_id, task_id)`唯一；
- `idempotency_key`全局唯一；
- `input_hash`保护输入一致性；
- `result_payload`保存结构化`ToolResult`；
- Tool仍受Registry、Pydantic输入和只读策略约束。

## `artifact_refs`

Artifact URI和最小元数据。实际文件仍在Artifact Volume，数据库不保存大文件。

## `terminal_results`

每个Run唯一的最终`ResearchRunResult`。`run_id`同时为主键和外键；重复相同写入幂等，不同终态冲突。
