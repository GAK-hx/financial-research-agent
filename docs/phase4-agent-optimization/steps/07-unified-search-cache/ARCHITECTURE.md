# 统一检索与分析复用架构

## 1. 三层边界

```text
┌──────────────────────────────────────────────────────────────┐
│ 查询层 Retrieval                                             │
│ QueryNormalizer -> WorkDecomposer -> WorkCoordinator         │
│ -> Tool Gateway -> Web / Milvus / Iceberg -> Evidence        │
│ 输出：RetrievalSnapshot                                      │
└──────────────────────────────┬───────────────────────────────┘
                               │ versioned evidence
┌──────────────────────────────▼───────────────────────────────┐
│ 分析层 Analysis                                              │
│ Skill -> Calculation / Fact Extraction / Comparison          │
│ -> Validator                                                 │
│ 输出：AnalysisArtifact                                       │
└──────────────────────────────┬───────────────────────────────┘
                               │ validated structured artifact
┌──────────────────────────────▼───────────────────────────────┐
│ 输出层 Presentation                                          │
│ Artifact + Current User Memory + Report Profile + Citations  │
│ 输出：ResearchReport / SSE                                   │
└──────────────────────────────────────────────────────────────┘
```

只有前两层的 `public` 产物可以跨用户复用。输出层每次重新绑定当前身份。

## 2. 存储分工

| 组件 | 保存内容 | 不保存 |
|---|---|---|
| Elasticsearch | 公共网页/新闻正文、元数据、版本、BM25 索引 | Job 锁、用户记忆、分析缓存 |
| PostgreSQL | Job、工作单元、依赖、检索快照、分析产物、TTL、水位 | 大规模网页全文、行情历史事实表 |
| Milvus + SQLite | PDF 研报向量与关键词索引 | 网络缓存、任务状态 |
| Iceberg | 行情、财务和长期数据快照 | 用户会话、网页正文 |
| LangGraph checkpoint | 单次运行状态与恢复点 | 跨运行公共缓存的唯一真相 |

## 3. 多用户合并示例

```text
用户 A：[600519, 300750, 601318, 000858, 600036] + 新闻/风险
用户 B：[600519, 300750, 000858, 002594]         + 新闻/风险

拆分后的公共原子任务：
  news:600519:risk:2026-08-15  <- A、B
  news:300750:risk:2026-08-15  <- A、B
  news:601318:risk:2026-08-15  <- A
  news:000858:risk:2026-08-15  <- A、B
  news:600036:risk:2026-08-15  <- A
  news:002594:risk:2026-08-15  <- B

实际外部检索：6 个原子任务，而不是 10 个。
```

如果前三个公共任务已经在有效期内，实际只补查剩余过期或缺失项。

## 4. 工作单元状态机

```text
PENDING -> LEASED -> RUNNING -> SUCCEEDED
   |         |          |
   |         |          +----> RETRY_WAIT -> PENDING
   |         +---------------> LEASE_EXPIRED -> PENDING
   +--------------------------> CANCELLED
                         \----> FAILED
```

同一 `atomic_query_key + generation` 只能存在一个 active 工作单元。Job 通过依赖表订阅结果。
Worker 领取时写入 `lease_owner` 和 `lease_expires_at`，定期心跳；完成时在一个事务中写快照、
更新水位和结束工作单元。

## 5. 缓存键分层

### Retrieval key

```text
canonical_hash({
  stock_code, domain, normalized_topic, window_or_bucket,
  provider_policy_version, visibility, tenant_id_if_private
})
```

### Analysis key

```text
canonical_hash({
  analysis_type, subjects, retrieval_snapshot_ids_and_versions,
  skill_versions, model_id, prompt_version, policy_version
})
```

### Presentation key

默认不持久化共享。如需同一用户短时重放：

```text
canonical_hash({
  analysis_artifact_ids, tenant_id, user_id, session_id,
  memory_version, report_profile
})
```

## 6. Elasticsearch 索引

`web_documents_v1` 建议字段：

```yaml
document_id: keyword
canonical_url: keyword
canonical_url_hash: keyword
url: keyword
domain: keyword
title: text + keyword
content: text
summary: text
stock_codes: keyword
topics: keyword
language: keyword
source_tier: keyword
provider: keyword
published_at: date
first_seen_at: date
last_seen_at: date
fetched_at: date
content_hash: keyword
content_version: integer
is_current: boolean
```

初版使用 BM25 + filter。股票名称/代码和主题进入 should，股票代码、日期、语言和来源策略进入
filter。相同 canonical URL 通过稳定 document ID upsert；内容变化增加版本并更新当前文档。

不直接使用 ES request cache 作为业务缓存，因为 TTL、依赖失效和权限需要在应用层可观察。
ES 自身 query/filesystem cache 仅作为底层性能优化。

## 7. 网络 Evidence

```yaml
evidence_type: web_source | event
subject: stock_code
statement: compact source-grounded statement
data:
  title: string
  published_at: datetime | null
  fetched_at: datetime
  excerpt: string
  provider: tavily
  source_tier: official | exchange | major_media | other
  content_hash: string
source:
  type: knowledge
  locator: canonical https URL
  metadata:
    es_document_id: string
    retrieval_snapshot_id: string
```

来源 URL、发布时间和抓取时间必须区分。发布时间未知时不得伪造成抓取时间。

## 8. 增量刷新示例

```text
旧 Snapshot：
  last_success_at = 2026-08-15 09:00
  max_published_at = 2026-08-15 08:42
  evidence_hash = H1

10:00 刷新：
  provider start = 08:42 - 24h overlap
  返回 URL A（相同内容）、URL B（内容更新）、URL C（新增）

处理：
  A -> 去重，不产生新 Evidence
  B -> content_version + 1，替换相关 Evidence
  C -> 新增 Evidence
  新 Snapshot hash = H2
  仅依赖 H1 且受 B/C 影响的 AnalysisArtifact 失效
```

## 9. LangGraph 节点衔接

```text
... -> validate_plan
    -> decompose_work
    -> resolve_retrieval_cache
    -> execute_or_join_work
    -> assemble_retrieval_snapshot
    -> resolve_analysis_cache
    -> analyze_or_reuse
    -> build_evidence/context
    -> generate_user_output
    -> validate_report
    -> finalize
```

Step 06 的研报候选与正文分支位于 `execute_or_join_work` 内部，但输出统一成为
RetrievalSnapshot；ReportFact 属于 AnalysisArtifact。

## 10. 可观测指标

- `retrieval_cache_hit_total{decision,domain}`
- `retrieval_external_calls_saved_total{provider}`
- `analysis_cache_hit_total{analysis_type}`
- `inflight_join_total{domain}`
- `work_unit_waiters`
- `incremental_documents_new/updated/unchanged`
- `artifact_invalidation_total{reason}`
- `cache_age_seconds`
- `retrieval_refresh_latency_ms`
- `presentation_generation_latency_ms`

并发 Gate 必须同时报告正确性和节省量，不能只报告吞吐量。
