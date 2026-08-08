# Step 03 运行手册

## 1. 构建和运行因子批任务

```bash
docker compose build factor-batch
docker compose --profile analysis run --rm factor-batch
```

指定股票池或观察日：

```bash
docker compose --profile analysis run --rm factor-batch \
  python -m financial_research_agent.analysis.cli \
  --universe demo_liquid_a_share --as-of 2026-07-14
```

批任务只写版本化分析结果；在线 API 不临时启动 Spark。

## 2. 部署 API 和异步后端

```bash
docker compose build app job-api job-worker
docker compose --profile harness up -d app job-api job-worker
docker compose --profile harness ps
```

模型配置继续放在未提交的 `.env`；默认 `MODEL_NAME=deepseek-v4-flash`。当前不稳定网络默认使用 75 秒
超时、4 次重试、3 秒初始退避和 20 秒最大退避。

## 3. 分析请求样例

```bash
curl -sS -H 'Content-Type: application/json' \
  -d '{"question":"分析贵州茅台最近一年技术面和动量"}' \
  http://localhost:8000/analyze
```

事件受控补充样例：

```bash
curl -sS -H 'Content-Type: application/json' \
  -d '{"question":"请分析贵州茅台最近一年的事件影响，重点关注渠道改革，并给出四维风险向量和乐观、基准、压力三种情景。"}' \
  http://localhost:8000/analyze
```

响应中重点检查：`selected_skills`、`tool_status`、`evidence`、`report.validation`、`budget.replan`、
`completion` 和 `context_manifests`。

## 4. 集中回归

```bash
docker compose run --rm app \
  python -m unittest discover -s tests -v
```

PostgreSQL 集成路径：

```bash
docker compose run --rm -e RUN_POSTGRES_TESTS=1 app \
  python -m unittest tests.test_governance tests.test_persistence \
  tests.test_skills tests.test_memory_context tests.test_jobs -v
```

## 5. 数据边界检查

- 不把演示股票池称为指数成分；
- 不把 `missing` 股票加入有效排名；
- 不把非 PIT 财务因子用于历史回测；
- 不把本地 Event 样例称为实时新闻；
- 不提交 `.env`、API Key、完整私有报告或原始模型响应。
