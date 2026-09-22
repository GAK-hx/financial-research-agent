# Step 08.2 Spring Gateway Gate 报告

## 结论

状态：`PASS`。

Java 21 Spring Gateway 已成为可选对外接入层。Python 保留完整 Agent 执行逻辑；Redis 只承担接入限流
和短期协同；PostgreSQL 继续保存 Job、Event、租约、幂等与恢复事实。

本 Gate 未调用模型，默认模型仍为 `deepseek-v4-flash`。

## 技术组件

| 组件 | 版本/用途 |
|---|---|
| Java | 21.0.11 runtime |
| Spring Boot | 4.1.0 |
| Spring Cloud | 2025.1.2 BOM / Gateway 5.0.2 |
| Spring Security | API key registry、可选 JWT、可信身份边界 |
| Spring Data Redis Reactive | Gateway token bucket |
| WebFlux/Reactor Netty | 非阻塞 API 与 SSE 代理 |
| Actuator/Micrometer | health、readiness、Prometheus |
| Docker | Maven/JDK 21 builder，非 root JRE 21 runtime |

Spring 官方项目页已复核：Spring Cloud `2025.1.2` 开始支持 Spring Boot `4.1.x`，版本组合不是通过
关闭 compatibility verifier 强行运行。

## 认证与身份 Gate

| 场景 | 结果 |
|---|---|
| readiness 无认证 | `200 UP` |
| Agent API 无认证 | `401 AUTHENTICATION_REQUIRED` |
| 合法 API key | Python `/health` `200 ready` |
| 伪造 tenant/user 头 | 下游保存为 `gateway-local/gateway-local`，伪造值未进入 Job |
| request ID | 下游透传并在响应中归一为一个值 |
| Idempotency-Key | 原值透传；缺失时由 Gateway 生成；超过 128 位返回结构化 422 |

## API、幂等与 SSE Gate

两次提交相同 payload 和 `Idempotency-Key=gateway-step-08-2-fixed`：

```text
first:  status=202 created=true
replay: status=202 created=false
same_run=true
```

暂停 Worker 后取消测试 Job，并通过 Gateway 连接 SSE：

```text
content-type=text/event-stream; charset=utf-8
event 1=job_queued
event 2=cancel_requested
final_status=cancelled
```

`Last-Event-ID` 被保留，持久事件仍由 Python/PostgreSQL 回放，Gateway 不保存第二份事件事实。

## Redis 并发限流 Gate

使用 curl 同时提交 15 个同用户、同 endpoint、同幂等键请求，配置为 burst 10、refill 5/s：

```text
202 = 10
429 = 5
```

成功请求通过 PostgreSQL 幂等入口收敛到一个 Job，后续重放返回 `created=false`。测试 Job 已取消，
Worker 在测试期间暂停，因此没有 Tool 或模型副作用。

## Redis 停机与恢复 Gate

停止 Redis 后：

```text
existing_job_read=200
new_job_create=503
error.code=RATE_LIMIT_BACKEND_UNAVAILABLE
Retry-After=1
actuator_overall_health=503 DOWN
actuator_readiness=200 UP
```

这表示已有任务、状态和 SSE 可继续回源 PostgreSQL，但昂贵的新分析不会绕过接入配额。Redis 恢复后，
Gateway 未重启即自动重连：

```text
overall_health=200
recovered_create=202
```

恢复测试 Job 随后取消，Redis 与 Worker 均恢复健康。

## 联调发现并修复的问题

### 1. WebFlux 代理链重复执行

初版把 `Mono<Void>` 的下游链直接接在 `switchIfEmpty` 前。正常响应完成也表现为空完成，导致代理链再次
执行并出现 `UnsupportedOperationException after response committed`。修复为先解析身份并生成唯一
`ServerWebExchange`，最后只调用一次 `chain.filter`；增加 Java 回归测试断言下游调用次数为 1。

### 2. Spring RedisRateLimiter 默认故障放行

Gateway 5.0.2 在 Redis Lua 超时后返回 `allowed=true, remaining=-1`。这会让 Redis 故障期间的新任务绕过
接入限流。项目增加 `FailClosedRedisRateLimiter`，识别该故障哨兵并返回结构化 503；读路径使用独立 route，
不依赖 Redis。

### 3. 测试命令环境问题

- 首次 Python 回归未设置 `PYTHONPATH=src`，27 个模块在收集阶段无法导入，没有执行业务测试；
- 第二次受到本机 `.env` 的 `IDENTITY_MODE=api_key` 影响，6 个 local API 用例返回 401；
- 最终显式使用 `IDENTITY_MODE=local PYTHONPATH=src` 后全部通过；生产容器仍为 `api_key`；
- 临时 Python `urllib` 并发脚本得到空正文 503，改用 curl 后稳定得到预期 202/429。正式并发 Gate 不使用
  该临时客户端。

## 集中回归

```text
Java Maven tests: 3 passed
Java 21 Docker package: PASS
Python unittest: 186 run, 24 skipped, all non-skipped tests passed
Compose base config: PASS
Compose production override config: PASS
git diff --check: PASS
```

Python warnings 是既有 FastAPI `on_event`、TestClient 和本机 PyArrow CPU 探测提示，不影响测试结论。

## 留给 08.3

- 5 用户 × 每人 4～5 只股票，包含交叉标的；
- 20～50 路完整查询、分析、输出分离后的端到端压力；
- tenant/user 公平性和跨租户隔离；
- Spring、Worker 重启及 SSE 重连；
- 汇总 Redis L1、PostgreSQL single-flight、队列等待与模型调用指标。
