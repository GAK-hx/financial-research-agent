# Step 08.2 Spring Gateway 运行手册

## 组件边界

对外请求只进入 Spring Gateway。Gateway 负责认证、可信身份、幂等入口、Redis 限流、请求追踪和
WebFlux/SSE 代理；LangChain Tool、LangGraph、Skill、Context、Memory、Evidence、模型调用和报告继续在
Python 内执行。

## 必要配置

本地 `.env` 至少包含：

```dotenv
IDENTITY_MODE=api_key
AGENT_API_KEY=<internal-python-key>
REDIS_ENABLED=true
REDIS_PASSWORD=<private-password>
GATEWAY_EXTERNAL_API_KEY=<external-client-key>
```

建议内外 key 使用不同值。若 `GATEWAY_EXTERNAL_API_KEY` 为空，开发环境会回退使用 `AGENT_API_KEY`；
生产环境不建议依赖该回退。

多 API key 可使用：

```dotenv
GATEWAY_API_CLIENTS=key-a|tenant-a|user-a|researcher;key-b|tenant-b|user-b|admin
```

启用 JWT 时配置 JWK Set URI：

```dotenv
GATEWAY_JWT_JWK_SET_URI=https://identity.example.com/.well-known/jwks.json
```

JWT 必须包含 `sub` 和 `tenant_id`；角色 claim 默认为 `role`。不配置 URI 时不会创建 JWT decoder。

## 开发启动

```bash
docker compose --profile gateway --profile concurrency --profile harness \
  up -d backend-gateway
```

开发入口：`http://localhost:8080`。`job-api:8000` 是 Compose 内部上游；基础 Compose 仍保留调试端口。

## 生产端口边界

```bash
docker compose -f docker-compose.yml -f docker-compose.gateway.yml \
  --profile gateway --profile concurrency --profile harness up -d
```

`docker-compose.gateway.yml` 清除 Python API、Redis、Elasticsearch 和 Milvus 的宿主机端口，只保留
Gateway `8080`。这只是单机生产形态；TLS 应由反向代理或云负载均衡终止。

## 调用示例

```bash
curl -H "Authorization: Bearer $GATEWAY_EXTERNAL_API_KEY" \
  http://localhost:8080/api/v1/health
```

```bash
curl -X POST http://localhost:8080/api/v1/runs \
  -H "Authorization: Bearer $GATEWAY_EXTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: client-request-001" \
  --data '{"question":"分析贵州茅台 600519 的基本面风险"}'
```

```bash
curl -N -H "Authorization: Bearer $GATEWAY_EXTERNAL_API_KEY" \
  -H "Last-Event-ID: 0" \
  http://localhost:8080/api/v1/runs/<run_id>/events
```

外部提交的 `X-Tenant-ID`、`X-User-ID` 和 `X-Agent-Role` 会被删除，身份只来自已配置 API client 或
JWT。`X-Request-ID` 只接受 1～128 位字母、数字、点、下划线和短横线；无效值由 Gateway 重新生成。

## 健康与指标

- `/actuator/health/readiness`：进程是否可以继续承接只读/状态/SSE 流量；
- `/actuator/health`：包括 Redis 在内的总体组件健康；
- `/actuator/prometheus`：Micrometer Prometheus 指标；
- `/api/v1/health`：Python Agent 数据、模型和依赖健康。

Redis 停机时总体 health 返回 `503 DOWN`，readiness 仍为 `UP`，已有 Job 读取/SSE 可继续；新建分析
返回结构化 `503 RATE_LIMIT_BACKEND_UNAVAILABLE` 和 `Retry-After: 1`。

## 限流配置

```dotenv
GATEWAY_RATE_LIMIT_REPLENISH_RATE=5
GATEWAY_RATE_LIMIT_BURST_CAPACITY=10
GATEWAY_RATE_LIMIT_REQUESTED_TOKENS=1
```

Key 使用 `SHA-256(tenant + user + endpoint)`，Redis key 不暴露身份原文。限流仅作用于 `POST /runs`
和 `POST /analyze`；查询、取消、恢复和 SSE 依赖 PostgreSQL 可靠状态，不因限流 Redis 故障被阻断。

## 停止

```bash
docker compose --profile gateway --profile concurrency --profile harness \
  stop backend-gateway
```

不要用 Redis 数据恢复 Job、Evidence、报告或记忆；这些可靠状态仍以 PostgreSQL/Iceberg 为准。
