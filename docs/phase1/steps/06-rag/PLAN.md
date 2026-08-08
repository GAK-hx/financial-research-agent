# Step 06 — 研报知识库与检索

## 目标

将已验证的6份PDF升级为可按股票过滤、可回到机构和页码的研报Evidence库。

## 依赖

- Step 01、02完成；
- 研报分块和日期缺失策略已审核。

## 任务

1. 校验6份PDF可打开；
2. PyMuPDF逐页解析并保留页码；
3. 清理空白、明显页眉页脚和重复行；
4. 第一版采用500字符、50重叠分块；
5. 补全股票、机构、标题、日期、页码、chunk ID、source path；
6. BGE向量维度运行时探测；
7. 创建`research_reports_v1`，Schema不匹配明确失败；
8. 使用归一化向量+IP索引；
9. 索引任务支持显式rebuild/skip，不静默删除；
10. Report Search先股票过滤再向量搜索；
11. Top K限制1～10；
12. 命中转换为研报Evidence；
13. 固定查询和页码人工核验。

## 交付物

- PDF解析与Metadata清单；
- Milvus Collection；
- Report Search Tool；
- 固定检索测试；
- 索引统计和已知限制。

## 验收标准

- 6份PDF全部处理；
- 每条chunk有股票、机构、标题、页码；
- 查询不跨股票；
- 两条固定问题召回正确报告；
- 随机5条可定位PDF页面；
- Milvus失败返回结构化错误。

## 不包含

- Reranker；
- Hybrid Search；
- 机构观点结构化抽取。

