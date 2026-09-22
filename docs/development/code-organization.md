# 代码结构与重构边界

## 当前稳定边界

```text
src/financial_research_agent/
├── orchestration/   LangGraph状态图与执行节点
├── governance/      Policy、预算和完成条件
├── tools/           类型化只读Tool
├── skills/          版本化能力包
├── retrieval/       Snapshot、Artifact与single-flight
├── rag/             文档解析、索引和混合检索
├── memory/          记忆、上下文和压缩
├── reporting/       报告、事实抽取与校验
├── jobs/            队列、租约和Worker
├── persistence/     PostgreSQL与Checkpoint
├── shared_state/    Redis热状态
├── financial/       财务采集与标准化
├── market/          行情采集与标准化
└── risk/            财务风险领域与公开Benchmark
```

这些目录之间通过Pydantic模型和显式服务接口协作。API不能直接拼接SQL，Agent节点不能绕过Tool Gateway，
Redis不能成为Job事实来源。

## `risk/`领域包

财务风险领域按职责拆分，在线运行代码、离线数据处理、公开评测和部署验证不混放：

```text
risk/
├── domain/          风险模型、指标Registry和披露事件
├── data/            PIT、Schema、标准化、公告、审计和特征管道
├── agents/          Supervisor、团队运行和公共分析产物
├── benchmarks/      FinanceBench、FinQA、TAT-QA、V4FinBench
├── validation/      数据、Agent、缓存、Spark和Kubernetes验证
└── *.json           版本化指标定义与小型确定性样例
```

`risk.__init__`只导出稳定的领域类型；数据CLI、Benchmark runner和验证程序使用完整模块路径调用，避免把
内部实现误当成公共API。`scripts/validation`保存跨服务集成与容量验证脚本，不参与在线Worker导入。

## 命名规范

- 模块和脚本使用功能名，不使用开发批次或日期编号；
- Artifact目录按`risk_data`、`agent_benchmarks`、`runtime_validation`分类；
- 验证模块直接描述对象，例如`data_foundation`、`agent_benchmarks`和`spark_iceberg`；
- 文档只描述当前设计、使用方法、实测结果和限制，不保留开发进度流水账。
