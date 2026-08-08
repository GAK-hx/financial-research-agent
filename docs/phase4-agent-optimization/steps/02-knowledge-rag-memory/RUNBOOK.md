# Step 02 操作手册

## 1. 启动依赖并迁移

```bash
docker compose up -d postgres etcd milvus
docker compose run --rm db-migrate
```

## 2. 运行本地事件知识样例

```bash
docker compose --profile knowledge run --rm knowledge-ingest
```

再次运行不应产生重复有效事件。当前样例不是实时新闻；输出中的 `fixture=true` 和
`realtime=false` 必须保留。

查看 ACTIVE 事件：

```bash
curl 'http://localhost:8000/knowledge/events?symbol=600519&limit=10'
```

## 3. 重建或增量更新研报索引

```bash
docker compose --profile rag run --rm rag-index
```

如需明确清空旧索引后重建：

```bash
docker compose --profile rag run --rm rag-index \
  python -m financial_research_agent.rag.indexer --mode rebuild
```

运行 Dense/Hybrid 对比：

```bash
docker compose --profile rag run --rm rag-index \
  python -m financial_research_agent.rag.evaluate
```

结果写到 `artifacts/phase4/step02/rag_evaluation.json`。

## 4. Memory 管理

```text
GET    /memory
GET    /memory/{memory_id}/versions
POST   /memory/preferences
DELETE /memory/{memory_id}
POST   /memory/cleanup
```

情节记忆不提供“用户随意写入”接口，只能由完成且验证通过的 LangGraph Run 在终态反思阶段写入。

## 5. 失败排查

- `KNOWLEDGE_STATUS_TRANSITION_DENIED`：检查状态机是否跳过 Candidate；
- `RAG_INDEX_COUNT_MISMATCH`：Dense 与关键词索引版本不一致，应重新构建；
- `CONTEXT_BUDGET_EXCEEDED`：查看 Context Manifest 的 `trimmed` 和 Token；
- `EVIDENCE_PROTECTED_FIELDS_CHANGED`：压缩或摘要修改了受保护事实；
- `EPISODIC_RUN_NOT_VALIDATED`：未通过 Validator/Completion 的 Run 不得反思写入。
