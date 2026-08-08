# 07 RAG与知识管理

## 1. 目标

RAG不是普通相似文本拼接，而是建立能按股票过滤、能定位机构和页码、能生成Evidence的研报证据库。

## 2. 摄取流程

```text
PDF
→ 文件校验
→ 逐页解析
→ 页眉页脚清理
→ 报告Metadata
→ 分块
→ Embedding
→ Milvus
→ 抽样验证
```

第一版复用旧项目验证过的500字符/50重叠递归分块，先补足页码和Metadata。结构化章节分块作为后续优化，不与第一步闭环同时冒险修改。

## 3. Metadata

必须包括：stock_code、stock_name、institution、report_title、report_date（可缺失但标记）、page_number、chunk_id、source_path。

## 4. 向量与Collection

- 模型：BGE-small-zh-v1.5；
- 向量归一化；
- IP相似度；
- 运行时探测Embedding维度；
- 新Collection：`research_reports_v1`；
- Schema不匹配时明确失败，不静默drop；
- Milvus是可重建索引，PDF与Metadata清单是事实来源。

## 5. 查询流程

```text
QuerySpec
→ stock_code Metadata Filter
→ Query Embedding
→ Top 20候选（第一版可直接Top K）
→ 可选Rerank（后续）
→ Top 5～10
→ Report Evidence
```

不得在股票过滤无结果后自动返回其他股票研报。

## 6. 引用

每个研报Evidence包含原文、报告、机构、页码、chunk ID和相似度。Reporter必须明确“某机构研报认为”，不能把机构观点写成事实。

## 7. 第一阶段验收

- 6份PDF全部可索引；
- 每条chunk有页码与股票；
- 固定查询能召回正确标的；
- Top K不跨股票；
- 引用能回到PDF页面；
- 重建不会误删其他Collection。

## 8. 第二阶段增强

- 章节识别；
- Hybrid Search；
- Reranker；
- 观点/主题结构化抽取；
- 跨机构共识和分歧；
- Retrieval评测集扩展；
- 文档更新和版本策略。

## 9. 已确认与待审核决策

- 已确认：第一步不加入Reranker，先得到召回基线；
- 已确认：第一步继续使用现有6份研报，评测稳定后再扩展；
- 报告日期缺失时是否允许索引？建议允许但增加`date_unknown`质量标记。
