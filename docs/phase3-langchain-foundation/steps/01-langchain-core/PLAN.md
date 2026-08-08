# Step 01 — LangChain核心接口改造

## 目标

一次完成模型、结构化输出、Tool和Message的LangChain化，使LangChain成为Agent开发基础接口，
同时保持现有业务流程和Gateway治理不变。

## 实施内容

1. 固定与现有LangGraph、Pydantic和DeepSeek兼容的LangChain依赖版本；
2. 建立集中式 `integrations/langchain` 适配模块；
3. 使用LangChain ChatModel/Runnable接入DeepSeek Flash和Pro；
4. 将规划、报告和上下文摘要改造成Prompt + Runnable + Structured Output；
5. 保留ModelGateway的预算、重试、幂等、Usage和审计；
6. 将FinancialTool包装为StructuredTool，Pydantic输入模型作为 `args_schema`；
7. StructuredTool必须调用ToolGateway，不直接访问底层工具；
8. 将Tool结果映射为ToolMessage的 `content + artifact`；
9. 在Graph State中加入标准Message轨迹，同时保留Plan、Evidence、Budget等领域字段；
10. 保留现有依赖感知Executor，不强行用普通ToolNode替代DAG调度；
11. 增加临时运行开关，便于与当前已跑通路径比较和回退。

## 验证

只进行一条规划—行情Tool—Evidence—报告的冒烟运行，确认：

- DeepSeek能通过LangChain调用；
- Structured Output能生成Pydantic对象；
- StructuredTool实际经过ToolGateway；
- ToolMessage artifact不丢失原始结果；
- 原API返回结构不变。

本Step不运行全量Regression和稳定性测试。

## Gate 01

- ChatModel/Runnable、Structured Output、StructuredTool和Message已进入新路径；
- Model/Tool均不存在绕过Gateway的调用；
- 冒烟链路可运行；
- 未修改数据底座和报告业务规则。
