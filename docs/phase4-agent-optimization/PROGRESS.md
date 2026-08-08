# 第四阶段进度

## 当前状态

- 阶段：实施；
- 状态：`STEP_04_TECHNICAL_GO_WITH_CAPACITY_BOUNDARY`；
- 当前 Step：四个 Step 技术实现完成；GitHub 发布 Gate 待用户关闭；
- 最近更新：2026-08-08。

## 已完成

- [x] 阅读英文 v1.3 和中文 v1.0.3 Agent 教程的相关章节；
- [x] 复盘现有 LangChain/LangGraph、Harness、Tool、Evidence、Memory、Context、RAG、
  Job API 和评测实现；
- [x] 将优化工作合并为四个完整 Step；
- [x] 为每个 Step 建立独立计划和进度文件；
- [x] 项目默认模型配置改为 `deepseek-v4-flash`；
- [x] 明确不在本阶段引入通用多 Agent、GraphRAG、开放代码执行和实时交易。
- [x] 将多租户并发、准入、配额、公平调度、背压和资源池治理纳入 Step 04；
- [x] 完成 Step 04 身份边界、公平队列、有界 Worker、Provider 限流和薄演示界面；
- [x] 完成 91 Run 冻结并发基准、两条 Flash Planner 并发和 168/168 PostgreSQL 回归；

## 待审核决定

- [ ] 是否接受四步顺序和每步 Gate；
- [ ] Step 02 首批事件来源的选择与使用许可；
- [x] Step 03 首批演示股票池和 12 个因子定义；
- [x] Step 04 实现 FastAPI 内嵌薄 UI；GitHub 最终保持私有还是清理后公开仍待决定；
- [x] Step 04 真实 Flash 验证限定为两条 Planner 并发请求；
- [x] MCP Adapter 保持可选；无实际消费者前只保留共享 Schema 和适配边界。

## Step 01 实施结果

- [x] 生产与评测时钟分离；
- [x] Tool 前语义对齐和完整周期解析；
- [x] 摘要、结论、风险、限制的 Evidence 支撑校验；
- [x] 冻结 Manifest、私有 Holdout 外部入口、Git/CI/Secret 基线；
- [x] Docker + PostgreSQL 150/150 通过；
- [x] DeepSeek V4 Flash 财务和综合真实链路通过；
- [ ] 私有 Holdout 和 Key 轮换由用户关闭。

## Step 02 实施结果

- [x] Iceberg 原始事件、PostgreSQL 游标和 ACTIVE-only 状态机；
- [x] 父子 Chunk、Milvus + SQLite FTS5、Dense Anchor RRF；
- [x] 按文档版本的真实增量索引，未变化重跑写入为 0；
- [x] 情节记忆、不可变版本、TTL、反思幂等和跨用户隔离；
- [x] Context 来源、版本、裁剪、Token 和输出预算 Manifest；
- [x] 157/157 完整回归，Dense/Hybrid Recall/MRR/NDCG 均为 1.0；
- [x] 用户授权后完成真实 Flash Gate；
- [x] Step 03 将 Knowledge Context 升级为可引用的 Event Evidence Tool/Skill。

## Step 03 实施结果

- [x] 20 只版本化演示股票池、12 因子 Registry 和 4 张 Iceberg 元数据/结果表；
- [x] Spark 4.2 + PyIceberg 实跑生成 240 条结果，真实覆盖 2/20 并保留全部缺失；
- [x] 技术、基本面、因子、比较和 Event Evidence Tool 进入统一 Gateway；
- [x] 六个分析 Skill 包和标准/简洁/风险报告 Profile；
- [x] LangGraph Evidence 充分性、一次受控补充、动作去重和无进展终止；
- [x] 四维风险向量、三情景、Evidence 引用和数据截止日确定性绑定；
- [x] 全量发现 161 项（141 通过/20 跳过），另有 44 项 PostgreSQL 集成和 36 项最终聚焦通过；
- [x] 默认 Flash Event Tool + 受控补充真实 Gate 通过。

## Step 04 实施结果

- [x] `local`/`api_key` 可信身份边界，业务请求体不再决定租户和用户；
- [x] 全局、租户、用户三级准入与运行配额，结构化 `429` 和 `Retry-After`；
- [x] 交互优先、租户公平领取、租户作用域幂等和有界并发 Worker；
- [x] 数据库连接池、模型 Semaphore 和 PostgreSQL 共享 Provider 分钟窗口；
- [x] `/demo` 薄界面、分层延迟和队列/准入可观测指标；
- [x] 91 个冻结 Run 的丢失、重复终态、跨租户读取和 Provider 调用均为 0；
- [x] Flash Planner 并发 2/2，完整 PostgreSQL/Compose 回归 168/168；
- [x] MCP 保留 Schema 兼容边界，因无实际消费者而不实现协议服务器。

## 本轮代码影响

已完成 Step 01～04 的正确性、知识/记忆/上下文、分析 Tool/Skill、受控循环以及多租户并发
交付。历史 Pro 评测产物只保留为历史证据；运行时、示例环境和后续计划均以 Flash 为默认。

## 下一动作

轮换历史 Key，决定 GitHub 私有/公开与许可范围，再执行首次发布；若未来容量目标超过约 30 个
同时提交请求，先升级准入计数并重新压测，而不是直接增加第二套队列。
