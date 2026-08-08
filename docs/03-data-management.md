# 03 数据管理设计

## 1. 目标

数据管理不仅是“写入Iceberg”，还包括数据源登记、采集批次、标准化、质量、幂等、版本、血缘和生命周期。Agent只消费通过质量门的数据。

## 2. 数据分级

| 等级 | 含义 | 可否进入正式Evidence |
|---|---|---|
| Raw | 数据源原始返回或PDF | 否 |
| Standardized | 字段、类型和单位统一 | 条件允许 |
| Curated | 去重、质量校验、口径冻结 | 是 |
| Derived | 通过确定性公式计算的指标 | 是 |
| Simulation | Mock/实验数据 | 否 |

## 3. 行情数据链路

```text
AkShare stock_zh_a_hist
→ Raw DataFrame
→ 字段映射/类型转换
→ 复权口径标记
→ 质量规则
→ 业务键去重
→ Iceberg market.kline_daily
→ Market Tool
```

业务键：`stock_code + trade_date + adjust_type`。

第一版默认前复权用于连续收益和技术指标；如果同时保存不复权数据，必须在表和Evidence中显式携带`adjust_type`，禁止跨口径拼接。

## 4. 财务数据链路

```text
AkShare报表接口
→ 原始字段快照
→ 中文字段映射
→ 报告期/公告日标准化
→ 单位与空值处理
→ 三张报表Iceberg表
→ 确定性财务指标
```

需要保留：数据源字段名、标准字段名、单位、报告期、公告日、采集时间。不得把`0`与`缺失`混为一类。

## 5. 研报数据链路

PDF原文件为Raw；页面文本和Chunk为Standardized；通过股票、机构、日期和页码校验的索引记录为Curated。Milvus只保存检索所需内容，PDF仍是最终来源。

## 6. Iceberg表管理

第一步采用SQLite Catalog + `file://` Warehouse，保持与旧项目已验证方案一致。

原则：

- 单写者，避免SQLite Catalog并发写；
- API进程只读，采集任务单独执行；
- 按批次或股票聚合后append，避免逐行写小文件；
- 数据规模较小时按年份分区，不按股票过度分区；
- Schema变化必须显式迁移；
- 每次采集记录snapshot ID和batch ID。

## 7. 数据质量规则

### 行情

- `high >= open/close/low`；
- `low <= open/close/high`；
- 价格、成交量、成交额非负；
- 交易日不可重复；
- 股票代码为六位数字；
- 日期范围内缺失交易日产生warning；
- 复权类型必须属于白名单。

### 财务

- 报告期合法；
- 同一公司/报告期/报表类型唯一；
- 单位明确；
- 关键恒等式只做容差校验，不直接修正数据；
- 异常值进入质量报告。

### 研报

- PDF可打开；
- 至少提取一个有效页面；
- Chunk必须绑定报告和页码；
- 股票实体与文件元数据一致；
- 空Chunk不入库。

## 8. 元数据与血缘

每个采集批次记录：

```text
batch_id
source_name/source_endpoint
requested_range
started_at/finished_at
input_count/output_count/rejected_count
target_table/snapshot_id
status/error_summary
code_version/config_version
```

Evidence的locator必须能够定位到Iceberg表+业务键/查询ID，或PDF+页码+chunk ID。

## 9. 生命周期

- Raw API响应在开发阶段按采集批次保存为Parquet，后续可根据存储成本设置保留期；
- Curated Iceberg数据长期保存；
- 质量报告与批次元数据长期保存；
- Milvus索引可以重建，不视为唯一事实来源；
- Simulation数据使用独立namespace，可定期清理；
- 第二步再增加Compaction、Snapshot Expiration和归档策略。

## 10. 第一步交付

- `market.kline_daily`及批次元数据；
- 至少两只股票三年数据；
- 数据质量报告；
- 研报Curated Metadata；
- Repository只读取通过质量门的数据。

## 11. 已确认与待审核决策

- 已确认：Raw API响应开发阶段按批次保存Parquet；
- 已确认：第一阶段只保存前复权日线；
- 第一步是否建立独立`metadata` Iceberg namespace？
- 已确认：质量失败采用行级隔离，正常行入库，批次状态为Warning。
