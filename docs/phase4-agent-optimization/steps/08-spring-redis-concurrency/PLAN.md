# Step 08：Spring + Redis 多用户并发接入层

> 状态：`STEP_08_COMPLETE`
> 原则：不重写已跑通的 Python Agent，不让 Redis 取代 PostgreSQL 的可靠状态

## 1. 目标

在现有 FastAPI、LangGraph、PostgreSQL Job/租约和检索 single-flight 之上，增加企业常见的多用户接入层：

1. Spring Boot 对外提供统一 API、身份认证、租户隔离、限流、幂等入口和 SSE 转发；
2. Redis 保存短生命周期的共享热状态，降低多实例下的数据库争用和重复外部调用；
3. Python 服务继续负责问题理解、Agent 编排、Tool、Skill、Evidence、分析和报告；
4. PostgreSQL 继续作为任务、租约、审计、缓存版本和恢复状态的唯一可靠事实来源。

该 Step 解决的是高并发接入和跨实例协同，不是把业务逻辑从 Python 搬到 Java。

## 2. 技术选择

- Java 21；
- Spring Boot 4.1；
- Spring Cloud 2025.1 / Gateway WebFlux；
- Spring Security；
- Spring Data Redis Reactive；
- Redis 单节点容器，开发环境持久化关闭或使用轻量 AOF；
- Maven；
- Python 侧使用异步 Redis client，通过统一接口提供无 Redis 降级。

Spring Boot 4.1 官方要求至少 Java 17；Spring Cloud 2025.1.x 与 Boot 4.0/4.1 兼容。选择 Java 21 是为了
兼顾长期支持、企业常见度和本地资源消耗。

Spring 模块使用 Docker 多阶段构建：Maven + JDK 21 只存在于 builder stage，运行镜像只保留 JRE 21。
宿主机无需安装 Maven 或切换当前 Java 19；Compose 只增加 Redis 和 Spring Gateway 两个可选服务。

## 3. 组件边界

### Spring 接入层负责

- 对外暴露 `/api/v1/analyze`、`/api/v1/runs/**` 和 SSE；
- 校验 JWT/API key，将可信 tenant/user 写入内部签名身份头；
- 拒绝客户端伪造内部身份头；
- 基于 tenant、user、endpoint 和请求成本执行 Redis token bucket；
- 生成/透传 trace ID、idempotency key 和超时预算；
- 将请求非阻塞转发到内部 Python Job API；
- 对短时重复的状态查询使用 Redis L1 cache；
- 暴露 Actuator 健康和 Micrometer 指标。

### Redis 负责

- 分布式接入限流和并发槽位；
- `idempotency key -> run_id` 的短 TTL 热映射；
- `atomic query key -> snapshot/artifact metadata` 的短 TTL L1 索引；
- Job 新事件的轻量通知，帮助 SSE 减少 PostgreSQL 轮询；
- 短时健康、配置版本和负载信息。

Redis 不保存最终报告、用户长期记忆、完整 Evidence、任务唯一终态或不可恢复的队列数据。

### Python Agent 负责

- LangChain Tool 与 LangGraph 状态编排；
- Harness、预算、Provider 限流和 Tool 参数治理；
- 股票/研报/网络/财务/因子取数和分析；
- Context、Memory、Skill、Evidence、报告校验；
- PostgreSQL Job 领取、租约、恢复和最终写入；
- Redis L1 miss 后回源 PostgreSQL/Elasticsearch。

### PostgreSQL 继续负责

- Job、Event、租约、幂等终态和审计；
- RetrievalSnapshot、AnalysisArtifact 及依赖版本；
- Redis 故障后的完整恢复；
- 对共享外部工作的最终 single-flight 判定。

## 4. 为什么保留 PostgreSQL single-flight

现有检索和任务协调已经用唯一键、事务锁、租约与幂等完成保证正确性。若直接换成 Redis 锁：

- 锁过期和执行时长不一致时可能产生重复模型调用；
- Redis 故障或淘汰可能丢失任务归属；
- 需要重新证明 Worker 崩溃恢复和最终状态唯一性。

因此 Redis 只做快速候选判断和热点合并；真正开始外部 Tool/模型调用前，仍由 PostgreSQL 做最终判定。

## 5. 请求流程

```text
Client
  -> Spring Gateway
       auth / tenant / trace / Redis rate limit
       idempotency hot lookup
  -> Python Job API
       PostgreSQL idempotency + enqueue
  -> Python Worker
       Redis L1 snapshot lookup
       PostgreSQL single-flight + lease
       LangGraph / Tool / Skill / model
       PostgreSQL durable commit
       Redis cache update + event notification
  -> Spring SSE
       live notification + Python/PostgreSQL replay fallback
  -> Client
```

## 6. 失败与降级

| 故障 | 行为 |
|---|---|
| Redis 不可用 | 不丢任务；清除 L1 优势并回源 PostgreSQL；昂贵新请求按策略限流或暂时拒绝 |
| Spring 重启 | 客户端凭 run_id 重连；SSE 从持久化事件位置继续 |
| Python API 不可用 | Gateway 返回结构化 503，不在 Java 内生成伪结果 |
| Worker 崩溃 | PostgreSQL 租约到期后由其他 Worker 接管 |
| 重复请求 | Redis 快速命中，PostgreSQL 幂等键做最终确认 |
| SSE 通知丢失 | 定期回源持久化事件；通知只负责唤醒，不承担可靠存储 |

## 7. 三个实现部分

### 08.1 Redis 共享热状态

- 增加 Redis Docker 服务、healthcheck、密码注入和内存上限；
- 定义带 namespace/version/tenant 的 key schema；
- 实现 token bucket、并发槽位、幂等热映射和 L1 metadata cache；
- Python 增加 Redis adapter，保持 PostgreSQL fallback；
- 任务落库成功后再更新 Redis，避免缓存领先于事实状态。

只做最小测试：原子限流、TTL、租户隔离和 Redis unavailable fallback。

### 08.2 Spring Boot 接入层

- 新建独立 `backend-gateway` 模块；
- 增加 Maven/JDK 21 -> JRE 21 的 Docker 多阶段构建；
- 接入 Spring Cloud Gateway WebFlux、Security、Reactive Redis 和 Actuator；
- 实现可信身份头、API key/JWT、trace、idempotency 和 Redis 限流；
- 代理 Python Job API 与 SSE，保持现有响应 schema；
- Docker Compose 中 Python API 改为内部服务，Spring 成为生产 profile 的唯一公网入口。

只做最小测试：认证、429、身份头防伪、API 转发和一次 SSE。

### 08.3 集中并发 Gate

- 5 个用户，每人查询 4～5 只股票，包含交叉标的；
- 增加 20～50 个同时提交请求的短压测；
- 验证重复 idempotency key 只有一个 run；
- 验证交叉股票仍只产生一个共享检索工作；
- 验证 tenant/user 限流、公平性、队列背压和 429；
- 验证 Redis、Spring、Worker 分别重启后的恢复；
- 最后统一执行 Python、Java 和 Docker 集成回归并集中修正。

## 8. 完成标准

- 公网请求只经过 Spring，Python Agent API 在生产 profile 不直接暴露；
- 多个 Spring/Python 实例共享同一套限流和热缓存；
- Redis 故障不会丢失任务、最终结果或用户记忆；
- PostgreSQL 仍能证明一个幂等请求只有一个终态；
- 交叉查询不会增加重复 Tool/模型副作用；
- SSE 可以重连和回放，不依赖瞬时 Pub/Sub 消息完整性；
- 指标能区分 Gateway 拒绝、Redis 命中、PostgreSQL 回源、队列等待和模型执行时间。

## 9. 明确不做

- 不在 Spring 中复制 LangGraph、Tool、Skill 或报告逻辑；
- 不同时维护两套对外业务 API schema；
- 不用 Redis Pub/Sub 代替可靠 Job 队列；
- 不用 Redis 分布式锁取代 PostgreSQL 最终 single-flight；
- 不缓存跨用户最终文本；
- 暂不引入 Kafka、Nacos、Sentinel、Eureka、MySQL 或 Kubernetes。

## 10. 外部依据

- Spring Boot 4.1 要求 Java 17～26；
- Spring Cloud 2025.1.x 对应 Spring Boot 4.0/4.1；
- Spring Cloud Gateway WebFlux 支持基于 Redis 的 token bucket；
- WebFlux 为非阻塞模型并支持 Reactive Streams 背压；
- Redis 官方建议在跨实例 API 配额场景使用原子计数/Lua token bucket；
- Redis Streams 有持久消费能力，但本项目已有 PostgreSQL Job/Event，因此初版只把 Redis 用作热路径和通知层。

Spring 官方兼容矩阵已于 2026-08-16 复核：Spring Cloud `2025.1.2` 开始支持 Spring Boot `4.1.x`。

## 11. 当前实施进度

- 08.1 Redis 共享热状态：完成；
- 08.2 Spring Boot 接入层：完成；
- 08.3 5 用户交叉股票查询、50 路上限、Spring/Redis/Worker 重启恢复及 Flash 端到端 Gate：完成。

详细结果见 `GATE_REPORT_08_3.md`，复现方式见 `RUNBOOK_08_3.md`。
