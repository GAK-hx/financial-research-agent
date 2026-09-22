# 本地开发与Docker

## 配置

```bash
cp .env.example .env
```

`.env.example`只提供字段结构。真实模型Key、数据库口令、Redis口令和加密Key只能写入未跟踪的`.env`或
Secret Manager。

最低模型配置：

```dotenv
MODEL_PROVIDER=openai_compatible
MODEL_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-flash
MODEL_API_KEY=
```

## 启动

```bash
docker compose --profile harness up -d \
  postgres etcd milvus db-migrate job-api job-worker
```

可选Gateway与Redis：

```bash
docker compose --profile harness --profile concurrency --profile gateway \
  up -d redis backend-gateway
```

FastAPI开发入口为`http://localhost:8002`，Gateway入口为`http://localhost:8080/api/v1`。

## 数据任务

```bash
docker compose --profile ingestion run --rm data-bootstrap
docker compose --profile ingestion run --rm market-ingest
docker compose --profile ingestion run --rm financial-ingest
docker compose --profile analysis run --rm factor-batch
```

## 验证

```bash
bash scripts/secret_scan.sh
.venv/bin/ruff check src tests
IDENTITY_MODE=local PYTHONPATH=src \
  .venv/bin/python -m unittest discover -s tests -q
docker compose config --quiet
```
