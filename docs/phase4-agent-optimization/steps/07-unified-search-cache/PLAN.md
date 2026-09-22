# Step 07：统一网络检索、增量缓存与分析复用

> 状态：`PASS_PARTIAL_ONLINE`
> 默认模型：`deepseek-v4-flash`
> 前置依赖：Step 06 输出可序列化的研报候选集、正文 Evidence 与类型化事实
> 新增基础设施：单节点 Elasticsearch；不新增 Redis、Kafka 或 Kibana

## 1. 目标

本 Step 将现有“一个请求从取数一直生成报告”的链路拆成三个可独立复用的阶段：

1. **查询阶段**：从网络、研报索引、行情和财务数据源取得并标准化 Evidence；
2. **分析阶段**：基于确定版本的 Evidence 计算指标、提取事实并形成结构化分析产物；
3. **输出阶段**：结合当前用户的格式偏好、会话上下文和权限生成最终回答。

用户重复或交叉查询时，系统复用仍然有效的公共检索结果和分析产物，只对过期、缺失或新增的
原子任务做增量查询。用户记忆、私有数据和最终个性化文本不跨租户共享。

## 2. 为什么不能只缓存最终回答

- 同一句话可能对应不同业务参考时间、数据版本或用户权限；
- 其他用户的偏好、会话信息和私有 Evidence 可能被错误复用；
- “最新消息”在 TTL 内也可能新增或被更正，整段结果缓存无法解释更新范围。

因此缓存单位不是原始问题文本，而是带版本和权限范围的结构化产物。

## 3. 总体流程

```text
User Query
  -> QueryNormalizer
  -> WorkDecomposer（股票 × 数据域 × 时间桶）
  -> WorkCoordinator
       -> fresh cache hit：直接复用 RetrievalSnapshot
       -> in-flight hit：加入同一工作单元等待结果
       -> partial/stale：仅查询缺失区间 + 回看窗口
       -> miss：执行完整受控 Tool
  -> RetrievalSnapshot
  -> AnalysisArtifact lookup
       -> hit：复用结构化分析
       -> miss：执行 Skill/计算/事实提取并持久化
  -> PresentationBuilder
       -> 合并当前用户记忆、输出格式和引用
       -> 生成最终回答
```

多股票问题会拆成原子工作单元。例如用户 A 查询 5 只股票、用户 B 查询其中 3 只时，重叠的
3 个工作单元只执行一次；两个请求分别等待和组装自己需要的结果。

## 4. 组件分工

### Elasticsearch：公共网页内容检索库

Elasticsearch 用于保存和检索网络搜索取得的公共网页/新闻文档：

- BM25 全文检索以及股票代码、名称、来源域名、发布时间和语言过滤；
- 通过 canonical URL 与 content hash 去重和版本化；
- 保存网页标题、受限正文、摘要、发布时间、抓取时间、来源等级和 Evidence 定位信息；
- 后续可使用外部 embedding 增加 `dense_vector`，本 Step 不部署 ELSER 或 ES 内置 ML。

Elasticsearch **不承担**任务锁、分析缓存或用户会话存储。

Docker 采用单节点、无 Kibana、无 ML 的轻量配置，目标容器内存 1～1.5 GB、JVM 512 MB，
镜像和 Python client 固定同一兼容主版本。服务放入可选 `search` profile，集成测试时再启动。

### PostgreSQL：协调、版本与持久化

复用现有 PostgreSQL，新增：

- `retrieval_work_units`：原子工作单元、状态、租约、重试和唯一执行键；
- `job_work_dependencies`：一个用户 Job 依赖哪些共享工作单元；
- `retrieval_snapshots`：Evidence ID、数据版本、水位和有效期；
- `analysis_artifacts`：结构化分析、输入版本、Skill/模型/提示词版本和有效期；
- `artifact_dependencies`：分析产物依赖的 RetrievalSnapshot，用于精确失效。

Worker 使用数据库唯一键、事务级 advisory lock 和行锁实现 single-flight：同一原子任务只有一个执行者，其他 Job
只建立依赖，不重复调用外部 API。延续现有 Worker，不引入 Redis 队列。

### 网络搜索：受控 Tool

新增 LangChain StructuredTool：`web_search`。

- 通过 `WebSearchProvider` 接口隔离具体供应商；
- 第一实现使用 Tavily Search，因为它提供起止日期、新闻主题、发布时间和可选清洗正文；
- 后续可增加 Brave LLM Context 适配器，不改变 Tool schema；
- 模型只能提交查询意图，Harness 负责股票、日期、域名、条数和 token 预算；
- 不开放任意 URL 抓取器，不允许模型访问内网地址或扩大来源范围；
- Provider 未配置时返回 `WEB_SEARCH_NOT_CONFIGURED`，离线数据流程仍可运行。

网络结果先标准化、去重并写入 ES，再转换为当前运行的网络/事件 Evidence。搜索供应商生成的
“答案”不作为 Evidence，只使用可定位到 URL 的来源内容。

## 5. 数据模型与版本键

### AtomicQueryKey

```text
hash(stock_code, data_domain, normalized_topic,
     explicit_time_range_or_time_bucket,
     source_policy_version, visibility_scope)
```

原始自然语言和输出风格不进入该键，保证语义等价查询可以合并。

### RetrievalSnapshot

```text
snapshot_id / atomic_query_key / evidence_ids
source_watermark / source_versions
window_start / window_end / fetched_at / fresh_until
visibility: public | tenant / tenant_id_if_private
coverage_status
```

### AnalysisArtifact

```text
artifact_id / analysis_key / analysis_type / subjects
structured_facts / metrics / risks / comparisons
input_snapshot_ids / skill_versions / model_id
prompt_version / policy_version
created_at / fresh_until / visibility / validation_status
```

### PresentationEnvelope

输出阶段临时构建，不作为跨用户公共缓存：

```text
analysis_artifact_ids / tenant_id / user_id / session_id
preference_version / memory_refs / report_profile / language / format
```

## 6. 缓存与失效策略

缓存首先看数据版本，其次才看 TTL。默认值均可配置：

| 产物 | 默认有效期 | 失效条件 |
|---|---:|---|
| 网络新闻检索快照 | 15 分钟 | 增量搜索发现新 URL/内容版本、来源策略变化 |
| 普通网页检索快照 | 60 分钟 | 新版本、来源策略变化 |
| 研报候选集 | 6 小时 | 研报索引版本或查询窗口变化 |
| 日线/财务检索快照 | 至数据快照变化，硬上限 24 小时 | Iceberg snapshot/data_as_of 变化 |
| 新闻/事件分析产物 | 30 分钟 | 输入快照、Skill、模型或提示词版本变化 |
| 研报/日线结构化分析 | 6 小时，硬上限 24 小时 | 任一依赖或实现版本变化 |
| 最终用户文本 | 默认不跨用户缓存 | 用户、会话、记忆、格式或引用变化 |

明确包含“最新/刚刚/今日”的请求必须等待增量刷新完成；普通研究请求在刷新失败时可以返回仍在
允许陈旧窗口内的产物，并标记 `stale_fallback`、刷新错误和数据截止时间。初版不在请求结束后
保留脱离 Job 租约与审计链的后台刷新任务。

## 7. 增量查询

每个原子工作单元保存最后成功水位：

```text
incremental_start = last_successful_watermark - overlap_window
```

网络搜索默认回看 24 小时，避免漏掉延迟收录、发布时间修正和同 URL 内容更新：

1. canonicalize URL，移除常见追踪参数；
2. canonical URL hash 识别同一网页；
3. content hash 判断是否产生新版本；
4. ES upsert 保留 `first_seen_at`、`last_seen_at` 和版本；
5. 只为新增或变化文档生成新 Evidence；
6. Evidence 集和版本未变时，已有 AnalysisArtifact 继续有效。

“增量”指数据范围和内容版本上的补充，不是盲目减少搜索条数。

## 8. 多用户并发与交叉查询

WorkCoordinator 返回：

- `fresh_hit`：直接复用；
- `partial_hit`：复用已有股票/数据域，只执行缺失部分；
- `stale_refresh`：执行增量刷新；
- `inflight_join`：加入正在执行的工作单元；
- `miss`：首次完整查询。

共享边界：

- 公共网络、公开行情和公开研报产物可以跨用户复用；
- 包含用户上传内容、私有知识或租户数据的键必须包含 `tenant_id`；
- 用户记忆和输出偏好只进入 PresentationEnvelope；
- 工作单元使用租约和心跳，Worker 崩溃后可以接管；
- 完成写入保持幂等，避免同一增量数据产生重复 Evidence。

## 9. 分步实现

### 07.1 三层接口与 PostgreSQL 模型

- 引入 RetrievalSnapshot、AnalysisArtifact、PresentationEnvelope 和缓存决策模型；
- 将现有 Job 拆成检索依赖、分析依赖和输出状态，同时保持原 API 兼容；
- 建立工作单元、Job 依赖、快照、分析产物和依赖关系表；
- 使用唯一执行键、数据库 advisory lock、租约和行级锁复用现有 Worker。

最小测试：模型序列化、状态迁移、两个 Job 关联同一工作单元。

### 07.2 Elasticsearch 与网络搜索 Tool

- 增加 ES Docker profile、健康检查、持久卷、凭据和资源限制；
- 增加官方异步 Python client 和索引初始化器；
- 建立 `web_documents_v1` mapping、alias 和版本迁移方式；
- 实现 Tavily Provider、`web_search` StructuredTool、来源标准化和 Evidence 转换；
- 实现 URL/content 去重、日期/股票/域名筛选和结构化错误。

最小测试：Provider fake、ES mapping、upsert/检索和密钥脱敏。

### 07.3 增量缓存与 single-flight

- 实现结构化 key、TTL + 数据版本双重判断；
- 实现 24 小时回看窗口、水位推进和无变化复用；
- 实现 exact duplicate、partial overlap、stale refresh 和 inflight join；
- 实现依赖变化后的 AnalysisArtifact 精确失效；
- 增加命中、节省的 Tool/模型调用、刷新耗时和等待者指标。

最小测试：冻结时间下的命中/过期、并发只执行一次、部分股票只补缺失项。

### 07.4 LangGraph、分析产物与输出组装

- LangGraph 在 Tool 前查询 RetrievalSnapshot，在报告前查询 AnalysisArtifact；
- 将技术面、基本面、因子、事件和研报结果标准化为可持久化分析产物；
- 只有校验通过的 AnalysisArtifact 可以共享；
- 输出阶段重新绑定当前用户上下文和引用；
- API/SSE 展示缓存决策、刷新状态、`data_as_of` 和产物来源链路。

最小测试：共享分析 + 两种用户输出格式、私有输入不共享、旧 checkpoint 兼容。

### 07.5 集中 Gate

1. 10～20 只股票、4～5 个用户，每人查询 4～5 只且存在交叉；
2. 精确重复请求只产生一次外部检索和一次公共分析；
3. 部分交叉请求只补查缺失股票/数据域；
4. 过期后只执行带回看窗口的增量刷新；
5. 新网页或内容更新只失效相关 AnalysisArtifact；
6. 用户记忆、私有 Evidence 和最终文本没有跨租户泄露；
7. ES、搜索 Provider、模型或 Worker 故障均产生可恢复状态；
8. 全量离线回归只在末尾执行；在线只做一组 Web Search + Flash 演示。

## 10. 明确不做

- 不用 Elasticsearch 保存 Job 锁、会话记忆或分析缓存；
- 不缓存和跨用户共享个性化最终报告；
- 不引入 Redis、Kafka、Celery、Kibana 或 ES 内置 ML；
- 不开放任意网页抓取、任意 URL 读取或模型直接访问搜索 API；
- 不把搜索供应商生成的答案当作来源证据；
- 不删除现有 Milvus 研报索引或 Iceberg 数据底座。

## 11. 完成标准

- 网络搜索通过受控 LangChain Tool 接入，URL、时间和来源可追踪；
- ES 实际承担公共网页索引与检索，不只是部署但未使用；
- 查询、分析和输出在代码、数据库状态与 LangGraph 节点上均有清晰边界；
- 重复和交叉查询能证明外部查询与模型调用减少；
- 增量刷新不会因严格水位漏掉延迟收录或更新内容；
- 公共产物可以安全复用，私有输入与最终文本保持隔离；
- 分析产物具备输入、模型、Skill、Prompt、Policy 和 Evidence 版本来源链路。

## 12. 外部设计依据

- [LangChain Tool 接口与命名](https://docs.langchain.com/oss/python/langchain/tools)
- [LangChain 搜索工具集成](https://docs.langchain.com/oss/python/integrations/tools/index)
- [Tavily Search 日期、新闻和正文参数](https://docs.tavily.com/documentation/api-reference/endpoint/search)
- [Elasticsearch 混合检索建议](https://www.elastic.co/docs/solutions/search/hybrid-search)
- [Elasticsearch 查询与缓存调优](https://www.elastic.co/guide/en/elasticsearch/reference/current/tune-for-search-speed.html)
- [Elasticsearch Python client 兼容性](https://www.elastic.co/docs/reference/elasticsearch/clients/python)
- [Elasticsearch 单节点 Docker](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/install-elasticsearch-docker-basic)
