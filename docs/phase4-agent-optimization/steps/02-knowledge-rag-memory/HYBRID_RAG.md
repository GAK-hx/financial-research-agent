# 研报混合检索设计

## 1. 当前实现

研报检索由单一 Dense Retrieval 升级为：

```text
PDF
  → 页面清洗
  → 标题/章节识别
  → Parent Chunk（完整上下文）
  → Child Chunk（检索粒度）
  ├─ BGE Embedding → Milvus
  └─ 文本与元数据 → SQLite FTS5

查询 → Dense Top-K × 3 + Keyword Top-K × 3
     → RRF 合并，保留 Dense 第一名作为精度锚点
     → 返回命中 Child 对应的 Parent Context
```

Milvus 负责语义相似度；SQLite FTS5 是轻量关键词索引，不增加 Elasticsearch/OpenSearch 容器。
如果运行环境不支持 trigram tokenizer，会退化为 Unicode FTS，并提供确定性文本匹配兜底。
金融报告优先保护首条 Evidence 的精度：关键词结果用于调整第二名之后的顺序和补充长尾候选，
不会仅凭词频把 Dense 第一名挤走。

## 2. 为什么使用父子分块

固定长度小块容易命中关键词，但上下文不足；整页或整章上下文完整，但向量主题被稀释。当前
实现让 Child 负责召回，最终把 Parent 交给报告生成，同时保留页码、章节和原始 PDF 路径。

每个 Chunk 包含：

- `document_id`、`document_version` 和 `content_hash`；
- `parent_chunk_id`、`section_title` 和 `chunk_ordinal`；
- 股票、机构、报告日期和页码；
- Child 文本、Parent 文本和来源路径。

## 3. 增量更新和删除

`rag-index --mode incremental` 会：

1. 重新解析当前已登记 PDF；
2. 将内容哈希形成的文档版本与上次索引 Manifest 对比；
3. 只为新增或版本变化的文档生成 Embedding 并替换对应 Chunk；
4. 从 Dense 与关键词索引同时删除已经不存在的文档；
5. 校验 Dense/Keyword 总记录数一致，再写入索引时间、版本、变化文档数、插入数和删除数。

Milvus 与关键词索引计数不一致时任务失败，避免在线查询读到两套版本。

## 4. 检索路由和过滤

- 行情/财务精确数值继续走 Iceberg Tool；
- 外部公司事件走 KnowledgeStore；
- 研报观点走 Hybrid Report Retriever；
- 研报支持股票、起止日期和机构过滤；
- 向量库和关键词索引只负责召回，不是事实源。

报告 Evidence 继续保留 PDF、页码、Chunk、文档版本、Dense/Keyword 分数和检索策略。

## 5. 评测

`python -m financial_research_agent.rag.evaluate` 在冻结查询集上同时运行 Dense 和 Hybrid，记录：

- Recall@K；
- MRR@K；
- NDCG@K；
- 平均检索延迟；
- 每题 Dense/Hybrid 命中 Chunk。

Gate 要求 Hybrid 的 Recall 和 NDCG 不低于 Dense 基线。若没有收益，可以保留结构化分块但关闭
关键词融合，不因为“架构更复杂”就默认认为效果更好。
