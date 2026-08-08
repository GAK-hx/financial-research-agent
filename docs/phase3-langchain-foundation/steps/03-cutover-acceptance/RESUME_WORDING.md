# 简历与面试口径

当前`简历_use_no_bold.tex`中的项目表述已经与实现一致，无需为了Step 03再次扩大
技术描述。

推荐项目标题：

```text
证据驱动的股票投研 Agent
```

推荐Agent段落：

```text
Agent框架与编排：以LangChain统一ChatModel、StructuredTool、Retriever和结构化
输出接口，基于LangGraph编排问题理解、研究计划、依赖感知取数、证据构建及报告
修复流程；使用PostgreSQL Checkpoint支持任务中断恢复与幂等执行。
```

面试补充：

```text
LangChain/LangGraph提供标准接口、状态图和Checkpoint；项目的优化点是金融领域的
Model/Tool Gateway、Policy/Budget、版本化Skill、隔离Memory、上下文压缩、
Evidence来源链、逐Claim报告校验和Completion Checker。
```

不建议表述：

- “完全自研Agent框架”；
- “LangChain自动保证数据真实性”；
- “模型可以直接操作数据库”；
- “支持实时或分钟行情”；
- “已经支持自动交易”。

