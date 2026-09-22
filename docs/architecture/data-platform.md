# 数据与检索平台

## 数据分层

- Raw：原始响应、来源、采集批次、观察时间和错误；
- Standardized Facts：统一主体、报告期、指标、单位和版本；
- Features：版本化PIT特征；
- Candidates：待Agent复核的确定性风险候选；
- Artifacts：绑定数据快照、证据和策略版本的分析结果。

财务事实同时记录来源发布时间和系统观察时间。分析截止日之后才公开或才被系统观察到的数据不能进入当前
特征和Evidence。缺失值保留缺失状态，不填零。

## Iceberg与Spark

PyIceberg管理Schema、Partition、Snapshot和原子提交；Spark用于批量聚合、窗口计算和增量处理。失败任务不会
写入Snapshot，相同批次重跑必须保持业务主键唯一。

当前系统面向日线和中长期分析，Iceberg足以承担分析数据底座，不引入面向高频瞬时查询的ClickHouse。

## 检索

- PyMuPDF解析研报并保留文档、页码、机构和版本；
- Milvus提供向量召回，关键词检索补充实体和数值匹配；
- Elasticsearch保存可选网络文档及其内容版本；
- `RetrievalSnapshot`记录查询、来源、水位、内容版本和依赖；
- 新数据只使受影响的Snapshot和AnalysisArtifact失效。

## 查询、分析与输出分离

相同公司、报告期、截止日和数据版本使用single-flight合并并发工作。公共`RiskAssessmentArtifact`可以跨用户
复用；`UserReport`绑定tenant/user并独立生成。Redis提供短TTL索引，PostgreSQL保存最终版本事实。

## 数据许可

仓库只分发Schema、采集方法、质量规则和不可还原的聚合指标。AkShare接口、研报、公告镜像、Benchmark原始
文件和模型权重均需使用者按各自条款获取，不随Git仓库分发。
