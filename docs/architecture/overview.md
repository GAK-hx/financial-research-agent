# 系统总览

Morshan是一个企业财务风险分析与证据复核系统。输入是公司、报告期、分析截止日和研究问题，输出是绑定
数据快照、证据与限制的`RiskAssessmentArtifact`。系统只提供研究辅助，不执行交易或下单。

## 核心链路

```text
Client
  → Spring Gateway（可选外部入口）
  → FastAPI Job API
  → PostgreSQL Queue
  → Python Worker
  → LangGraph Runtime
  → Tool / Skill / Evidence / Evaluator
  → RiskAssessmentArtifact / UserReport
```

数据侧链路：

```text
AkShare / 公告 / 研报 / 可选网络来源
  → 原始响应与观察时间
  → 标准化事实与质量检查
  → Iceberg Snapshot
  → PIT特征与风险候选
  → Agent取证与反证
```

## 职责边界

- 模型负责问题理解、有限规划、证据综合和自然语言表达；
- 程序负责数据读取、金融计算、权限、预算、并发、校验和终态；
- 模型只能调用白名单Tool，不能直接访问数据库或执行任意代码；
- 公开分析产物不包含tenant、user或session，最终用户报告严格隔离；
- PostgreSQL保存可靠事实，Redis只保存可重建热状态；
- 动态多Agent按题型选择，不作为所有请求的默认路径。

## 风险范围

系统只覆盖四类相互关联的企业财务风险：偿债与流动性、盈利质量与现金流、资产质量与减值、财务披露与
审计异常。行情、因子、新闻和研报只作为辅助证据，不扩展为短期预测或自动选股系统。

## 主要技术栈

- Python、FastAPI、Pydantic；
- LangChain、LangGraph；
- PostgreSQL、Redis；
- PyIceberg、Spark、PyArrow；
- Milvus、Elasticsearch、PyMuPDF；
- Java 21、Spring Boot、Spring Cloud Gateway；
- Docker Compose、Kustomize、Kubernetes/Kind。
