# 分析数据与计算链路

## 1. 设计目标

股票分析中的数字由确定性代码产生，LLM 负责理解问题、选择受控能力和组织报告。在线 Agent 不执行
任意 SQL/Python，也不在 Prompt 中临时计算因子。

## 2. 数据边界

- 当前正式日线和财务数据只覆盖 `600519`、`300750`；
- 演示股票池 `demo_liquid_a_share@2026.08.v1` 固定 20 只常见 A 股，不代表官方指数；
- 因子批任务为 20 只股票生成完整结果骨架，真实无数据的 18 只写 `missing`，不伪造排名；
- 日线数据可以用于当前技术指标和市场因子；
- 当前财务源没有可靠的历史首次可得时点，只能做最新快照分析，所有基本面因子标记
  `point_in_time_eligible=false`，不得包装成无前视偏差回测。

## 3. 版本化对象

| 对象 | 版本/位置 | 作用 |
|---|---|---|
| 股票池 | `demo_liquid_a_share@2026.08.v1` | 固定成员、选择策略和生效日 |
| Factor Registry | `factor_registry_v1` | 固定公式、字段、窗口、方向、空值和 PIT 资格 |
| Security Master | `metadata.security_master` | 股票名称、交易所和资产类型 |
| 股票池成员 | `metadata.universe_membership` | 股票池版本与成员快照 |
| 因子结果 | `financial.factor_values` | 值、截面排名、覆盖数、输入 Snapshot 和缺失原因 |
| 批次元数据 | `metadata.factor_runs` | Run、引擎、股票池、Registry、数据 Snapshot 和状态 |

## 4. 首批 12 个因子

- 市场域：20/60 日动量、5 日反转、20 日年化波动率、60 日最大回撤、20 日相对成交量、
  20 日 Amihud 非流动性；
- 基本面域：营收增长、归母净利润增长、ROE、经营现金流/归母净利润、资产负债率；
- 市场因子使用前复权日线；财务因子使用最新报告期且明确非 PIT；
- 因子方向和百分位排名由 Spark 计算，在线 Tool 只读 Iceberg 已落湖结果。

## 5. 批处理实现

`factor-batch` Docker Profile 使用 PySpark 4.2 的 `groupBy.applyInPandas` 按股票计算长表因子，使用
Spark Window 生成截面百分位和覆盖数，再由 PyIceberg 批量写入本地 Iceberg 数据湖。Java 由
Debian `default-jre-headless` 提供，批任务固定 `local[2]`、4 个 Shuffle Partition、768 MB Driver，
Compose 总内存限制 1600 MB。

本次实跑：

```text
run_id=66f9005e5657479dbdf9365d11d51312
engine=pyspark-4.2.0+pyiceberg
as_of_date=2026-07-14
universe_size=20
covered_stocks=2
factor_rows=240
status=SUCCESS
```

## 6. 在线分析 Tool

- `technical_analysis`：趋势、均线、动量、波动、回撤、量价和流动性；
- `fundamental_analysis`：增长、ROE、现金流质量和杠杆，并强制返回非 PIT 限制；
- `factor_screen`：读取版本化因子值、排名、覆盖、缺失和 Run Lineage；
- `stock_comparison`：用同一日期和公式比较 2～5 只股票；
- `event_search`：只读取 PostgreSQL 中 ACTIVE 且可追溯到原始来源的事件。

每个计算型 Evidence 都包含 `formula_version` 和 `input_locator`；因子 Evidence 额外包含
Registry、Universe 和 Factor Run；事件 Evidence 包含状态、来源 URL、可用时间和 Raw Locator。

## 7. 已知限制

- 当前截面只有 2 只有真实数据，排名仅是链路演示，不具备投资代表性；
- 财务数据不能用于历史时点回测；
- Event 样例是流水线演示数据，不代表实时新闻；
- 下一步应先增加合法、稳定的数据覆盖和首次披露时间，再增加回测与组合构建。
