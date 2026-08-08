# Step 07 Worker与租约设计

## 1. PostgreSQL队列

`research_jobs`保存请求哈希、身份范围、状态、Attempt、取消标记、可领取时间、
Lease、终态结果和错误；`job_events`保存队列层事件。LangGraph的`runs`、
`run_events`和Checkpoint表仍保持原职责。

Worker使用`SELECT … FOR UPDATE SKIP LOCKED`按创建时间领取：

- Queued任务可领取；
- Running但Lease已过期的任务可回收；
- 活跃Lease不能被第二个Worker领取；
- 每次领取增加Job Attempt并记录Worker ID；
- 续租周期为Lease的三分之一；
- Lease丢失时取消本进程执行，避免无所有权写终态。

## 2. 幂等与恢复

即使Worker在外部调用后崩溃，Model/Tool Gateway仍使用业务幂等键和独立调用Lease，
已完成结果可复用。LangGraph通过PostgreSQL Checkpoint继续未完成Run，因此Job
回收不等于从头重复所有副作用。

20任务双Worker竞争实测：

```text
worker-1 claimed     9
worker-2 claimed    11
Job attempt != 1     0
重复Node Attempt组    0
重复Tool副作用组      0
```

## 3. Docker部署

- `job-api`：700MiB限制，对外端口默认8002；
- `job-worker`：1000MiB限制，固定`worker-1`；
- `job-worker-2`：1000MiB限制，固定`worker-2`，通过`workers` profile启用；
- `postgres`：512MiB；
- Worker收到SIGTERM后停止领取新任务，等待当前循环退出并关闭LangGraph、数据库连接；
- `stop_grace_period`为270秒，与最长Run的受控退出窗口匹配。

空闲Worker-2实测收到SIGTERM后输出`worker_stopped`，退出正常。
