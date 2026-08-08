# 项目演示脚本

建议演示时长：8—12分钟。

## 1. 开场

一句话说明：

> 这是一个面向日线和中长期股票分析的只读Agent。LangGraph负责状态图和恢复，项目的
> Harness负责Skill、工具权限、预算、Memory、Evidence和最终报告校验。

先声明边界：不下单、不支持实时分钟行情、模型不能直接访问数据库或执行代码。

## 2. 启动与健康

```bash
docker compose --profile harness up -d job-api job-worker
curl http://localhost:8002/health
curl http://localhost:8002/skills
curl http://localhost:8002/tools
```

讲解：API、Worker、PostgreSQL、Milvus分开部署；Skill和Tool均可审计。

## 3. 提交异步Run

```bash
curl -X POST http://localhost:8002/runs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: interview-demo-v1' \
  -d '{
    "question":"分析贵州茅台最近三年的营收和利润",
    "tenant_id":"demo",
    "user_id":"candidate",
    "session_id":"interview"
  }'
```

记录返回的`run_id`。

## 4. 查看SSE和状态

```bash
curl -N http://localhost:8002/runs/<run_id>/events
curl http://localhost:8002/runs/<run_id>
```

重点展示：

- Interpret得到股票、时间和Intent；
- Skill选择及版本；
- Plan只包含意图需要的Tool；
- Worker执行后产生Evidence；
- Validator和Completion决定是否可成功。

断开SSE后使用最后的Event ID恢复：

```bash
curl -N \
  -H 'Last-Event-ID: <last_event_id>' \
  http://localhost:8002/runs/<run_id>/events
```

SSE断开不取消后台任务。

## 5. 查看Trace

```bash
curl http://localhost:8002/runs/<run_id>/trace
```

展示Model Call、Tool Call、节点、Context Manifest、Attempt和终态。强调Trace不保存API
Key、完整隐藏推理或任意模型上下文。

## 6. 展示Evidence和报告

在Run结果中说明：

- `tool_status`显示实际执行的白名单Tool；
- Evidence包含类型、主体、结构化数据和Source Locator；
- Claim引用当前Run的Evidence ID；
- 数字、日期、机构和页码由程序校验；
- `budget.open_reservations`必须为0；
- `completion.passed`才允许`success=true`。

## 7. 展示Memory

```bash
curl \
  'http://localhost:8002/sessions/interview/memory?tenant_id=demo&user_id=candidate'

curl -X DELETE \
  'http://localhost:8002/sessions/interview/memory?tenant_id=demo&user_id=candidate'
```

说明Session Memory按Tenant/User/Session隔离、默认30天TTL、支持查询和删除；Evidence不会
作为模型可改写的长期事实写入Memory。

## 8. 恢复演示

长任务运行时停止Worker：

```bash
docker compose --profile harness stop job-worker
docker compose --profile harness up -d job-worker
```

如果任务因Lease丢失进入`interrupted`，使用：

```bash
curl -X POST http://localhost:8002/runs/<run_id>/resume
```

随后查看Trace，确认已完成Tool没有重复执行、终态只写一次。不要为了演示在短任务已经
完成后强行宣称发生了恢复；可直接展示Step 07/08保存的恢复测试证据。

## 9. 收尾

说明职责边界：

- LangGraph：StateGraph、Checkpoint、Interrupt/Resume；
- 项目：金融Schema、Skill、Gateway、Policy/Budget、Memory/Context、Evidence、
  Validator、Completion和Job协调；
- DeepSeek：结构化规划和报告表达；
- Iceberg/Milvus/PostgreSQL：真实数据、研报检索和运行审计。

