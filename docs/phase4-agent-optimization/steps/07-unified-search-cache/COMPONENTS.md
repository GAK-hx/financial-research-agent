# 组件说明：统一检索、增量缓存与分析复用

## 1. 一次请求现在怎样运行

```text
用户问题
  -> LangGraph 理解问题并生成受控计划
  -> decompose_work：拆成“股票 × 数据域 × 时间窗”的原子任务
  -> Tool Gateway：先查 PostgreSQL 共享快照
       fresh      -> 直接复用
       inflight   -> 等待同一工作单元
       miss/stale -> 一个 Worker 取得租约并调用 Tool
  -> assemble_retrieval_snapshot：组装本 Job 所需证据
  -> resolve_analysis_cache / analyze_or_reuse：复用或生成结构化分析产物
  -> 报告生成：重新绑定当前用户记忆、会话、格式和引用
  -> PresentationEnvelope：返回缓存决策、刷新状态和来源链
```

模型仍负责理解、计划和表达，但它不能直接访问网页、数据库或缓存。所有真实数据访问仍经过
LangChain `StructuredTool`、Policy、预算、参数校验和 Tool Gateway。

## 2. PostgreSQL 保存什么

新增五张业务表：

| 表 | 用途 |
|---|---|
| `retrieval_work_units` | 原子工作状态、generation、租约、心跳、等待者和错误 |
| `job_work_dependencies` | 当前 Job 订阅了哪些共享工作 |
| `retrieval_snapshots` | ToolResult、Evidence hash、水位、TTL 和来源版本 |
| `analysis_artifacts` | 校验后的结构化事实/分析、Skill/模型/Prompt/Policy 版本 |
| `artifact_dependencies` | AnalysisArtifact 到 RetrievalSnapshot 的依赖关系 |

PostgreSQL 是协调和版本元数据的唯一真相。single-flight 使用事务级 advisory lock 保证同一 key
的决策串行化，再用工作租约允许 Worker 崩溃后的接管。Tool 长时间运行时会续租，完成写入是幂等的。

## 3. Elasticsearch 保存什么

ES 只保存公共网页和新闻，不保存 Job 锁、用户记忆或分析缓存。

- 索引：`web_documents_v1`
- 读写 alias：`web_documents`
- 查询：BM25 + 股票代码、主题、日期、域名、当前版本过滤
- 去重：canonical URL 的 SHA-256
- 更新：content hash 变化时增加 `content_version`
- 时间：严格区分 `published_at`、`fetched_at`、`first_seen_at`、`last_seen_at`

同一 URL 被不同股票查询命中时会合并 `stock_codes` 和 `topics`，避免交叉查询覆盖标签。

## 4. 网络搜索如何受控

`WebSearchProvider` 是供应商接口，首个实现为 Tavily。`web_search` Tool 只接受：

- 一只已在用户问题范围内的股票；
- 受控日期范围；
- `news/general` 主题；
- 最多 12 条结果；
- 配置允许的来源域名。

Harness 会把自然语言问题归一成稳定的事件主题，公共缓存键不包含整句用户问题。这样用户 A 和
用户 B 即使问题写法不同，只要股票、分析主题、时间窗和来源策略一致，仍能共享检索。供应商的
自动答案被忽略，只把有 URL 的来源内容转换为 Evidence。

## 5. 增量与失效

网络快照过期后：

```text
incremental_start = last_published_watermark - 24 hours
```

24 小时回看用来覆盖延迟收录、发布时间修正和同 URL 内容更新。新的 Evidence hash 会使依赖它的
AnalysisArtifact 失效；其他股票和其他快照的分析不受影响。Tool、Policy 或检索策略版本进入缓存键，
代码版本变化也会自然生成新快照。

“最新”查询刷新失败时返回失败，不把旧数据冒充最新；普通研究查询可以 `stale_fallback`，同时返回
刷新错误、旧快照 generation 和 `data_as_of`。

## 6. 分析缓存不缓存最终回答

AnalysisArtifact 只保存稳定的 Evidence ID、类型化事实和版本依赖，不保存用户问题原文、记忆、偏好
或最终报告。只有 schema/引用检查通过且输入快照明确的产物才会写入共享缓存。

最终报告仍为每个 tenant/user/session 单独生成。PresentationEnvelope 只负责把当前身份与
RetrievalSnapshot、AnalysisArtifact、`data_as_of` 和引用链重新绑定，因此不会把另一位用户的记忆或
表达风格带进当前回答。

## 7. LangGraph 新增节点

- `decompose_work`
- `assemble_retrieval_snapshot`
- `resolve_analysis_cache`
- `analyze_or_reuse`

实际缓存命中与外部调用抑制位于 Tool Gateway，LangGraph 节点负责把这部分状态显式化、可恢复并输出
给 API。旧的计划、取数、Evidence、研报正文和报告校验节点继续复用，没有另造第二套 Agent 运行时。

## 8. API 可见信息

每个 `tool_status` 增加：

- `cache_decision`
- `retrieval_snapshot_id`
- `refresh_performed`
- `stale_fallback`
- `refresh_error`

最终响应和 Job terminal SSE 还包含 `cache_summary`、`data_as_of` 和 `artifact_lineage`。Prometheus 文本
端点增加缓存 decision、外部调用节省和等待者指标。
