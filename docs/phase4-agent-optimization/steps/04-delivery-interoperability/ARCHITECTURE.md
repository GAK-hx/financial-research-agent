# Step 04 架构：多租户并发交付

## 1. 实现结论

Step 04 没有替换前三步的 LangChain、LangGraph、Gateway、Evidence 和 Validator，
而是在正式异步入口外增加可验证的服务治理层：

```text
HTTP 请求
  → Identity Boundary
  → Admission（全局 / 租户 / 用户）
  → PostgreSQL Job Queue
  → 交互优先 + 租户公平领取
  → 有界并发 Worker
  → LangGraph + LangChain
  → Gateway / Policy / Budget
  → Tool / Evidence / Validator / Report
```

PostgreSQL 继续同时承担 Job 真相、Lease、Checkpoint、预算和审计。冻结负载没有证明它已成为
不可接受的业务瓶颈，因此没有引入 Redis 或 Celery，也没有形成第二套状态真相。

## 2. 身份与隔离

业务请求不再决定 `tenant_id` 和 `user_id`。HTTP 边界支持两种模式：

- `local`：固定为 `local/local`，仅用于单机开发；
- `api_key`：校验 Bearer Key，再从 `X-Tenant-ID`、`X-User-ID` 和
  `X-Agent-Role` 解析身份。

`/runs` 和 `/analyze` 的公开请求模型禁止租户、用户字段。Run 状态、结果、Event、Trace、
取消和恢复查询都会把身份条件带入 Repository；跨租户和跨用户访问表现为 `404`，不泄露对象
是否存在。租户管理员可查看同租户其他用户，但不能跨租户。

Memory API 暂时保留旧请求模型以兼容内部调用，但服务端会用认证身份覆盖其中的租户和用户，
因此请求体不能扩大访问范围。

## 3. 准入、背压和公平调度

准入使用 PostgreSQL 事务锁保护以下上限：

| 层级 | 排队默认值 | 运行默认值 |
|---|---:|---:|
| 全局 | 100 | 8 |
| 租户 | 20 | 3 |
| 用户 | 5 | 2 |

超过排队上限返回 `429`，响应包含结构化原因、`retryable=true`、建议等待时间和
`Retry-After`。幂等键按租户唯一；同一租户重试复用原 Run，不同租户可以使用相同键。

队列分为 `interactive` 和 `batch`。交互任务优先；同优先级先从每个租户取最早候选，
再依据 `tenant_schedule.last_claimed_at` 轮转。领取事务同时检查全局、租户、用户运行上限，
并使用 `FOR UPDATE SKIP LOCKED` 和 Lease 防止重复领取。

当前准入为了严格保证全局上限，会短暂串行化计数与入队。这使 50 VU 下 API 接收 P95 达到
约 1.79 秒。它适合耗时较长、吞吐中等的研究任务，不应包装成高 QPS 网关。只有当业务确实
要求更高接收吞吐时，下一步才应把计数改成原子 Counter/Lease 表，再重新评估队列选型。

## 4. Worker 与资源池

一个 Worker 进程默认运行两个 Slot，每个 Slot 独立领取、续租和执行 Run。收到退出信号后，
Worker 停止领取新任务，已有 Slot 完成或安全中断后再释放数据库与模型资源。

资源边界包括：

- PostgreSQL 可配置连接池、Overflow 和等待超时；
- 模型进程内 Semaphore；
- 可选 PostgreSQL 固定分钟窗口，在多个 Worker 间共享 DeepSeek 请求额度；
- DeepSeek `429` 和可重试错误沿用有限指数退避，并识别 `Retry-After`；
- 单 Run 内继续受 Gateway、Policy、Budget、Tool 并行度和超时约束。

固定分钟窗口是保守保护，不等同于供应商精确配额。生产值应按 DeepSeek 账户实际限额配置。

## 5. 可观测性

Job 状态补充 `queue_wait_ms`、`execution_ms` 和 `total_ms`。Prometheus 文本端点增加：

- 准入接受/拒绝计数；
- 最老排队任务等待时间；
- 活跃 Worker；
- 原有 Job、模型调用、Token、费用和 Tool 调用指标。

Trace 仍记录 Node Attempt、Model Call、Tool Call 和 Context Manifest；SSE/JSON Event 继续支持
断线后的 `Last-Event-ID` 或 `after` 游标恢复。

## 6. 演示界面

`/demo` 是无独立前端构建链的薄界面。它调用正式 `/runs`、`/runs/{id}` 和 Event JSON
接口，展示任务状态、事件和最终结果；API Key 只保存在当前页面内存，不写 Local Storage。
界面用于演示和调试，不承担生产身份系统职责。

