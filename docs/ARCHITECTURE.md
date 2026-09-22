# 组件架构

## 请求链路

```text
Client
  → Spring Gateway（可选）
  → FastAPI Job API
  → PostgreSQL Queue
  → Python Worker
  → LangGraph Runtime
  → Tool / Skill / Evidence / Evaluator
  → RiskAssessmentArtifact / UserReport
```

## 数据链路

```text
AkShare / 公告 / 研报 / 网络资料
  → 原始响应与观察时间
  → 标准化事实与质量检查
  → Iceberg Snapshot
  → PIT特征与风险候选
  → Agent取证与报告
```

## 主要组件

| 组件 | 技术 | 职责 |
|---|---|---|
| 外部入口 | Java 21、Spring Boot、WebFlux | API Key/JWT认证、身份头清洗、Redis限流、SSE代理 |
| 任务API | FastAPI、Pydantic | 创建、查询、取消和恢复任务，提供Trace与事件接口 |
| Agent运行时 | LangChain、LangGraph | 模型与Tool接口、状态图、条件路由、并行执行、Checkpoint |
| 受控执行 | Harness、Policy、Budget Ledger | Tool白名单、参数校验、预算、超时、重试和终态控制 |
| 风险分析 | Supervisor、专业子Agent、Evaluator | 候选复核、取证、反证、计算和报告校验 |
| 数据平台 | PyArrow、PyIceberg、Spark | 标准化、PIT特征、Snapshot、批处理和增量计算 |
| 文档检索 | PyMuPDF、Milvus、Elasticsearch | 研报解析、向量与关键词召回、网络内容版本管理 |
| 持久化 | PostgreSQL | Job、租约、事件、Checkpoint、Memory和分析事实 |
| 热状态 | Redis | 限流、并发槽位、single-flight索引和事件通知 |
| 部署 | Docker Compose、Kustomize、Kubernetes | 本地运行、服务编排和容器资源管理 |

## Agent边界

模型负责问题理解、有限规划、证据综合和自然语言表达。程序负责真实数据访问、金融计算、权限、预算、并发、
校验和最终写入。模型只能调用Pydantic类型化的只读Tool，不能直接执行SQL、Shell或任意Python。

Context Builder按节点预算组合问题、计划、Tool结果、记忆和Evidence。上下文可以裁剪或摘要，但原始Evidence
不会被摘要覆盖。会话记忆按tenant、user和session隔离，公共分析产物不携带用户身份。

## 代码结构

```text
src/financial_research_agent/
├── orchestration/   LangGraph状态图与执行节点
├── governance/      Policy、预算和完成条件
├── tools/           类型化只读Tool
├── skills/          版本化Skill
├── retrieval/       Snapshot、Artifact与single-flight
├── rag/             研报解析与混合检索
├── memory/          会话记忆、上下文与压缩
├── reporting/       报告生成与校验
├── jobs/            任务队列、租约与Worker
├── persistence/     PostgreSQL与Checkpoint
└── risk/
    ├── domain/      风险模型与指标定义
    ├── data/        PIT数据、质量与特征管道
    ├── agents/      Supervisor与团队运行
    ├── benchmarks/  公开Benchmark适配与评分
    └── validation/  数据、缓存、Spark与部署验证
```
