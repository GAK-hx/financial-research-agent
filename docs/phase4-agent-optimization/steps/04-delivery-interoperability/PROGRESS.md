# Step 04 进度：多租户并发、交付与互操作

- 状态：`TECHNICAL_GO_WITH_CAPACITY_BOUNDARY`
- 前置条件：Step 03 Gate 通过
- 计划审核：已确认
- 实现开始：2026-08-08
- Gate 结论：技术实现通过；GitHub 发布仍受 Key 轮换与许可确认阻断

## 范围决定

- [x] MCP 保持可选；当前只统一 Tool Schema/元数据，不实现无消费者的协议服务器；
- [x] 薄 UI 使用 FastAPI 内嵌单页，不增加前端构建链；
- [ ] GitHub 最终私有或公开策略；
- [ ] 允许随仓库分发的样例数据和报告清单。
- [x] 真实 Flash 仅执行两条 Planner 并发调用，不外发本地 Evidence。

## 已确认设计

- [x] 多租户并发查询优化纳入 Step 04，不新增独立 Step；
- [x] 区分应用服务层并发与托管模型推理层并发；
- [x] 第一版继续使用 PostgreSQL Queue、Lease 和 Checkpoint；
- [x] 先做冻结负载基准，达到升级条件后才评估 Redis/Celery；
- [x] 验收必须覆盖租户隔离、三级限额、公平调度、背压和分层延迟指标。

## 已完成实现

- [x] 请求体身份字段禁用，建立 `local`/`api_key` 两种可信身份模式；
- [x] Run/Result/Event/Trace/取消/恢复/Memory 按租户和用户隔离；
- [x] 全局、租户、用户排队与运行限额，以及结构化 `429` 背压；
- [x] 交互优先、租户轮转、公平领取和租户作用域幂等；
- [x] Worker 有界并发、可配置数据库池和共享 Provider 限流窗口；
- [x] 分层延迟、准入、队列年龄和 Worker 指标；
- [x] `/demo` 复用正式 Job/Event/Result API；
- [x] 1/10/30/50 VU 冻结基准：91 个 Run，关键不变量均为 0；
- [x] Flash Planner 并发 2/2；
- [x] 完整 PostgreSQL/Compose 回归 168/168；
- [x] 生成架构、运行手册、并发、MCP 决策、失败记录、证据和 Gate 文档。

## 发布前仍需用户关闭

- [ ] 在 DeepSeek 控制台轮换历史对话中出现过的 Key；
- [ ] 决定 GitHub 私有/公开策略与数据、报告、PDF 的许可范围；
- [ ] 如未来出现真实 MCP 消费者，再实现并单独验证 Streamable HTTP Adapter。
