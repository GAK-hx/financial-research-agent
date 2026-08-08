# Step 04 运行手册

## 1. 身份模式

本地开发默认：

```env
IDENTITY_MODE=local
```

多租户演示：

```env
IDENTITY_MODE=api_key
AGENT_API_KEY=<生成一个新的随机值>
```

`AGENT_API_KEY` 不能提交 Git。`api_key` 是演示级认证边界；正式部署应由 OIDC/API Gateway
完成认证，再把可信身份传给内部服务。

## 2. Docker 启动

```bash
docker compose --profile harness up --build -d \
  postgres etcd milvus app job-api job-worker
docker compose --profile harness ps
```

默认地址：

- App：`http://localhost:8000`；
- Job API：`http://localhost:8002`；
- 调试界面：`http://localhost:8002/demo`。

## 3. 多租户请求

```bash
curl -X POST http://localhost:8002/runs \
  -H "Authorization: Bearer $AGENT_API_KEY" \
  -H 'X-Tenant-ID: demo-a' \
  -H 'X-User-ID: analyst-1' \
  -H 'Idempotency-Key: demo-001' \
  -H 'Content-Type: application/json' \
  -d '{"question":"分析贵州茅台近期技术面","queue_class":"interactive"}'
```

查询、Event、取消和恢复必须继续携带同一身份头。`X-Agent-Role: admin` 只允许查看同租户用户，
不是跨租户超级管理员。

## 4. Worker 扩容和排空

单进程 Slot：

```env
JOB_WORKER_CONCURRENCY=2
```

需要第二个进程时：

```bash
docker compose --profile workers up -d job-worker-2
```

停止 Worker 会先停止领取，再等待当前 Run：

```bash
docker compose stop job-worker
```

Compose 的 `stop_grace_period` 应大于常见 Run 完成时间；超过后 Lease 到期可由其他 Worker
恢复。

## 5. 过载响应

排队超过全局、租户或用户阈值时返回：

```json
{
  "detail": {
    "code": "USER_QUEUE_LIMIT",
    "retryable": true,
    "retry_after_seconds": 5
  }
}
```

调用方应遵守 `Retry-After`，并复用原 `Idempotency-Key`，不能每次重试生成新键。

## 6. 验收命令

冻结并发 Gate 不调用模型：

```bash
python scripts/step4_concurrency_gate.py
```

Flash Gate 只发送问题、QuerySpec 和 Tool Schema，不发送本地行情、财务或研报 Evidence：

```bash
python scripts/step4_flash_gate.py
```

原始结果位于本地 `artifacts/step4/`，该目录被 Git 忽略。可分发结论记录在本 Step 文档目录的
`CONCURRENCY_GATE.md` 和 `GATE_REPORT.md`。

## 7. GitHub 边界

提交前执行：

```bash
bash scripts/secret_scan.sh
git status --short
```

`.env`、Lake、模型缓存、运行产物、第三方 PDF/研报不进入仓库。历史对话中曾出现过 API Key，
因此上传 GitHub 前仍应在 DeepSeek 控制台轮换相关 Key；本步骤不会自动创建远程仓库或推送。
