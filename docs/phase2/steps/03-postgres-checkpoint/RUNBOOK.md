# Step 03 PostgreSQL运行手册

## 启动

```bash
docker compose --profile harness up -d postgres
docker compose --profile harness run --rm db-migrate
docker compose --profile harness up -d langgraph-app
```

`langgraph-app`也会等待PostgreSQL健康和`db-migrate`成功后启动。

## 配置

开发环境可使用`.env.example`中的本地默认值。生产环境必须：

- 修改PostgreSQL密码；
- 使用Secret管理数据库URL；
- 设置`CHECKPOINT_ENCRYPTION_ENABLED=true`；
- 设置随机的16/24/32字节`CHECKPOINT_AES_KEY`；
- 限制PostgreSQL网络访问；
- 备份`postgres_data`。

模型网络暂时不稳定时，当前开发默认使用：

```env
MODEL_TIMEOUT_SECONDS=45
MODEL_MAX_RETRIES=2
MODEL_RETRY_BACKOFF_SECONDS=2
MODEL_RETRY_MAX_BACKOFF_SECONDS=8
RUN_TIMEOUT_SECONDS=240
CALL_LEASE_SECONDS=180
```

只对连接/超时及408、409、425、429、5xx瞬时错误重试。JSON、Schema、
Policy、Budget和Validator错误不重试。调用租约必须覆盖一次完整重试窗口，
避免慢请求被第二个Worker提前接管。

## Alembic

```bash
docker compose --profile harness run --rm db-migrate alembic current
docker compose --profile harness run --rm db-migrate alembic upgrade head
docker compose --profile harness run --rm db-migrate alembic downgrade base
```

降级会删除Harness业务表，属于破坏性操作，只允许在空测试数据库执行。它不会删除LangGraph Checkpoint表。

## 恢复审计

第一进程写入Interrupt：

```bash
docker compose --profile harness run --rm langgraph-app \
  python -m financial_research_agent.persistence.audit \
  interrupt --thread-id recovery-demo
```

新进程继续：

```bash
docker compose --profile harness run --rm langgraph-app \
  python -m financial_research_agent.persistence.audit \
  resume --thread-id recovery-demo
```

再次执行Resume时`tool_calls`应为0，证明完成状态未重放。

## 容量

```bash
docker compose --profile harness run --rm langgraph-app \
  python -m financial_research_agent.persistence.audit inspect
```

输出数据库总字节数和逐表大小。Step 03只记录增长，不启用自动清理。

## 故障处理

| 现象 | 检查 |
|---|---|
| App健康检查PostgreSQL unavailable | `docker compose ps postgres`和数据库URL |
| Checkpoint表不存在 | 确认App有权限并检查官方`setup()`错误 |
| 业务表不存在 | 运行`db-migrate` |
| AES Key错误 | 使用原Key恢复；不要用新Key覆盖旧数据 |
| `CALL_IN_PROGRESS` | 确认旧Worker已停止，等待租约过期 |
| Terminal冲突 | 停止继续写入，保留Run/Event并审计两个结果来源 |
