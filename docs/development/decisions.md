# 架构决策

## LangChain与LangGraph

采用LangChain作为模型、Tool和Retriever兼容层，LangGraph作为状态化编排层。Harness、Evidence和领域模型保留
为项目能力，避免业务语义依赖单一框架。

## PostgreSQL与Redis

PostgreSQL保存Job、租约、事件、Checkpoint和最终事实。Redis只承担限流、热索引、通知和并发协同；Redis
不可用不能导致已完成结果丢失。

## 单Agent、固定团队与动态团队

根据公开Benchmark选择运行路径，而不是默认使用多Agent。动态团队只在复杂算术和表格文本混合任务中启用。

## Iceberg而非ClickHouse

当前工作负载是日线、财务和中长期批分析。Iceberg提供Snapshot、Schema演进和增量批处理，足以满足数据底座。
没有稳定的高频瞬时数据源前不引入ClickHouse。

## 不引入Ray

系统以外部模型API、受控Tool和异步Job为主，没有大规模本地模型推理或分布式Python计算需求。Spark负责批量
数据处理，Kubernetes负责服务部署，因此暂不增加Ray。

## MCP

Tool Schema保持可适配MCP，但没有真实外部MCP消费者前不实现独立Server。未来适配器必须复用现有Policy、
Budget、身份和Evidence边界。
