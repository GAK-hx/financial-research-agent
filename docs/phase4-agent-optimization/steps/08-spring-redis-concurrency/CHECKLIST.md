# Step 08 实现清单

## 08.1 Redis 共享热状态

- [x] 增加 Redis 容器、健康检查、认证和资源限制
- [x] 定义 versioned、tenant-safe key schema 和 TTL
- [x] 实现 tenant/user/endpoint token bucket
- [x] 实现分布式并发槽位
- [x] 实现 idempotency -> run_id 热映射
- [x] 实现 RetrievalSnapshot/AnalysisArtifact metadata L1 cache
- [x] 实现事件通知和 PostgreSQL replay fallback
- [x] Redis 不可用时不丢任务、不绕过 PostgreSQL 最终判定
- [x] 完成最小可行性测试并更新进度

## 08.2 Spring Boot 接入层

- [x] 建立 Java 21 / Maven / Spring Boot 4.1 模块
- [x] 使用 Docker 多阶段构建，宿主机不依赖 Maven/JDK 21
- [x] 接入 Spring Cloud Gateway WebFlux
- [x] 接入 Spring Security API key/JWT 边界
- [x] 阻止外部伪造内部 tenant/user 头
- [x] 接入 Reactive Redis rate limiter
- [x] 透传 trace 和 idempotency；网关限制上游响应时间，执行预算仍由 Python Harness 管理
- [x] 代理 analyze/run/cancel/resume/trace/skills/metrics API
- [x] 代理 SSE 并支持 Last-Event-ID 重连
- [x] 增加 Actuator health/readiness 和 Micrometer 指标
- [x] 生产 profile 只暴露 Spring 端口
- [x] 完成认证、身份、限流、SSE、Redis 故障恢复和全量回归并更新进度

## 08.3 集中 Gate

- [x] 5 用户 × 4～5 股票交叉查询
- [x] 20～50 个同时提交请求
- [x] 相同 idempotency key 只产生一个 run
- [x] 相同原子检索只产生一个共享工作（Step 07 Gate 证明，Step 08 全量回归防回退）
- [x] tenant/user 配额与 429 正确
- [x] 最终报告和用户记忆不跨租户共享
- [x] Redis 重启后 PostgreSQL 完整恢复
- [x] Spring 重启后 API/SSE 可重连
- [x] Worker 重启后租约接管且无重复终态
- [x] Python 全量回归、Java 测试和 Compose 集成 Gate
- [x] 将原始并发指标和失败输出保存为 Markdown
- [x] 组件稳定后更新面向读者的组件化README
