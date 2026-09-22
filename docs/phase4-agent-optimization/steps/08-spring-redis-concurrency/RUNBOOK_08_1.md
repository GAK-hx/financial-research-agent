# Step 08.1 Redis 运行手册

## 启动

```bash
docker compose --profile concurrency up -d redis
```

使用完整 Job 服务：

```bash
docker compose --profile concurrency --profile harness up -d \
  redis app job-api job-worker
```

本地 `.env` 至少配置：

```dotenv
REDIS_ENABLED=true
REDIS_URL=redis://redis:6379/0
REDIS_PASSWORD=<private-password>
REDIS_KEY_PREFIX=financial-agent
```

密码不写入受版本控制文件。`.env.example` 中的值只适用于本地开发。

## 检查

API `/health` 应包含：

```json
{"redis": {"status": "ready", "detail": null}}
```

`/metrics` 中可查看：

- Redis 是否启用；
- 操作数和错误数；
- metadata hit/miss。

## 故障行为

- Redis 不可用时 `/health` 为 `degraded`；
- Job 创建、读取、取消和恢复仍回源 PostgreSQL；
- metadata miss 回源 PostgreSQL/Elasticsearch；
- Pub/Sub 丢失时 SSE 继续轮询和回放 PostgreSQL Event；
- 不要从 Redis 手工恢复 Job 或最终报告。

## 清理测试数据

真实集成测试使用 Redis DB 15，并在测试前后执行 `flushdb`，不会清理业务 DB 0。

## 安全

- 生产环境替换默认密码；
- 不把 Redis 端口直接暴露到公网；
- Spring 上线后由 Gateway 成为唯一公网入口；
- GitHub 发布前继续排除 `.env` 并执行 secret scan。
