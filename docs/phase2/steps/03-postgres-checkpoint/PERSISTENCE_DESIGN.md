# Step 03 PostgreSQL持久化设计

## 1. 目标与边界

同一PostgreSQL实例承载两类相互独立的存储：

1. LangGraph `AsyncPostgresSaver`保存Graph State、Checkpoint和Pending Writes；
2. Harness Business Store保存Run状态、审计事件、节点尝试、外部调用、Artifact引用和唯一终态。

Checkpoint表由官方`setup()`管理，业务表由Alembic管理。两者不得相互创建、修改或删除对方的表。

本步不实现Job API、Worker领取、Skill、Budget、Memory或完整Gateway。

## 2. 版本

| 组件 | 固定版本 |
|---|---|
| PostgreSQL | `17.10-alpine3.23` |
| LangGraph | `1.2.9` |
| PostgreSQL Checkpointer | `langgraph-checkpoint-postgres==3.1.0` |
| Psycopg | `3.3.4` |
| SQLAlchemy | `2.0.51` |
| asyncpg | `0.31.0` |
| Alembic | `1.18.5` |
| PyCryptodome | `3.23.0` |

## 3. 标识映射

| 标识 | 权威来源 | 规则 |
|---|---|---|
| `run_id` | `runs.id` | 业务Run主键 |
| `thread_id` | `runs.thread_id` | 当前等于`run_id`，唯一 |
| `checkpoint_id` | LangGraph | 只引用到`runs.last_checkpoint_id`，业务端不生成 |
| `attempt_id` | `node_attempts.id` | `{run_id}:{node}:{attempt_no}` |
| Model幂等键 | `model_calls.idempotency_key` | `{run_id}:{node}:model` |
| Tool幂等键 | `tool_calls.idempotency_key` | `{run_id}:execute_tools:{task_id}` |

## 4. Serializer策略

- Graph State继续只写JSON安全值；
- `JsonPlusSerializer`关闭pickle fallback；
- `allowed_json_modules=()`、`allowed_msgpack_modules=[]`；
- Compose设置`LANGGRAPH_STRICT_MSGPACK=true`；
- 单个序列化值默认不超过2 MB；
- 超限返回`CHECKPOINT_PAYLOAD_TOO_LARGE`；
- 生产设置`CHECKPOINT_ENCRYPTION_ENABLED=true`并提供16/24/32字节`CHECKPOINT_AES_KEY`；
- 加密使用官方`EncryptedSerializer.from_pycryptodome_aes`；
- Key只来自环境变量，不写入State、数据库、日志或文档。

本地默认关闭加密，便于开发；Gate 03必须验证加密Round Trip和错误Key拒绝解密。

## 5. Run状态

```text
running
  ├── interrupted → resume → running
  ├── completed
  └── failed
```

- Worker中止、总超时或数据库暂时不可用时，不写业务终态，Run标记`interrupted`；
- 只有Graph到达唯一`finalize`后才写`terminal_results`；
- `terminal_results.run_id`为主键，同一Run只能有一个终态；
- 相同终态重复写是幂等操作；不同终态重复写直接冲突；
- 已存在终态的Run再次提交时直接返回保存结果，不调用模型或Tool。

## 6. 节点Attempt与Event

- 节点开始前写`node_attempts(status=running)`；
- 同一`run_id + node + attempt_no`唯一；
- 完成、失败或取消后写结束时间和错误码；
- `runs.event_sequence`在单条原子UPDATE中递增；
- `run_events(run_id, sequence)`唯一，保证同一Run事件严格有序；
- Checkpoint保存执行状态，Event用于审计，不复制Pending Writes。

## 7. Model/Tool幂等

- 调用前以幂等键和输入Hash占用记录；
- 已完成记录直接复用结构化结果；
- 相同Key但不同输入立即拒绝；
- 执行中记录带Worker租约，未过期时其他Worker不得接管；
- 失败记录可重试；Worker消失后只有租约过期才允许接管；
- Tool继续全部只读，因此租约恢复不会产生数据写入副作用；
- Provider不提供服务端幂等键，模型响应返回与数据库提交之间仍存在极小崩溃窗口；Step 05 Gateway继续处理调用级重试、费用和Provider能力。

当前Gate的“重复副作用为0”口径是：已成功落库的Model/Tool结果在重启和重复Resume中不再次调用。

## 8. Cancel/Resume

- `request_cancel`只设置数据库标记并写Event；
- Graph在每个节点安全边界读取取消标记；
- 已进入外部HTTP/Tool调用时不强制杀协程，在下一个节点边界停止；
- 本步提供Service底层`resume(run_id)`和`request_cancel(run_id)`；
- HTTP Job API、Cancel/Resume端点和Worker领取属于Step 07。

## 9. 恢复流程

```text
Worker退出
  → PostgreSQL保留最近Checkpoint
  → 新进程使用原thread_id
  → graph.ainvoke(None, config)
  → 已完成Checkpoint节点不重跑
  → 已完成Model/Tool调用从业务表复用
  → Finalize
  → 唯一Terminal Result
```

Interrupt恢复使用原`thread_id`和`Command(resume=...)`。重复Resume读取已完成Graph，不产生第二终态或第二次Tool调用。

## 10. 保留与清理

Step 03不自动删除数据。建议在Step 08按以下顺序实现保留策略：

1. 保留仍在运行或中断的Run及全部Checkpoint；
2. 已完成Run先导出/确认Artifact；
3. 删除Checkpoint历史；
4. 再删除业务Run，外键级联清理Event/Attempt/Call/Terminal；
5. Skill、Memory和用户审计采用独立保留周期。
