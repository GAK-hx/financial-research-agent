# 第一阶段技术总结

## 1. 完成目标

第一阶段完成了一个面向A股日线及中长期研究的、基于真实数据和Evidence约束的单次研究Agent闭环：

```text
用户问题
→ Query Interpreter
→ QuerySpec
→ 模型Planner / 规则降级
→ AnalysisPlan DAG
→ Plan Validator
→ 只读Tool Executor
→ ToolResult
→ Evidence Builder
→ Evidence-only Reporter
→ Report Validator
→ ResearchReport + Evidence + Validation + Timings
```

系统不是自由聊天机器人，也不是交易Agent。模型负责问题理解、有限规划和报告表达；数据查询、指标计算、权限、调度、错误、引用和数字校验由程序控制。

## 2. 框架与技术路线

### Agent框架

第一阶段没有把LangGraph、CrewAI或AutoGen作为领域核心依赖，而是实现了框架无关的轻量Agent编排：

- Pydantic强类型领域模型；
- 自研Query Interpreter与有限DAG Planner；
- Tool Registry白名单；
- Plan Validator；
- 基于`asyncio`的并行DAG Executor；
- Run/Working/Evidence Memory；
- Evidence-only Reporter；
- Entity/Date/Citation/Attribution/Numeric Validator；
- 最多一次报告修订；
- 规则Planner安全降级。

这不是“没有框架”，而是把编排核心建立在稳定的领域接口上。未来可以替换模型SDK或外部编排框架，但不能绕过Plan、Tool、Evidence和Validation边界。

### 模型接入

- 模型：`deepseek-v4-flash`；
- 协议：DeepSeek官方OpenAI兼容API；
- 项目内部Adapter：`openai_compatible`；
- Planner Prompt：`planner_v2`；
- Reporter Prompt：`report_v2`；
- JSON结构化输出；
- 模型没有数据库连接、任意SQL、Shell或Python执行能力。

## 3. 技术栈

| 板块 | 技术 |
|---|---|
| 语言/运行时 | Python 3.11、`asyncio` |
| API | FastAPI、Uvicorn、HTTPX |
| Schema/配置 | Pydantic v2、pydantic-settings |
| Agent编排 | 自研Query Interpreter、Structured Planner、DAG Executor、Validator |
| 模型 | DeepSeek V4 Flash，OpenAI兼容HTTP Adapter |
| 行情/财务数据源 | AkShare |
| 表格计算 | Pandas、NumPy、PyArrow |
| 数据湖表 | Apache Iceberg、PyIceberg |
| Iceberg Catalog | SQLite Catalog（第一阶段） |
| PDF解析 | PyMuPDF |
| Embedding | BAAI/bge-small-zh-v1.5、sentence-transformers、CPU Torch |
| 向量数据库 | Milvus Standalone、etcd |
| 测试 | unittest；Docker内运行 |
| 部署 | Docker、Docker Compose、Compose Profiles、Named Volumes |

未引入ClickHouse、Kafka/Flink、HDFS、MinIO、Kubernetes和多Agent框架，因为当前数据源与日线研究范围不需要这些组件。

## 4. 数据管理

### 行情域

- 两只股票：600519、300750；
- AkShare前复权日线；
- `market.kline_daily` Iceberg表；
- Raw响应、批次元数据、质量结果和异常隔离；
- 增量采集、业务键去重和幂等重跑；
- 1706行，两股各853行，覆盖2023-01-03至2026-07-14；
- 重复业务键0、非法OHLC 0、Raw抽样10/10一致。

### 财务域

- Raw三张完整报表；
- Curated：利润表、资产负债表、现金流量表和指标表；
- 562行，重复键0，Raw抽样10/10一致；
- 支持营收、归母净利润、同比、毛利率、资产负债率、经营现金流、ROE；
- 来源历史公告日期不满足严格时点回测要求，因此明确不支持财务时点回测。

### 研报域

- 6份PDF、30页、88个Chunk；
- 500字符、50字符重叠；
- 保留股票、机构、标题、日期、页码和Chunk ID；
- BGE 512维Embedding；
- Milvus Collection：`research_reports_v1`；
- 强制股票过滤，跨股票误召回0；
- 索引幂等，重跑新增0。

## 5. 工具与Evidence

正式Registry公开4个只读工具：

1. `market_query`：按股票和日期查询日线；
2. `indicator_calculator`：确定性计算收益率、波动率、MA5/MA20、最大回撤、相对成交量和区间高低；
3. `financial_query`：查询标准化财务指标；
4. `report_search`：按股票过滤检索页级研报Chunk。

每个成功Tool Result转换为Evidence，携带：

- 当前`run_id`隔离的Evidence ID；
- 股票和Evidence类型；
- 结构化数据与可读Statement；
- Iceberg/Milvus/Calculation Locator；
- Snapshot、页码、公式版本和观测时间。

报告的每个Claim必须引用当前Run Evidence；模型不能直接创建正式Evidence。

## 6. 可靠性与安全

- Plan最多6任务、工具最多8次、并行最多4；
- Run总预算60秒；
- 单工具有限超时和最多2次临时错误重试；
- Planner失败使用规则计划；
- Reporter失败明确返回失败，不用模板冒充模型报告；
- 报告最多修订一次；
- 模拟数据域不能进入正式Registry；
- 模型输出必须经过Pydantic和确定性Validator；
- 日志递归脱敏；代码、Artifact和日志密钥扫描均为0。

## 7. API与可观测性

- `GET /health`：配置、Iceberg和Milvus健康；
- `GET /tools`：公开只读工具Schema；
- `POST /analyze`：返回Plan、工具状态、Evidence、Report、Validation、Timings、模型/Prompt/Tool版本；
- `run_id`贯穿执行、Evidence、错误、日志和Artifact；
- 结构化JSON日志记录阶段与工具耗时。

## 8. Docker部署

### 常驻服务

```text
app       FastAPI + Agent编排 + Iceberg查询 + BGE查询
milvus    研报向量索引
etcd      Milvus元数据
```

### 一次性任务

```text
data-bootstrap
market-ingest
financial-ingest
rag-index
evaluation
```

### Compose Profile

- 默认：App、Milvus、etcd；
- `ingestion`：数据初始化与行情/财务采集；
- `rag`：研报索引和审计。

### Volume

- `lake_data`：Iceberg Warehouse与SQLite Catalog；
- `milvus_data`：向量数据；
- `etcd_data`：Milvus元数据；
- `model_cache`：Hugging Face模型缓存；
- `artifacts`：脱敏演示、评测和审计产物；
- 研报目录只读挂载。

资源限制：App 900MiB、Milvus 1800MiB、etcd 256MiB。最终快照分别约461.4MiB、638MiB和48.59MiB。

## 9. 测试与评测

- 69项单元、集成边界和故障注入测试通过；
- 五类故障：空数据、Milvus不可用、非法模型JSON、工具超时、伪造引用；
- 真实Iceberg、Milvus和三条API E2E通过；
- `phase1_eval_v1`共20题；
- Intent、工具、参数、引用和数字均18/18；
- 含2个非法输入的Task Success为20/20；
- 有效题P50 9.185秒、P95 15.293秒；
- 当前固定链路36次模型调用。

20题在首轮后用于确定性缺陷修复，因此最终100%是回归结果，不是未见问题上的泛化准确率。

## 10. 第一阶段边界

尚未实现：

- 跨进程Run持久化与恢复；
- 异步Job/Worker；
- 暂停、继续、取消；
- Session/长期记忆；
- Token、费用和工具预算统一记账；
- Provider/Tool Gateway治理；
- Checkpoint、租约和多Worker并发；
- 独立未见Holdout；
- 完整Agent Harness。

这些内容进入第二阶段。
