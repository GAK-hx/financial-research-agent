# 第二阶段技术交付说明

## 1. 运行架构

```text
Client
  → FastAPI Job API
  → PostgreSQL Job Queue / Lease
  → Worker
  → LangGraph StateGraph + AsyncPostgresSaver
  → Model/Tool Gateway
  → Iceberg / Milvus
  → Evidence
  → Report Validator
  → Completion Checker
  → Result / Events / Trace
```

LangGraph不是整个Harness。它提供图执行、Checkpoint和恢复；项目在其外实现金融领域的
权限、预算、Memory、Evidence和验收规则。

## 2. 关键模块

| 模块 | 责任 |
|---|---|
| `orchestration/` | QuerySpec、Plan、StateGraph、DAG校验和执行 |
| `skills/` | 版本化Skill、选择、组合、审核与Run快照 |
| `governance/` | Gateway、Policy、事务Budget、Completion |
| `memory/` | Scope隔离、TTL、显式Preference、Context构建与压缩 |
| `tools/` | 只读行情、指标、财务、研报检索 |
| `reporting/` | Evidence-only报告生成和逐Claim校验 |
| `jobs/` | PostgreSQL队列、Lease、Worker、取消与恢复 |
| `persistence/` | 业务Store、Checkpoint适配、Alembic和Trace |
| `evaluation/` | 冻结数据集、评分、稳定性与A/B |

## 3. 模型与Harness分工

模型可以：

- 理解问题；
- 在可见Schema中规划任务；
- 根据当前Evidence生成或修订报告。

模型不可以：

- 直接访问Iceberg、Milvus或PostgreSQL；
- 运行SQL、Shell或Python；
- 增加未授权Tool或未知参数；
- 绕过预算、Memory Scope或报告校验；
- 自行把失败终态改为成功。

Harness会归一化真实取数参数，使股票、日期、复权、研报查询和Top-K可复现。模型仍决定
需要的任务类型和依赖图，不拥有数据访问权。

## 4. 当前技术栈

- Python 3.11、FastAPI、Pydantic；
- LangGraph StateGraph、AsyncPostgresSaver；
- PostgreSQL 17、SQLAlchemy、Alembic；
- PyIceberg、PyArrow、AkShare；
- Milvus、BGE Embedding、PyMuPDF；
- DeepSeek OpenAI-compatible HTTP适配；
- Docker Compose。

## 5. 交付状态

- Phase 1受控研究闭环：完成；
- Phase 2 LangGraph Harness九步工程实现：完成；
- Gate 01—08：通过；
- Gate 09工程验收：通过；
- 用户最终人工签字：待确认。

## 6. 后续候选

按价值排序：

1. 扩充正式股票池、研报和财务数据覆盖；
2. 为Flash建立更短、更严格的报告Schema或确定性报告模板；
3. 支持受控Replan，但必须引入单独预算和循环上限；
4. 增加Checkpoint和Artifact定期清理任务；
5. 在任务量增长后评估专用队列中间件；
6. 有稳定实时数据源后再评估Kafka、Flink和ClickHouse；
7. 增加认证、RBAC和外部Secret Manager后再讨论生产多租户。

