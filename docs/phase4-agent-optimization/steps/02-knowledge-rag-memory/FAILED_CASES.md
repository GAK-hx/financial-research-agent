# Step 02 失败案例记录

## 2026-08-08：首轮聚焦回归

### 执行命令

```bash
docker compose run --rm -e RUN_POSTGRES_TESTS=1 app \
  python -m unittest \
  tests.test_knowledge tests.test_rag tests.test_memory_context \
  tests.test_langchain_enhancements tests.test_langgraph_runtime -v
```

### 结果

- 总计：27；
- 通过：24；
- 失败：2；
- 错误：1；
- PostgreSQL Memory API、租户/用户隔离、TTL、版本历史和 LangGraph 基本运行均通过。

### 原始失败 1：RAG 测试夹具不满足数据模型

```text
ERROR: test_incremental_keyword_index_filters_and_retrieves
pydantic_core._pydantic_core.ValidationError: 1 validation error for ReportChunk
text
  String should have at least 20 characters
  input_value='线上渠道改革持续推进。'
```

判断：测试夹具错误，不是索引运行错误。`ReportChunk.text` 明确要求至少 20 个字符，测试必须使用
真实可接受长度的文本。

### 原始失败 2：摘要安全测试没有触发摘要分支

```text
FAIL: test_one_layer_summary_cannot_introduce_numbers
AssertionError: EvidenceProtectionError not raised
```

判断：当前确定性裁剪已把输入压到预算内，因此模型摘要函数没有执行。应修改测试，使其显式验证
摘要输出的数字保护，而不是依赖一个可能先被确定性裁剪消除的超限场景。

### 原始失败 3：旧 Collection Locator 断言

```text
FAIL: test_retrieval_context_memory_skill_and_runtime_chain
AssertionError:
'milvus://research_reports_v2/chunk-600519-7'
!=
'milvus://research_reports_v1/chunk-600519-7'
```

判断：实现已将新父子 Chunk Schema 放在 `research_reports_v2`，测试仍断言旧版本；同步断言即可。

### 修复状态

- [x] 修复三处测试/实现问题；
- [x] 重跑相关测试；27/27 通过；
- [x] 完成后记录验证结果。

## 2026-08-08：第一次真实 Knowledge Lake 集成

### 执行命令

```bash
docker compose --profile knowledge run --rm knowledge-ingest
```

### 原始失败

```text
ValueError: Mismatch in fields:
Table field: source_id/source_record_id/raw_version/symbol/event_type/
             published_at/fetched_at/source_url/payload_json required string
Dataframe field: corresponding fields optional string
```

### 原因与修复

`pa.Table.from_pylist(rows)` 默认生成 nullable Arrow 字段，而 Iceberg 原始事件 Schema 将九个字段
声明为 required。现改为使用 `schema_to_pyarrow(RAW_EVENT_SCHEMA)` 显式构造 Arrow Table，保证
Arrow nullability 与 Iceberg Schema 一致。失败发生在 Iceberg append 阶段，游标尚未提交，也没有
写入 PostgreSQL 有效事件。

- [x] 修复 Arrow/Iceberg required 字段兼容；
- [x] 重建 Knowledge 镜像并重跑两次验证。

## 2026-08-08：Knowledge Cursor Upsert 集成

### 原始失败

```text
SAWarning: Additional column names not matching any column keys in table
'knowledge_source_cursors': 'metadata_json'

asyncpg.exceptions.UndefinedColumnError:
column "metadata_json" of relation "knowledge_source_cursors" does not exist
```

失败 SQL 的 `INSERT` 正确使用数据库列 `metadata`，但 `ON CONFLICT DO UPDATE SET` 使用了 ORM
属性名 `metadata_json`。现将 upsert 的 `set_` 映射改为 ORM Column 对象，SQLAlchemy 会正确解析
真实数据库列名。

本次故障发生顺序为：Iceberg append 成功、事件标准化和状态迁移成功、游标提交失败。恢复时允许
原始层保留重复抓取痕迹，但标准化事件必须由唯一键识别为重复，随后成功推进游标。

- [x] 修复 Cursor upsert 列映射；
- [x] 验证故障恢复不会产生重复有效事件；ACTIVE 总数保持 2；
- [x] 验证游标推进后再次运行返回空批次；`cursor_before=2, raw_rows=0`。

## 2026-08-08：首次 Dense/Hybrid 冻结集评测

### 结果

```text
Dense:  Recall@5=1.0000, MRR@5=1.0000, NDCG@5=1.0000, mean=10.05ms
Hybrid: Recall@5=1.0000, MRR@5=0.8125, NDCG@5=0.8577, mean=8.55ms
Gate:   Recall 未下降=true, NDCG 未下降=false
```

完整逐题结果保存在 `artifacts/phase4/step02/rag_evaluation.json`。

### 判断与修复

关键词 RRF 保住了全部召回，但把 Dense 已正确命中的第一名向后移动，降低排序质量。为避免为了混合
检索而接受质量倒退，融合策略改为 Dense Anchor：Dense 第一名保持首位，RRF 只重排和补充后续
候选。该策略仍使用关键词检索扩展长尾，但优先保护金融报告第一条 Evidence 的精度。

- [x] 保存未通过指标；
- [x] 增加 Dense Anchor；
- [x] 重跑冻结集；Dense/Hybrid Recall、MRR、NDCG 均为 1.0。

## 2026-08-08：首次完整确定性回归

### 结果

```text
Ran 157 tests in 22.441s
FAILED (failures=2)
```

### 失败 1：数据湖域断言未更新

```text
FAIL: test_catalog_bootstrap_is_idempotent
Items in the first set but not the second: 'knowledge'
```

实现已将 `knowledge` 加入正式 Iceberg Namespace，旧测试仍只期望 market、financial、metadata、
simulation。已同步断言，不修改生产实现。

### 失败 2：外部 Worker 抢占测试 Job

```text
FAIL: test_expired_lease_recovery_cancel_and_resume
self.assertIsNotNone(claimed)
AssertionError: unexpectedly None
```

运行全量回归时 Compose 中常驻 `job-worker` 仍在轮询同一个 PostgreSQL，它可能在测试自己的
`JobStore.claim()` 前抢走刚入队的测试 Job。该失败不来自租约算法；最终回归前停止外部 Worker，
让测试的两个显式 Worker 成为唯一消费者。测试结束后再用最新镜像恢复服务。

- [x] 更新 Knowledge Namespace 断言；
- [x] 定位外部 Worker 测试环境竞争；
- [x] 在隔离 Worker 后重跑完整回归；157/157 通过。

## 2026-08-08：真实 Flash Gate 授权等待

真实端到端问题会把本地事件与研报检索片段作为模型上下文发送至 DeepSeek。执行环境在请求发出
前阻止了该操作，因为当前授权只覆盖“使用 Flash 测试”，未明确覆盖“向 DeepSeek 发送这些本地
项目数据”。没有请求到达外部模型，也没有产生本次模型费用。

这不是功能失败或网络失败。待用户明确授权该数据发送范围后，再执行一条小规模真实 Gate；不得
通过绕过策略、改走其他客户端或隐藏上下文的方式规避授权。

### 关闭结果

用户已明确授权。随后执行一条 `deepseek-v4-flash` 端到端请求，`success=true`、模型规划、
Hybrid RAG、Completion 和最终 Validation 均通过。没有发生网络或 Provider 失败。
