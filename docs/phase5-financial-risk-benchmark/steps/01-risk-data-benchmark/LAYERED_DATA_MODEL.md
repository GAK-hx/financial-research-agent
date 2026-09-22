# 分层数据模型 v1

## 1. 总体流向

```text
ODS 原始响应/PDF
  -> DWD risk_fact_pit
  -> DWS risk_feature_pit
  -> ADS risk_candidate
                  \
metadata.risk_label -> metadata.issuer_risk_bench_case
```

Agent 不读取 ODS。Tool 只能查询通过质量检查的 DWD/DWS/ADS；被拒绝记录进入隔离区并保留批次、原因和
重放入口。

## 2. ODS

沿用 `RawBatchStore` 按 `dataset/batch_id` 保存原始 Parquet；PDF 使用本地只读挂载。Manifest 至少记录
来源、接口、参数、抓取时间、内容哈希、AkShare 版本、文件大小和逻辑发布日期。ODS 不覆盖旧批次。

## 3. DWD：`financial.risk_fact_pit`

使用长表保存标准化事实，业务键为：

`issuer_id + report_period + metric_code + source_published_at + revision_no + source_record_id`

同时保存来源发布时间与系统观测时间，以支持双时间边界；`availability` 独立于 `value`，不允许用空值或
0 混淆未披露、来源不支持和质量拒绝。

## 4. DWS：`financial.risk_feature_pit`

一行代表一个公司—报告期—截止日—快照下的一个版本化风险指标。业务键为：

`issuer_id + report_period + as_of_date + data_snapshot_id + metric_code + metric_version`

`source_fact_ids_json` 保存参与计算的事实 ID；窗口指标保存 `periods_used`。任何输入事实晚于截止日时，
该特征必须拒绝生成而不是标记为低风险。

## 5. ADS：`financial.risk_candidate`

保存确定性规则或统计基线生成的候选，不保存模型自由文本。候选包含类别、状态、规则分数、触发指标和
证据 ID。Step 02 的 Supervisor 只读取候选和受控 Evidence，不重新解释 ODS。

## 6. 标签与 Benchmark

- `metadata.risk_label`：同一 Case 的独立标注行，保留 annotator、版本和依据；
- `metadata.issuer_risk_bench_case`：冻结问题、快照、时点、Gold 标签与 Evidence 清单；
- 开发集可以导出到仓库内；私有 Holdout 只在外部路径保存，运行时由环境变量挂载；
- 后续确认事件日期必须晚于分析截止日，否则会被 Schema 拒绝。

## 7. 幂等、快照和变更

- ODS 以内容哈希和批次保留不可变原始输入；
- DWD 按完整业务键去重，不用“公司+报告期”覆盖修订；
- DWS/ADS 以数据快照和 Registry 版本隔离重算结果；
- Schema 破坏性变更建立新表或新字段版本，不原地改写历史 Benchmark；
- 评测产物记录 Iceberg Snapshot、Registry、映射和 Case 数据集哈希。
