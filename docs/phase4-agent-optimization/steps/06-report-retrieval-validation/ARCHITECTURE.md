# 研报两级工作流架构

## 1. 组件关系

```text
ResearchRequest
  |
  v
QueryInterpreter + ReportRequestResolver
  |  QuerySpec + ReportAnalysisRequest
  v
LangGraph / Harness
  |
  +-- 非 report 域 --------------------------> 现有分析工具
  |
  +-- report_candidate_search
         |  LangChain StructuredTool
         v
      HybridReportStore（Milvus dense + SQLite FTS）
         |
         v
      ReportCandidateSet / report_candidate Evidence
         |
         +-- candidate_only --> Candidate Context --> 清单型回答
         |
         +-- deep --> ReportSelector（Harness）
                         |
                         v
                    report_content_search
                         |
                         v
                    research_report Evidence
                         |
                         +-- 可选 ReportFactExtractor
                         v
                    Deep Report Context
                         |
                         v
                    ReportValidator
```

这仍是一个 Agent、一张 LangGraph。两个 Tool 表示不同的数据访问权限，而不是两个 Agent。

## 2. 核心数据模型

### ReportAnalysisRequest

```yaml
mode: candidate_only | deep
explicit_date_range: true | false
start_date: date | null
end_date: date | null
institution_filters: [string]
title_keywords: [string]
candidate_ids: [string]
candidate_ordinal: integer | null
deep_topics:
  - viewpoint
  - target_price
  - rating
  - earnings_forecast
  - catalyst
  - risk
  - institution_disagreement
allow_unknown_date: false
```

该对象由 Harness 验证；模型建议不能扩大股票、日期、租户或文档范围。

### ReportCandidate

```yaml
candidate_id: rpt_<stable hash>
document_id: internal document id
stock_code: "600519"
institution: string
report_title: string
report_date: date | null
date_unknown: boolean
excerpt: max 160 chars
relevance_score: float
retrieval_strategy: dense | keyword | hybrid
document_version: string
content_hash: string
```

`candidate_id` 是对外稳定标识；`source_path` 只留在服务端审计信息，不进入模型上下文和 API 默认响应。

### ReportCandidateSet

```yaml
candidate_set_id: string
run_id: string
tenant_id: string
user_id: string
session_id: string
requested_window: {start_date, end_date}
applied_window: {start_date, end_date}
window_expanded: boolean
coverage_status: sufficient | limited | empty
candidates: [ReportCandidate]
```

### ReportSelection

```yaml
candidate_set_id: string
candidate_ids: [string]
selection_source: user | deterministic_policy
selection_reason: string
max_documents: integer
```

正文工具只接收该对象。选择器验证 candidate set 的身份范围及候选成员关系。

### ReportFact

```yaml
fact_id: string
fact_type: target_price | rating | earnings_forecast | financial_metric | catalyst | risk
metric_name: string | null
value: number | null
unit: string | null
currency: string | null
period: string | null
text_value: string | null
source_span: string
document_id: string
page_number: integer
evidence_id: string
confidence: high | medium | low
extraction_method: rule | model_structured
```

`ReportFact` 是带来源的派生结构，不替代原始研报 Evidence。模型抽取时必须返回原文片段，
系统再验证该片段确实存在于对应 Evidence 正文中。

## 3. LangGraph 状态变化

建议新增字段：

```text
report_request
report_candidate_set
report_validation_profile
report_selection
report_facts
report_window_expanded
report_depth_reason
```

建议节点顺序：

```text
load_memory
 -> interpret
 -> align_semantics
 -> resolve_report_request
 -> remember_query
 -> select_skill
 -> initialize_governance
 -> plan
 -> validate_plan
 -> execute_tools
 -> build_evidence
 -> validate_report_candidates
 -> decide_report_depth
      | candidate_only
      +---------------------------> check_evidence_sufficiency
      | deep
      -> select_report_candidates
      -> retrieve_report_content
      -> extract_report_facts（按需）
      -> build_evidence
      -> check_evidence_sufficiency
 -> generate_report
 -> validate_report
 -> revise_report（最多一次）
 -> completion_check
 -> finalize
```

对于非研报查询，三个研报节点是常数时间旁路，不产生 Tool 调用。

## 4. 深析触发规则

| 条件 | 模式 | 说明 |
|---|---|---|
| 无 report 域 | none | 不访问研报 |
| “有哪些/列表/筛选/查找研报” | candidate_only | 只返回候选元数据 |
| “总结/观点/详细/全文” | deep | 默认最多 3 份 |
| “目标价/评级/盈利预测/催化剂/风险” | deep | 同时启用相应 Fact 类型 |
| “机构分歧/比较机构” | deep | 最多 5 份并优先机构多样性 |
| 显式候选 ID、序号、机构或标题 | deep | 必须能在候选集中匹配 |

若规则与模型建议冲突：

- 规则判定 `deep` 时不能被模型降为候选清单；
- 规则判定 `candidate_only` 时，模型不能自行申请全文；
- 无法确定时采用 `candidate_only`，在清单中提示用户可选择研报继续分析。

## 5. 访问与预算边界

- 候选阶段：最多 5 个去重文档，允许一次 90 -> 180 天扩大；
- 深析阶段：普通总结最多 3 个文档，机构对比最多 5 个文档；
- 每个文档默认最多 3 个正文父块，总正文块上限由 Context Policy 再限制；
- 重试沿用现有 Tool Gateway 的退避策略，但扩大时间窗不是网络重试；
- 模型调用预算分别记录“请求理解、事实抽取、报告生成、报告修正”；
- 候选阶段不做模型摘要，摘要取命中块的受限截断文本；
- 只有需要高风险结构化事实时才调用 Fact 抽取，普通观点总结不额外调用。

## 6. Evidence 使用规则

| Evidence 类型 | 可以支持 | 不可以支持 |
|---|---|---|
| `report_candidate` | 研报存在、标题、机构、日期、候选排序和覆盖说明 | 目标价、盈利预测、风险结论、详细机构观点 |
| `research_report` | 对应页正文中的观点和事实 | 未选中文档、未命中页面或跨运行内容 |
| `market/financial/...` | 各自领域的结构化事实 | 研报作者观点 |

候选 Evidence 和正文 Evidence 使用不同 ID 前缀，避免校验器误用。

## 7. 与现有组件的兼容

- LangChain：两个数据工具仍通过 `StructuredTool` 暴露，完整结果放在 ToolMessage artifact；
- LangGraph：新增字段可 JSON 序列化并由 PostgreSQL checkpointer 保存；
- Retriever：保留 `BaseRetriever` 兼容层，正文检索仍返回标准 `Document`；
- Evidence：新增候选类型，正文类型不变；
- ContextBuilder：继续生成 Context Manifest 和 Evidence 保护哈希；
- Memory：候选集只作为带 TTL 的会话记录，不写成长周期偏好或知识；
- Knowledge：研报候选和正文不是事件知识入库，本 Step 不复制进知识库；
- Docker：沿用当前 API、Worker、PostgreSQL、Milvus 和 Iceberg 服务，不增加容器。
