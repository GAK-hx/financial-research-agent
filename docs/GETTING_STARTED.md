# 快速使用

## 配置

```bash
cp .env.example .env
```

填写模型配置：

```dotenv
MODEL_PROVIDER=openai_compatible
MODEL_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-flash
MODEL_API_KEY=
```

真实Key、数据库口令和加密Key只写入未跟踪的`.env`或Secret Manager。

## Docker启动

启动API、Worker、PostgreSQL和研报检索依赖：

```bash
docker compose --profile harness up -d \
  postgres etcd milvus db-migrate job-api job-worker
```

需要统一认证、Redis限流和SSE代理时，再启动Spring Gateway：

```bash
docker compose --profile harness --profile concurrency --profile gateway \
  up -d redis backend-gateway
```

- FastAPI：`http://localhost:8002`
- Spring Gateway：`http://localhost:8080/api/v1`

## 提交分析任务

```bash
curl -X POST http://localhost:8080/api/v1/runs \
  -H "Authorization: Bearer $GATEWAY_EXTERNAL_API_KEY" \
  -H "Idempotency-Key: risk-600519-001" \
  -H "Content-Type: application/json" \
  --data '{"question":"分析600519最近报告期的盈利质量和偿债风险"}'
```

查询状态：

```bash
curl -H "Authorization: Bearer $GATEWAY_EXTERNAL_API_KEY" \
  http://localhost:8080/api/v1/runs/<run_id>
```

订阅事件：

```bash
curl -N -H "Authorization: Bearer $GATEWAY_EXTERNAL_API_KEY" \
  -H "Last-Event-ID: 0" \
  http://localhost:8080/api/v1/runs/<run_id>/events
```

## 数据任务

```bash
docker compose --profile ingestion run --rm data-bootstrap
docker compose --profile ingestion run --rm market-ingest
docker compose --profile ingestion run --rm financial-ingest
docker compose --profile analysis run --rm factor-batch
```

增量构建研报索引：

```bash
docker compose --profile rag run --rm rag-index \
  python -m financial_research_agent.rag.indexer --mode incremental
```

## Kubernetes

`deploy/k8s/base`提供通用Kustomize配置，`deploy/k8s/kind`用于本地三逻辑节点演练。部署前需要在目标
Namespace创建`financial-agent-secrets`，再执行：

```bash
kubectl apply -k deploy/k8s/kind
kubectl -n financial-agent wait --for=condition=complete job/db-migrate --timeout=300s
kubectl -n financial-agent rollout status deployment/job-api --timeout=300s
kubectl -n financial-agent rollout status deployment/job-worker --timeout=300s
kubectl -n financial-agent rollout status deployment/backend-gateway --timeout=300s
```
