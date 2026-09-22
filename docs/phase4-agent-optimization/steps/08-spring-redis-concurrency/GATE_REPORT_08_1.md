# Step 08.1 Redis 共享热状态 Gate 报告

## 结论

状态：`PASS`。

Redis 已作为可丢失、可重建的热状态层接入。PostgreSQL 仍保存可靠任务、事件、租约、幂等终态和
检索版本；Redis 停机不会丢失任务，也不会成为绕过 PostgreSQL 最终 single-flight 的依据。

## 组件

| 组件 | 版本/配置 |
|---|---|
| Redis Server | `redis:8.4-alpine` |
| Python Client | `redis-py 8.0.1`，asyncio |
| Redis 内存 | 192 MB maxmemory，容器上限 256 MB |
| 持久化 | 关闭；Redis 数据必须可从 PostgreSQL/ES 重建 |
| Key | `financial-agent:v1:<kind>:<sha256>` |
| 默认模型 | `deepseek-v4-flash`，本 Gate 未调用模型 |

## 实现范围

- 原子 token bucket：capacity/refill/cost/TTL；
- 带到期清理的分布式并发槽位；
- tenant-scoped 幂等热映射；
- RetrievalSnapshot 和 AnalysisArtifact metadata L1；
- Job Pub/Sub 唤醒与最后事件短 TTL marker；
- Redis 健康、操作数、错误数和 metadata hit/miss 指标；
- Redis disabled/unavailable 的显式降级结果。

Redis key 对 tenant、user、idempotency key 和业务标识进行 SHA-256，不保存这些原文。L1 metadata
限制为 16 KiB，不保存最终报告、用户记忆或完整 Evidence。

## 真实 Redis 原子 Gate

| 场景 | 输入 | 结果 |
|---|---:|---:|
| token bucket | 20 路并发，capacity=5 | 只放行 5 |
| 并发槽位 | 10 路并发，limit=2 | 只获取 2 |
| 幂等映射 | 20 路相同 key | 1 个 run_id |
| metadata | set/get | PASS |
| Pub/Sub | subscribe/publish | 收到 `job_terminal` |

## 真实 Job API 幂等 Gate

暂停 Worker 后，同时向 Job API 提交 20 个相同 tenant、user、输入和 Idempotency-Key：

```text
HTTP statuses=[202]
unique_run_ids=1
created_true=1
run_id=7f8bd584641c4062932275d1686d75c9
```

测试 Job 随后被取消，没有触发 Tool 或模型调用。Redis 用于快速命中，PostgreSQL 唯一键仍是最终确认。

## Redis 停机降级 Gate

短暂停止 Redis 后执行健康检查和 Job 创建/读取/取消：

```text
health=degraded
redis.status=unavailable
redis.detail=PING_FAILED
create_status=202
created=true
read_status=queued
cancel_status=200
```

说明 Redis 故障可见，但 PostgreSQL 可靠链路继续工作。Redis 与 Worker 已在 Gate 后恢复。

## 全量回归

```text
170 passed, 24 skipped, 19 warnings in 15.71s
Ruff: PASS
compileall: PASS
git diff --check: PASS
```

24 个 skipped 包含需要真实 Redis、PostgreSQL、Docker或其他外部服务的可选集成项；真实 Redis 测试已
在单独 Gate 中运行通过。warnings 是 FastAPI `on_event` 和 TestClient 的既有弃用提示。

## 边界

- Redis Pub/Sub 只负责唤醒，不负责事件可靠存储；SSE 断线重连仍回放 PostgreSQL Event；
- Redis metadata 只是指向 PostgreSQL 产物的 L1 索引，命中后仍校验数据库版本与有效期；
- Redis token bucket/slot 将在 08.2 由 Spring Gateway 用于公网准入；
- Redis 故障时 Python 当前配置为 fail-open，但仍受 PostgreSQL 队列、运行数和Provider预算约束；
- 生产环境是否改为 fail-closed，将在 Spring endpoint 分级策略中决定。
