# Step 04 Gate 报告

- 日期：2026-08-08
- 结论：`TECHNICAL_GO_WITH_CAPACITY_BOUNDARY`
- 默认模型：`deepseek-v4-flash`

## Gate 结果

| Gate | 结果 | 证据 |
|---|---|---|
| 可信身份边界 | 通过 | 请求体不能声明租户/用户；API Key 模式从认证头生成身份 |
| 租户隔离 | 通过 | Run、Result、Event、Trace、取消、恢复和 Memory 都按可信身份过滤 |
| 三级背压 | 通过 | 全局、租户、用户排队与运行上限；过载返回 `429` 和 `Retry-After` |
| 公平调度 | 通过 | 交互优先；同优先级按租户轮转；领取事务检查运行配额 |
| Worker 与 Provider 边界 | 通过 | 有界 Worker Slot、PostgreSQL 连接池、模型 Semaphore、跨进程分钟窗口 |
| 冻结并发基准 | 通过 | 1/10/30/50 VU，共 91 个 Run；四项关键不变量均为 0 |
| 真实 Flash Planner | 通过 | 两条并发结构化 Planner 请求 2/2 通过，不携带本地 Evidence |
| 完整 Docker/PostgreSQL 回归 | 通过 | 168/168；可重复记忆接口测试使用真实认证身份范围 |
| 离线回归与静态检查 | 通过 | 145 通过/23 跳过；`uvx ruff` 通过 |
| 薄演示界面 | 通过 | `/demo` 复用正式 Job、Event 和 Result API，无第二套业务逻辑 |
| MCP | 延后 | 复用 Tool Schema 和只读元数据，但没有外部消费者，因此未实现协议服务器 |
| Docker 交付 | 通过 | App/Job API 健康，Demo/指标返回 200，Worker 以 2 Slot 启动 |
| Secret 扫描 | 通过 | 当前 Git 候选文件通过仓库扫描脚本 |
| GitHub 发布 | 阻断 | 历史对话中暴露过 Key，推送前必须轮换，并决定许可/公开范围 |

## 容量结论

当前单实例适合耗时较长、吞吐中等的研究任务。冻结 Stub 在 30 个同时提交时吞吐约
17.5 次/秒；到 50 个同时提交时，准入 P95 约 1.79 秒、排队 P95 约 2.11 秒，吞吐下降。
因此推荐演示容量是约 30 个同时提交的请求，而不是 30 个同时调用模型，也不是高 QPS SLA。

严格全局准入计数当前使用 PostgreSQL 事务锁。它保证配额不被竞态突破，但会串行化短暂的
入队临界区。只有业务目标超过该容量时，才值得把计数升级为原子 Counter/Lease 表，并在
新的冻结基准下决定是否引入 Redis/Celery。

## 允许交付的范围

- 可以演示 LangChain + LangGraph 正式链路、异步 Job、SSE/事件、取消恢复和受控分析；
- 可以演示多租户准入、身份隔离、公平调度、过载响应和可观察的分层延迟；
- 可以把 Tool Schema 作为未来 MCP/其他协议适配的共享边界；
- 不能宣称分钟级实时、高频、自动交易、生产级认证或大规模在线推理；
- 不能把本机 Stub 压测解释为云生产 SLA；
- 未轮换历史 Key、完成许可核对前，不进入 GitHub 发布。

## 非阻塞技术债

- `api_key` 只是演示级认证；生产应接 OIDC/API Gateway，并由网关签发可信身份；
- Provider 共享窗口是保守的固定分钟窗口，不等同于 DeepSeek 的精确动态配额；
- FastAPI `on_event` 和旧 TestClient 兼容层存在上游弃用警告；
- 准入审计、Provider 限流和数据库池等待可继续接入 OpenTelemetry/Prometheus；
- MCP 仅保留兼容边界，尚未形成可对外承诺的集成功能。
