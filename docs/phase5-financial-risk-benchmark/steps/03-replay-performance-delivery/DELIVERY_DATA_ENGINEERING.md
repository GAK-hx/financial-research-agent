# 数据开发岗位交付说明

## 数据链路

项目按ODS/DWD/DWS/ADS思路管理财务数据：原始响应保留来源和观察时间，DWD形成双时间边界的标准事实，
DWS生成版本化风险特征，ADS生成待Agent复核的风险候选。Iceberg保存Schema、Snapshot和可回放数据，
Spark用于批量分组、窗口和增量聚合。

## Point-in-Time与回放

数据可见性同时满足来源发布时间和系统观察时间。03-A在同一冻结回填批次上重建5个历史截止日，共生成
126,880条特征和39,040条候选，PIT泄漏与主键重复均为0。该结果是source-time backfill replay，
不是对历史系统知识状态的伪造还原。

## 增量与存储

500万行合成数据Gate中，Spark全量聚合输出12万行；50/1000家公司更新时只扫描25万行。Iceberg聚合
表按公司组分区，单组读取从20个计划文件降为1个。错误Schema提交不会生成Snapshot；相同增量批次重跑
后业务主键重复0，未变化分区变化0。

当前聚合表只有20个文件，每个分区一个文件。虽然单文件小于64 KiB，但没有碎片膨胀，因此没有为了展示
“Compaction”而制造无意义任务。生产中应按同分区文件数、删除文件比例和总字节触发整理。

## 服务化数据边界

- PostgreSQL保存Job、Event、租约和最终结果，是任务事实来源；
- Redis保存限流、single-flight和热元数据，可丢失并重建；
- Elasticsearch负责网络文档关键词检索，Milvus负责稠密召回；
- 公共RetrievalSnapshot与AnalysisArtifact可跨用户复用，用户最终文本按tenant/user隔离；
- 任何新增数据只使依赖它的公共分析身份变化，不做全量缓存清空。

## 部署验证与边界

Kind三逻辑节点已完成真实部署、Worker驱逐接管、Redis降级、Gateway更新/回滚和初始化Job幂等验证。
本地集群仍使用RWO共享PVC和临时PostgreSQL/Redis；生产应替换为对象存储、共享Catalog和托管持久化服务。
本地未安装metrics-server，因此不声明已经完成HPA动态扩缩容。
