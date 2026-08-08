# Step 10 测试报告

## 1. 单元与故障注入

最终RAG镜像内运行`python -m unittest discover -s tests -q`：

- 69项测试全部通过；
- 覆盖领域模型、数据质量、行情/财务采集、工具、RAG、Planner、Executor、Reporter、Validator、API和评测评分器；
- 存在1条Starlette TestClient第三方弃用Warning，不影响当前功能；
- 五类显式故障注入全部通过。

| 故障 | 预期结果 | 实际 |
|---|---|---|
| 行情空数据 | `MARKET_DATA_EMPTY` | Pass |
| Milvus不可用 | `REPORT_SEARCH_UNAVAILABLE` | Pass |
| 模型非法JSON | 明确解析失败并进入既有降级/失败边界 | Pass |
| 工具超时 | `TOOL_TIMEOUT` | Pass |
| 伪造Evidence引用 | `CITATION_UNKNOWN` | Pass |

## 2. Iceberg集成

### 行情

- `market.kline_daily`：1706行；
- 600519、300750各853行，覆盖2023-01-03至2026-07-14；
- 业务键重复0，非法OHLC 0；
- Raw抽样一致10/10。

### 财务

| 表 | 行数 | 重复键 |
|---|---:|---:|
| `financial.income_statement` | 142 | 0 |
| `financial.balance_sheet` | 140 | 0 |
| `financial.cash_flow` | 138 | 0 |
| `financial.metrics` | 142 | 0 |

Raw抽样一致10/10。600519覆盖102个报告期，300750覆盖40个报告期。

## 3. Milvus集成

- 6份PDF、30页、88个Chunk；
- Metadata完整88/88；
- BGE维度512；
- Collection实体88，幂等运行新增0；
- 跨股票错误0；
- 600519固定查询Top 1为华鑫证券第2页；
- 300750固定查询Top 1为交银国际证券第1页。

## 4. API E2E

| 路径 | Run ID | Evidence | 结果 | 耗时 |
|---|---|---:|---|---:|
| Market | `f961d80b464749c38533ac7c44fafd67` | 2 | Pass | 12313ms |
| Report | `605baf9f597a4d0fbaf1767a47e57419` | 5 | Pass | 29266ms |
| Comprehensive | `af6e52db6bfd4cb09bb647cf84679cbb` | 7 | Pass | 9695ms |

三条均为HTTP 200、`success=true`、`planner_source=model`、报告完成且确定性校验通过。

## 5. 安全与构建

- 工作区及Artifact密钥特征匹配0；
- App最近1000行日志密钥特征匹配0；
- `.env`不进入镜像或文档；
- 本地包安装使用`--no-build-isolation`，避免重复联网下载构建工具；
- 最终App确认可导入`pymilvus`和`sentence_transformers`。
