# Step 03 — 行情日线链路

## 目标

将AkShare真实日线稳定、幂等地写入`market.kline_daily`，成为行情和指标Evidence的数据源。

## 依赖

- Step 01、02完成。

## 任务

1. 实现股票池配置；
2. 调用`stock_zh_a_hist`并保存source版本；
3. 标准化日期、OHLCV、成交额、换手率和复权类型；
4. 业务键：stock_code + trade_date + adjust_type；
5. 校验OHLC关系、非负值、代码和日期；
6. 首次回填至少两只股票三年数据；
7. 增量读取表内最大交易日并补充缺失日期；
8. 写入前反连接或合并去重；
9. 批量写入Iceberg并记录snapshot/batch；
10. 生成质量报告和失败股票清单；
11. 抽样与原始响应核对；
12. 增加网络失败和重复运行测试。

## 交付物

- 日线采集命令/一次性任务；
- `market.kline_daily`；
- 日线Schema与字段映射；
- ingestion report；
- 增量与幂等测试。

## 验收标准

- 600519、300750至少三年日线；
- 抽样10行与源一致；
- 重跑不产生业务重复；
- 异常行被隔离；
- 能按股票和日期读取；
- 数据截止日明确。

## 不包含

- 真实分钟行情；
- Kafka/Flink；
- ClickHouse。

