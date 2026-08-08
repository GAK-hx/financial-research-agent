# Docker部署、备份与保留手册

## 1. 前置条件

- Docker Desktop或Docker Engine；
- 项目根目录存在由`.env.example`复制的`.env`；
- 模型Key只写入`.env`，不得进入代码、镜像、日志或文档；
- 需要复用研报时，确认`../financial-agent/data/reports`只读目录存在。

## 2. 正式本地启动

```bash
docker compose --profile harness build langgraph-app job-api job-worker
docker compose --profile harness up -d langgraph-app
docker compose --profile harness up -d job-api job-worker
docker compose --profile harness ps
```

入口：

- 同步LangGraph API：`http://localhost:8001`；
- Job API：`http://localhost:8002`；
- Milvus：`localhost:19531`。

健康检查：

```bash
curl http://localhost:8001/health
curl http://localhost:8002/health
```

## 3. 数据初始化

只有新建数据卷或明确需要更新数据时才运行：

```bash
docker compose --profile ingestion run --rm data-bootstrap
docker compose --profile ingestion run --rm market-ingest
docker compose --profile ingestion run --rm financial-ingest
docker compose --profile rag run --rm rag-index \
  python -m financial_research_agent.rag.indexer --mode rebuild
```

`rebuild`会重建Milvus Collection，不应在日常启动时执行。已存在的数据卷使用
`--mode skip`或直接跳过索引任务。

## 4. PostgreSQL备份与恢复

备份：

```bash
docker compose --profile harness exec postgres sh -lc \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
  -f /tmp/financial_agent.dump'
```

复制到宿主机：

```bash
docker cp financial-research-agent-postgres-1:/tmp/financial_agent.dump \
  ./artifacts/backups/financial_agent.dump
```

恢复前必须停止API和Worker，防止恢复期间继续写入：

```bash
docker compose --profile harness stop langgraph-app job-api job-worker
```

优先恢复到新数据库验证，不直接覆盖现有数据库：

```bash
docker compose --profile harness exec postgres sh -lc \
  'createdb -U "$POSTGRES_USER" financial_agent_restore &&
   pg_restore -U "$POSTGRES_USER" -d financial_agent_restore \
   /tmp/financial_agent.dump'
```

验证`alembic_version`、表数和关键Run后，再决定是否切换连接字符串。删除临时恢复库属于
显式运维操作，不应写入自动启动脚本。

## 5. Memory保留与删除

- Session Memory默认TTL为30天；
- Preference Memory必须显式确认，可配置独立TTL；
- 过期Memory使用`POST /memory/cleanup`软删除并写审计；
- 单条删除使用`DELETE /memory/{memory_id}`；
- Session级删除使用`DELETE /sessions/{session_id}/memory`；
- 查询必须携带相同Tenant/User Scope。

示例：

```bash
curl -X POST http://localhost:8002/memory/cleanup
curl -X DELETE \
  'http://localhost:8002/sessions/demo-session/memory?tenant_id=demo&user_id=demo'
```

删除是软删除，审计记录保留。物理清理需另行制定数据保留政策，当前Demo不自动执行。

## 6. Checkpoint与Artifact保留

- Checkpoint与业务Run分表管理，不应绕过业务终态直接删除单条Checkpoint；
- 当前Demo不自动清理Checkpoint；
- `artifacts/`保存评测、失败输出和交付证据，不随容器停止删除；
- 清理前应先备份PostgreSQL，并确认Run已进入终态；
- `docker compose down`保留卷；不要附加`-v`，除非明确要永久删除数据。

## 7. 停止与恢复

保留数据停止：

```bash
docker compose --profile harness stop \
  langgraph-app job-api job-worker milvus etcd postgres
```

恢复：

```bash
docker compose --profile harness up -d langgraph-app job-api job-worker
```

Worker由PostgreSQL Lease协调。异常退出后新Worker只能接管过期Lease；已完成调用通过
幂等键复用，不重新产生副作用。

## 8. 常见问题

- API为`degraded`：检查模型名、Base URL和Key；
- 报告`validation_failed`：查看报告校验错误，不要关闭Validator；
- Job长时间Queued：检查Worker日志和PostgreSQL；
- Milvus查询失败：检查etcd、Milvus和索引Collection；
- 模型429/网络中断：保留失败产物，Provider会按配置退避重试；
- Budget未闭合：视为治理缺陷，不能把Run标为成功。

