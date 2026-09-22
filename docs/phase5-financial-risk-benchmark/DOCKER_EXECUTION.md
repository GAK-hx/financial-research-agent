# Step 01 Docker 执行说明

## 隔离边界

`risk-step01` 是第五阶段的离线数据与评测容器，不启动 Agent API，也不读取 `.env`。容器只获得：

- 镜像内 `/app` 的项目代码；
- 可写的 `/artifacts` 主机目录，用于断点、原始快照、Iceberg 与报告；
- 临时的 `/tmp`；
- 外部数据源所需的出站网络。

根文件系统只读，全部 Linux capabilities 被移除，并启用 `no-new-privileges`。默认限制为 2 CPU、
1400 MiB 内存和 256 个进程。Step 01 不需要 PostgreSQL、Milvus、Redis、Elasticsearch 或模型 API。

主镜像负责财务数据、PIT 特征、Benchmark 和基线；官方 PDF 内容解析沿用已具备相应解析能力的
`risk-step01-cached-eval` 评测容器。当前阶段不为合并依赖重复构建镜像，Step 03 再按采集、评测、
API 和 Worker 职责正式拆分。

## 构建与最小检查

```bash
docker compose --profile risk build risk-step01
docker compose --profile risk run --rm risk-step01
```

如果 Docker Hub 暂时不可用，但本机已有本项目的 `financial-ingest` 和 `job-api` 镜像，可以使用缓存模式：

```bash
docker compose --profile risk-cached run --rm risk-step01-cached-ingest
docker compose --profile risk-cached run --rm risk-step01-cached-eval
```

缓存模式仍在容器内运行，`src/` 和 `tests/` 只读挂载；它用于开发续跑，不替代网络恢复后的正式镜像固化。

## 从主机检查点续跑 100 家扩展池

```bash
docker compose --profile risk-cached run --rm risk-step01-cached-ingest \
  python -m financial_research_agent.risk.pool_ingestion \
  --root /artifacts/phase5_step01/expansion_statements_v1 \
  --pool-file /artifacts/phase5_step01/expansion_pool_v1/expansion_pool_v1.json \
  --seed-root /artifacts/phase5_step01/correctness_pool_v1 \
  --legacy-checkpoint-akshare-version 1.18.83 \
  --workers 2 --retries 5 --initial-backoff-seconds 5 --call-timeout-seconds 120
```

每家公司只有 `result.json` 为 `success` 才会被断点复用。警告公司按三张报表分别复用成功的原始
Parquet，只重试失败报表；混合 AkShare 版本和各报表观测时间写入结果，不能把新补采的报表回填成旧时点。

## 公告池从原始快照重建

```bash
docker compose --profile risk run --rm risk-step01 \
  python -m financial_research_agent.risk.disclosure_pool_ingestion \
  --root /artifacts/phase5_step01/disclosure_pool_v1 \
  --workers 2 --retries 2 --initial-backoff-seconds 5 --call-timeout-seconds 90
```

相同映射版本直接复用结果；映射版本升级时优先从已保存的原始 Parquet 重建，不重复访问数据源。
