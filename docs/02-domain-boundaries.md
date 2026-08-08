# 02 领域划分

## 1. 为什么需要分域

数据源、Agent状态、研报知识和最终报告具有不同的更新频率、质量规则和生命周期。如果全部混在一张表或一个`state`对象中，会导致数据口径、记忆语义和工具权限无法控制。

## 2. 业务域

### Market Domain

负责日线行情、交易日、复权口径、收益和价格区间。核心实体：`DailyBar`、`TradingCalendar`、`MarketSnapshot`。

### Financial Domain

负责财务报表、报告期、字段标准化和财务指标。核心实体：`FinancialStatement`、`FinancialMetric`、`ReportingPeriod`。

### Research Document Domain

负责研报、机构、页码、章节、Chunk和检索结果。核心实体：`ResearchReportDocument`、`ReportChunk`、`RetrievalHit`。

### Indicator Domain

负责确定性计算逻辑及口径。核心实体：`IndicatorDefinition`、`IndicatorValue`、`CalculationTrace`。

### Evidence Domain

统一封装来自不同域的可引用事实。核心实体：`Evidence`、`SourceReference`、`EvidenceSet`。

### Agent Execution Domain

负责任务计划和运行过程。核心实体：`ResearchRequest`、`QuerySpec`、`AnalysisPlan`、`AnalysisTask`、`ToolResult`、`RunState`。

### Reporting Domain

负责报告、结论、风险和引用。核心实体：`ResearchReport`、`ReportSection`、`ReportClaim`、`Citation`、`ValidationResult`。

## 3. 数据域/Namespace建议

```text
Iceberg
├── market.kline_daily
├── market.trading_calendar        可后置
├── financial.balance_sheet
├── financial.income_statement
├── financial.cash_flow
├── financial.metrics
├── metadata.ingestion_runs
├── metadata.data_quality_results
└── simulation.kline_1min          实验域

Milvus
└── research_reports_v1

应用存储（第二步）
├── agent_runs
├── agent_tasks
├── agent_evidence
├── agent_reports
├── agent_feedback
└── memory_items
```

## 4. 域间依赖方向

```text
Market/Financial/Document/Indicator
                ↓
             Evidence
                ↓
         Agent Execution
                ↓
             Reporting
```

Reporting不能反向修改Evidence；Agent不能修改源数据域；Memory可以引用Evidence，但不能复制后失去来源关系。

## 5. 第一、二步边界

第一步实现所有领域的最小实体，但Agent Execution只处理单次Run。第二步增加持久化的Run、Task、Feedback和Memory实体。

## 6. 已确认边界

- 财务域接入三张Raw报表，Curated层保存三张最小表和基础指标表；
- 第一版股票池覆盖600519、300750；
- 第一版不加入估值指标；
- 来源历史公告日期不满足严格时点回测要求。
