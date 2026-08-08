# 05 API、Worker、SSE与Docker部署

## 1. 当前服务化状态

同步`/analyze`与异步Job API均已实现。长任务可以查询状态、订阅SSE、取消和恢复，
API重启、客户端断开或单个Worker退出不会丢失已持久化Run。

## 2. 当前API

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
POST   /analyze
```

### 创建Run

`POST /runs` 接收问题、Session 和 Idempotency Key。响应立即返回 Run ID 和初始状态。重复 Key 返回同一 Run。

### 状态与结果

`GET /runs/{run_id}` 返回：

- 当前状态和节点；
- 创建、更新时间；
- Skill Snapshot；
- Tool/Evidence 计数；
- Budget摘要；
- 成功时的最终 Artifact；
- 失败时的结构化错误。

### Cancel与Resume

- Running Run 可请求 Cancel；
- Cancel 在节点安全边界生效；
- Interrupted Run 可 Resume；
- Completed/Failed 的非法 Resume 被拒绝或幂等返回；
- Cancel/Complete 竞态只能产生一个合法终态。

### Trace

Trace 只返回可审计事实：节点、Attempt、Tool、Budget、错误和时间，不返回隐藏推理、完整敏感 Prompt 或未校验草稿。

## 3. SSE事件

SSE 事件包含：

```text
run.created
node.started
node.completed
tool.started
tool.completed
budget.warning
run.interrupted
run.completed
run.failed
```

每个 Event 有严格递增 ID。客户端断线后使用 Last-Event-ID 继续，不要求服务器把历史事件留在内存中。

## 4. API与Worker拆分

```text
API
  ├── 校验与鉴权
  ├── 创建/查询Run
  ├── SSE
  └── Cancel/Resume命令

Worker
  ├── PostgreSQL原子领取
  ├── Lease续期
  ├── LangGraph执行
  ├── Gateway调用
  └── Artifact写入
```

第一版用 PostgreSQL 原子领取和 Lease，不急于引入 Redis/Celery。只有目标并发实测证明 PostgreSQL 方案不够时，才重新评估队列。

双 Worker 必须证明：

- 同一 Run 不被同时领取；
- 同一 Attempt 不重复执行；
- Lease 过期后可接管；
- 已完成 Model/Tool 结果可复用；
- 优雅停机不领取新任务并保存当前状态。

## 5. Docker Compose部署

| 服务 | 职责 | 内存上限 |
|---|---|---:|
| `app` | LangChain/LangGraph同步API | 1000 MiB |
| `job-api` | Job API、SSE、查询 | 768 MiB |
| `job-worker` | LangChain/LangGraph、BGE、Gateway | 1200 MiB |
| `postgres` | Checkpoint与业务数据 | 512 MiB |
| `milvus` | 研报向量索引 | 1800 MiB |
| `etcd` | Milvus元数据 | 256 MiB |

持久卷：

- `postgres_data`；
- `lake_data`；
- `milvus_data`；
- `etcd_data`；
- `model_cache`；
- `artifacts`。

不在当前目标中增加 Kafka、Flink、ClickHouse、MinIO、Kubernetes 或自动交易基础设施。

## 6. 启动顺序

```text
PostgreSQL / etcd
  ↓ health
Milvus
  ↓
Alembic Migration
  ↓
API / Worker
  ↓
Readiness
```

Readiness 不只检查进程存活，还检查：

- 配置有效；
- PostgreSQL 可查询；
- Iceberg Catalog 可访问；
- Milvus 可访问；
- 模型已配置；
- 必要迁移已应用。

## 7. 配置与Secret

`.env.example` 只提供字段和本地默认值。真实环境：

- API Key 和数据库密码由 Secret 管理；
- Checkpoint 启用 AES；
- 日志递归脱敏；
- 数据库限制网络访问；
- Artifact 和数据库定义备份周期；
- 不把 Key 放进 Skill、Memory、State 或评测产物。

## 8. 可观测性

结构化日志至少带：

- request_id / run_id / thread_id；
- node / attempt；
- skill_id / version；
- model / prompt / tool version；
- duration；
- retry_count；
- token / cost；
- policy / budget result；
- error_code。

指标包括：

- Run成功率和合法终态率；
- 节点P50/P95；
- Provider网络错误与重试；
- Tool成功率；
- Checkpoint和数据库增长；
- Token与费用；
- Lease接管和重复副作用；
- API/Worker CPU、内存和磁盘。

## 9. 运维操作

当前Runbook覆盖：

- 空环境部署；
- Alembic升级和安全降级；
- PostgreSQL备份/恢复；
- Checkpoint历史清理；
- Memory TTL和用户删除；
- Artifact保留；
- Worker扩缩和优雅停机；
- Provider故障降级；
- Milvus重建；
- 数据批次与Snapshot审计。
