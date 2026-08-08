# Step 07 Job API设计

## 1. 服务边界

API进程负责请求校验、Job入队、状态查询和事件输出，不在进程内保存队列状态。
Worker从PostgreSQL领取任务并调用LangGraph正式运行时。两者共享版本化Python领域包，
不共享内存对象，因此API重启不会取消Worker中的Run。

## 2. 接口

```text
POST   /runs
GET    /runs/{run_id}
GET    /runs/{run_id}/events
GET    /runs/{run_id}/events.json
POST   /runs/{run_id}/cancel
POST   /runs/{run_id}/resume
GET    /runs/{run_id}/trace
GET    /skills
GET    /skills/{skill_id}
GET    /sessions/{session_id}/memory
DELETE /sessions/{session_id}/memory
GET    /metrics
POST   /analyze
```

`POST /runs`接受`Idempotency-Key`。相同Key与相同输入返回原Job并标记
`created=false`；相同Key用于不同输入返回409。

`GET /runs/{run_id}`同时返回Job状态和终态结果。SSE使用标准`id/event/data`格式，
支持`Last-Event-ID`或`after`游标；JSON事件端点用于调试和自动化。

## 3. 状态转换

```text
queued → running → completed | failed | cancelled
                 ↘ interrupted → queued
```

- Queued取消立即进入Cancelled，重复取消幂等；
- Running取消写入Job和LangGraph Run的取消标记，由节点边界安全停止；
- 只有Interrupted允许Resume，重复Resume保持Queued/Running；
- Completed、Failed或Cancelled上的非法Cancel/Resume返回409；
- Interrupted恢复沿用同一Run ID和Checkpoint；
- Failed/Cancelled若需重试，应显式创建新Run，避免修改已封存终态。

## 4. 同步兼容

独立Job API容器中，`POST /analyze`先入队并在限定时间内等待：

- Worker及时完成时，返回原有`AnalyzeResponse`与HTTP 200；
- 等待超时时，返回HTTP 202、Run ID和`Location`，后台Job不被取消；
- 原`langgraph-app`仍可保留直接同步模式，便于第一阶段兼容和评测。
