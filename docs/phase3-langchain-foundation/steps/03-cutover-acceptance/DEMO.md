# LangChain/LangGraph完整演示

## 1. 启动

在项目根目录配置`.env`后执行：

```bash
docker compose --profile harness up --build -d app job-api job-worker
docker compose --profile harness ps
```

默认组件：

- 主API：`http://localhost:8000`
- Job API：`http://localhost:8002`
- 模型接口：LangChain ChatModel/Runnable
- 状态运行时：LangGraph
- Checkpoint与业务审计：PostgreSQL
- 行情/财务：PyIceberg
- 研报检索：Milvus

## 2. 健康检查

```bash
curl http://localhost:8000/health
curl http://localhost:8002/health
```

期望`configuration`、`iceberg`、`milvus`和`postgres`均为`ready`。

## 3. 同步研究

```bash
curl -X POST http://localhost:8000/analyze \
  -H 'Content-Type: application/json' \
  -d '{
    "question":"分析贵州茅台最近一年的行情和趋势",
    "tenant_id":"demo",
    "user_id":"interviewer",
    "session_id":"sync-01"
  }'
```

观察：

- LangChain Structured Output生成Query与Plan；
- LangGraph按显式节点运行；
- Tool Gateway校验白名单、参数、Policy和Budget；
- StructuredTool返回ToolMessage artifact；
- Evidence Builder保留Snapshot与Source Locator；
- LangChain生成ResearchReport；
- Validator逐Claim检查数字和引用；
- Completion Checker决定是否允许`success=true`。

## 4. 异步任务和SSE

```bash
curl -X POST http://localhost:8002/runs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-async-01' \
  -d '{
    "question":"比较贵州茅台近期均线与成交量趋势",
    "tenant_id":"demo",
    "user_id":"interviewer",
    "session_id":"async-01"
  }'
```

从响应复制`run_id`：

```bash
curl -N "http://localhost:8002/runs/<run_id>/events?after=0"
curl "http://localhost:8002/runs/<run_id>"
curl "http://localhost:8002/runs/<run_id>/trace"
```

SSE只输出节点状态、Tool摘要、Budget Snapshot和终态，不输出隐藏推理。

## 5. 显式回退

仅用于兼容诊断：

```bash
docker compose run --rm \
  -e AGENT_FRAMEWORK=native \
  -e ORCHESTRATION_RUNTIME=legacy \
  app
```

默认生产演示不使用该路径。

## 6. 面试讲解顺序

1. 先说明LangChain解决接口标准化，LangGraph解决状态运行与恢复；
2. 展示模型不能直接访问数据库，所有真实数据只能通过Tool Gateway；
3. 展示ToolMessage artifact、Evidence ID和Source Locator；
4. 展示Validator如何拒绝无来源数字；
5. 展示SSE与PostgreSQL Checkpoint如何支持长任务；
6. 最后说明框架外的金融增强点：Skill、Policy/Budget、Memory/Context、
   Evidence与Completion。

