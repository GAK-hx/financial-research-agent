# Step 03 实现证据

## 1. 组件版本

| 组件 | 版本/实现 |
|---|---|
| 模型 | `deepseek-v4-flash`（项目默认） |
| Agent 接口 | LangChain `1.3.14` |
| 状态编排 | LangGraph `1.2.9` |
| 批计算 | PySpark `4.2.0` |
| 数据湖表 | PyIceberg `0.11.1` + 本地 Iceberg Catalog |
| 在线 API | FastAPI `0.141.1` |
| 业务状态/检查点 | PostgreSQL 17 + LangGraph Postgres Checkpointer |
| 研报检索 | Milvus + SQLite FTS5 + RRF |
| 部署 | Docker Compose，分析/主应用/异步 Worker 分 Profile |

Spark 运行版本依据官方文档的 Java 17/21/25 与 Python 3.10+ 边界：
<https://spark.apache.org/docs/latest/index.html>、
<https://spark.apache.org/docs/latest/api/python/getting_started/install.html>。

## 2. 数据审计

```text
market rows: 1706
market stocks: 600519, 300750
market dates: 2023-01-03 .. 2026-07-14
financial rows: 142
financial stocks: 600519, 300750
financial report dates: 1998-12-31 .. 2026-03-31
```

因此 20 只演示股票池只用于验证 Security/Universe/Factor 数据结构；实际截面覆盖始终显示为 2/20。

## 3. Spark 因子实跑

```text
run_id: 66f9005e5657479dbdf9365d11d51312
universe: demo_liquid_a_share@2026.08.v1
registry: factor_registry_v1
as_of_date: 2026-07-14
market_snapshot_id: 979427596024687778
financial_snapshot_id: 3604996605292135954
universe_size: 20
covered_stocks: 2
factor_rows: 240
engine: pyspark-4.2.0+pyiceberg
status: SUCCESS
```

在线 `factor_screen` 实跑覆盖 `600519`、`300750`，并对 `601318` 的两个请求因子返回明确缺失；
因子 Evidence 同时返回 Registry、Universe、Run ID、Snapshot、覆盖数和 PIT 警告。

## 4. 回归

- Docker 全量发现 161 项：141 项通过，20 项因未打开 PostgreSQL 开关而正常跳过；
- PostgreSQL/治理/Memory/Job 集成批次：44 项通过；
- 最终修复后的聚焦批次：36 项通过；
- 新增确定性用例覆盖因子 Registry、技术/基本面计算、意图/Skill/Profile、一次受控补充和
  Evidence 截止日绑定。

## 5. Flash Gate

| 项目 | 结果 |
|---|---|
| Run | `b454673bbac540c99ec14d1639d417cc` |
| 模型 | `deepseek-v4-flash` |
| Skill | `event_impact@1.0.0` |
| 首次 Event Tool | `EVENT_DATA_EMPTY` |
| 受控补充 | 1 次，未扩大股票或日期 |
| 最终 Evidence | 1 条 ACTIVE Event Evidence |
| 模型调用 | 2 |
| 报告修订 | 0 |
| Validation | 通过 |
| Completion | 通过 |
| 开放预算预留 | 0 |

本 Gate 只向模型发送用户已允许的演示 Event Evidence。行情、财务和因子本轮保持本地确定性验证；
若以后要做真实综合模型 Gate，需要另行确认这些数据的外发边界。
