# Step 08.3 并发与恢复 Gate 运行手册

## 目的

本手册只用于重复执行 Step 08.3 验收。默认把高并发调度测试与真实模型测试分开：前者冻结模型，
后者只运行少量 `deepseek-v4-flash` 查询。

## 前置服务

```bash
docker compose --profile harness --profile concurrency --profile gateway \
  up -d postgres redis job-api job-worker backend-gateway
```

确认 Gateway、Job API、Redis、PostgreSQL healthy，Worker 为 running。不要在文档或命令历史中写入真实
DeepSeek key；模型密钥继续从本地 `.env` 注入。

## 1. 多用户接入 Gate

先暂停 Worker，避免 25 个接入任务触发模型：

```bash
docker compose --profile harness stop job-worker
```

临时为 Gateway 设置 5 个非敏感 Gate client，格式为：

```text
key|tenant|user|role;key|tenant|user|role
```

使配置与 `scripts/step8_gateway_multiuser_gate.py` 中的 Gate-only client 一致后，重新创建 Gateway，执行：

```bash
python scripts/step8_gateway_multiuser_gate.py
```

通过标准：25/25 接收、身份错误 0、幂等错误 0、跨用户/跨租户均 404、突发 15 请求同时出现 202 和
429、25 个任务全部取消。脚本不会把凭据写入产物。

## 2. 冻结公平队列 Gate

```bash
docker compose --profile harness run --rm --no-deps \
  -v "$PWD/scripts:/app/scripts:ro" \
  job-worker python /app/scripts/step4_concurrency_gate.py
```

通过标准：1/10/30/50 VU 全部完成，`lost_runs`、`duplicate_terminal`、`cross_tenant_leaks` 和
`provider_calls` 均为 0。

## 3. Worker 崩溃与 SSE 恢复

通过 Gateway 创建一个专用测试 Job，记录 run_id。生产 Worker 必须保持停止。第一次运行：

```bash
docker compose --profile harness run --rm --no-deps \
  -v "$PWD/scripts:/app/scripts:ro" \
  job-worker python /app/scripts/step8_frozen_worker.py \
  claim-and-exit --run-id <run_id>
```

读取事件并记录最后 event_id，然后重启 Redis 和 Spring Gateway。等待 30 秒租约过期，执行：

```bash
docker compose --profile harness run --rm --no-deps \
  -v "$PWD/scripts:/app/scripts:ro" \
  job-worker python /app/scripts/step8_frozen_worker.py \
  recover-one --run-id <run_id>
```

用 `Last-Event-ID` 重连 `/api/v1/runs/<run_id>/events`。通过标准：出现 `job_reclaimed`，attempt 为 2，
只有一个 `job_terminal`，最终 completed，trace 中 model/tool 都是 0。

## 4. 少量 Flash 端到端

恢复正式 Worker，确认容器内 `MODEL_NAME=deepseek-v4-flash`，再执行：

```bash
python scripts/step8_flash_e2e_gate.py
```

只复测一个失败案例时：

```bash
STEP8_FLASH_CASES=single_technical \
STEP8_FLASH_ARTIFACT_BASENAME=flash_e2e_retest \
python scripts/step8_flash_e2e_gate.py
```

失败时脚本会把完整 Job、Result、Event 和 Trace 写入 `artifacts/step8/*.json`，并把失败原文附在同名
Markdown 中。先区分网络/Provider、数据缺失、模型偶发格式与代码缺陷，不要机械降低校验阈值。

## 5. 集中回归

```bash
IDENTITY_MODE=local PYTHONPATH=src \
  .venv/bin/python -m unittest discover -s tests -q
```

Gateway 使用 Docker 中的 Maven/JDK 21 构建，构建阶段会执行 Java 测试：

```bash
docker build backend-gateway
```

## 6. 恢复正常配置

Gate 结束后必须：

1. 不带临时 `GATEWAY_API_CLIENTS` 重建 Gateway；
2. 启动正式 Worker；
3. 确认 Gateway、Job API、Redis、PostgreSQL healthy；
4. 确认没有 queued/running 的 Step 08 Gate 任务；
5. 保持仓库私有，不上传 `.env` 或任何模型/API/SSH 私钥。
