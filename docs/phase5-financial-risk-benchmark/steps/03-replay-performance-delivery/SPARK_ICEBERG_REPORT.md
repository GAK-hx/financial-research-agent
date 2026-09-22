# 03-C Spark / Iceberg 增量与恢复报告

## 结论

03-C 已在 Docker 中完成。测试使用明确标记的500万行合成财务指标，不参与风险正确率或公开Benchmark。
PySpark 负责生成、读取、过滤和聚合，PyIceberg 负责原子提交、Snapshot、动态分区覆盖和文件裁剪。

所有验收项通过：

- 500万行输入完整物化；
- 仅50/1000家公司变化时，增量读取25万行，较全量减少95%；
- `issuer_group=0` 出现在Spark物理计划的分区过滤中；
- Iceberg全表计划20个文件，单公司组只计划1个文件，减少95%；
- 错误Schema提交失败后Snapshot保持不变；
- 修正后恢复提交生成新Snapshot；
- 同一个增量批次再次执行后业务主键重复0；
- 未受影响分区数值变化0。

## 数据规模与资源

| 项目 | 结果 |
|---|---:|
| 合成行数 | 5,000,000 |
| 公司数 | 1,000 |
| 公司组 | 20 |
| 年份 | 10 |
| 指标 | 12 |
| Docker CPU上限 | 4 |
| Docker内存上限 | 6 GiB |
| 压缩源文件 | 约8.2 MiB |
| Iceberg聚合行 | 120,000 |

源文件体积很小是因为合成列高度规则且Gzip压缩率高，不能据此推断真实财务数据压缩率。

## 全量与增量

| 模式 | 输入行 | 输出行 | 当前容器耗时 |
|---|---:|---:|---:|
| 全量 | 5,000,000 | 120,000 | 8.066秒 |
| 增量（5%公司） | 250,000 | 6,000 | 2.121秒 |

验收依据是扫描边界和输出一致性，耗时仅作当前机器诊断，不作为生产SLA或简历数字。正式简历如果需要
性能表述，应在端到端环境稳定后采用更保守的相对值。

## 分区设计

合成源按 `issuer_group + report_year` 物理分区；Iceberg聚合表按 `issuer_group` 做identity分区。
每组包含50家公司，因此单组增量自然覆盖5%公司。变化批次只重算并动态覆盖一个公司组，同时保留其他19组。

当前Iceberg聚合表20个数据文件，恰好每个业务分区一个文件。文件都小于64 KiB，是因为聚合表只有12万行，
但不存在同分区数百个碎片文件，因此本轮不做为了展示而做的压缩。生产策略应按“同分区文件数量和总字节”
触发整理，而不是只看单文件阈值。

## 失败恢复

测试先提交缺少必填 `batch_id` 的Arrow表。PyIceberg在Schema校验阶段拒绝提交，当前Snapshot不变；随后
使用完整Schema执行动态分区覆盖并成功生成新Snapshot。再次执行相同增量批次后：

- 总行数仍为120,000；
- 业务主键重复为0；
- 未变化分区值变化为0。

这证明失败不会暴露部分结果，任务可以从同一批输入重跑。它不是多节点生产故障演练；Worker驱逐、Job重试
和滚动更新属于03-D。

## 产物

- 原始结构化结果：`artifacts/phase5_step03/spark_iceberg_v1/report.json`；
- 人读结果：`artifacts/phase5_step03/spark_iceberg_v1/report.md`；
- Iceberg Catalog与Warehouse：`artifacts/phase5_step03/spark_iceberg_v1/iceberg/`；
- 合成Parquet源：`artifacts/phase5_step03/spark_iceberg_v1/synthetic_source/`。
