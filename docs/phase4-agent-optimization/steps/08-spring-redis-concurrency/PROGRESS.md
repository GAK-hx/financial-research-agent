# Step 08 进度

## 当前状态

- 状态：`STEP_08_COMPLETE`
- 当前任务：Step 08及组件化README已完成，下一步执行发布前密钥/仓库检查
- 默认模型：`deepseek-flash`
- 是否开始编码：是，08.1 已完成

## 已确定

- [x] Spring 是对外接入层，不承载 Agent 业务逻辑
- [x] Redis 是热状态和协同层，不是可靠事实库
- [x] Python 保留 LangGraph、Tool、Skill、模型和 Worker
- [x] PostgreSQL 保留 Job、租约、审计、版本和最终 single-flight
- [x] 实现压缩为 Redis、Spring、集中 Gate 三个部分
- [x] 不增加 Kafka、Nacos、Sentinel、Eureka 或第二套业务数据库

## 待实施

- [x] 08.1 Redis 共享热状态
- [x] 08.2 Spring Boot 接入层
- [x] 08.3 集中并发与故障恢复 Gate
- [x] 面向读者的组件化README

## 08.1 实施结果

- [x] Redis 8.4 Alpine 可选容器、密码、健康检查和 256 MB 容器上限
- [x] redis-py 8.0.1 异步客户端和显式连接关闭
- [x] SHA-256 key schema，不在 Redis key 中暴露 tenant/user/idempotency 原文
- [x] Lua token bucket 和带租约的分布式并发槽位
- [x] `idempotency -> run_id/request_hash` 短 TTL 热映射
- [x] RetrievalSnapshot/AnalysisArtifact metadata L1 cache
- [x] Job Pub/Sub 唤醒和最后事件短 TTL marker
- [x] PostgreSQL 最终幂等、single-flight、Job/Event 和恢复逻辑保持不变
- [x] Redis 停机时显式 degraded，并成功从 PostgreSQL 创建、读取和取消 Job
- [x] 真实 Redis Gate、20 路 API 幂等 Gate和全量回归通过

## 08.2 实施结果

- [x] Java 21、Spring Boot 4.1、Spring Cloud Gateway 5.0.2 独立模块
- [x] Maven/JDK 21 builder 到非 root JRE 21 runtime 的 Docker 多阶段构建
- [x] API key registry 与可选 JWK JWT 身份解析，支持 tenant/user/role
- [x] 移除外部伪造身份头，由网关写入内部固定身份和内部 API key
- [x] request ID、Idempotency-Key、固定上游超时与结构化认证错误
- [x] 仅对昂贵的新分析请求应用 Redis token bucket，读/取消/SSE 不依赖限流 Redis
- [x] 覆盖 Spring RedisRateLimiter 默认故障放行行为，Redis 异常时新建请求结构化 503
- [x] Python Job API、取消、trace、skill、metrics 与 SSE 非阻塞代理
- [x] Actuator health/readiness/Prometheus，Redis 故障总体 health DOWN、readiness 保持只读可用
- [x] 生产 Compose override 仅暴露 Spring 端口
- [x] 认证、身份防伪、幂等、15 路限流、SSE、Redis 停机/恢复和全量回归通过

## 08.3 实施结果

- [x] 5 用户各 5 个任务，25 路并发提交，覆盖 17 支且包含交叉标的
- [x] 25/25 接收、25/25 幂等重放复用原 run、身份映射错误 0
- [x] 同租户跨用户和跨租户读取均为 404
- [x] 单用户 15 路突发得到 10 个 202 和 5 个 429
- [x] 1/10/30/50 VU 冻结公平队列共 91 个任务，丢失/重复终态/泄漏/模型调用均为 0
- [x] Redis 与 Spring 重启后，Worker 过期租约从 attempt 1 接管为 attempt 2
- [x] SSE 使用 Last-Event-ID 从持久化事件 2 续传到唯一终态
- [x] DeepSeek V4 Flash 最终 2/2 端到端通过
- [x] 修正时间窗口与最大回撤幅度的数值校验误判，保留普通下降方向检查
- [x] Python 187 项（24 跳过）全部非跳过通过，Java 3 项通过
- [x] 临时测试身份已撤销，正常 Gateway 配置与正式 Worker 已恢复

## 进度记录

| 日期 | 状态 | 记录 |
|---|---|---|
| 2026-08-16 | PLANNED | 完成 Spring + Redis 职责边界、三部分实施计划和 Gate 设计 |
| 2026-08-16 | STEP_08_1_COMPLETE | Redis 热状态、原子并发原语、真实容器与降级 Gate 完成 |
| 2026-08-16 | STEP_08_2_COMPLETE | Spring Gateway、安全边界、限流、SSE、Redis 失败关闭与恢复 Gate 完成 |
| 2026-08-16 | STEP_08_COMPLETE | 5 用户/25 任务、50 VU、公平队列、组件重启、SSE 续传和 Flash Gate 完成 |
| 2026-09-22 | DOCUMENTATION_COMPLETE | 根README改为组件化项目说明，并纳入企业财务风险Benchmark与Kubernetes运行结果 |
