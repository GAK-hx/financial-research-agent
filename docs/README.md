# Morshan 文档

文档按系统职责组织，不记录开发阶段、临时计划或对话过程。

## 架构

- [系统总览](architecture/overview.md)：职责边界、请求链路与主要组件；
- [Agent运行时](architecture/agent-runtime.md)：LangChain、LangGraph、Harness、Tool、Skill与Evidence；
- [数据与检索平台](architecture/data-platform.md)：Point-in-Time数据、Iceberg、Spark、RAG与缓存；
- [服务与部署](architecture/service-runtime.md)：API、Worker、PostgreSQL、Redis、Gateway与Kubernetes。

## 评测

- [评测方法](evaluation/methodology.md)：公开Benchmark、数据隔离和指标口径；
- [模型与Agent结果](evaluation/results.md)：FinanceBench、FinQA、TAT-QA与V4FinBench；
- [工程验证](evaluation/engineering-validation.md)：回放、缓存、增量计算和故障恢复。

## 运维

- [本地开发与Docker](operations/local-development.md)；
- [Kubernetes部署](operations/kubernetes.md)；
- [安全与发布](operations/security.md)。

## 开发

- [代码结构与重构边界](development/code-organization.md)；
- [架构决策](development/decisions.md)。

## 参考

- [财务指标口径](reference/financial-metrics.md)；
- [市场指标口径](reference/market-indicators.md)；
- [SSH空配置模板](security/SSH_SETUP.md)。

运行产物、第三方数据、真实研报和私有评测集不进入Git。公开文档中的数字均来自公开Benchmark或明确标记的
工程测试，不混用业务演示数据与准确率结论。
