# Step 02 Progress

状态：`COMPLETED`　完成度：100%　审核：Review Ready

## 任务

- [x] BaseRetriever与Document
- [x] ToolMessage/Document到Evidence
- [x] Context Middleware/Runnable
- [x] Evidence保护与Context Manifest
- [x] LangGraph Store适配
- [x] Memory治理桥接
- [x] Skill动态Prompt和Tool选择
- [x] Runtime Context与图整理
- [x] 一条增强能力组合冒烟链路

## 实施记录

- 2026-07-28：将`MilvusReportStore`包装为LangChain `BaseRetriever`，统一输出标准`Document`；
- 2026-07-28：建立`RetrievalHit -> Document -> Evidence`双向适配，保留机构、标题、日期、页码、Chunk和Source Locator；
- 2026-07-28：研报`StructuredTool`的`ToolMessage artifact`同时保留完整`ToolResult`和标准`Document`；
- 2026-07-28：将`ContextBuilder`通过`RunnableLambda`接入图节点调用生命周期，保留节点预算、确定性压缩、Evidence保护和Context Manifest；
- 2026-07-28：新增`FinancialMemoryStore`，将LangGraph Store读写桥接到`MemoryManager`，继续复用租户隔离、TTL、版本、删除和敏感信息治理；
- 2026-07-28：将`SkillSelection`映射为模型可见的Skill版本、工具白名单、证据要求和工作流限制；
- 2026-07-28：StateGraph加入`ResearchRuntimeContext`，每次新运行显式注入Tenant/User/Session/Run身份并校验状态范围；
- 2026-07-28：组合冒烟与核心收口回归共7项通过，额外LangChain正式开关主图冒烟成功；
- 2026-07-28：Docker保持停止，PostgreSQL Checkpoint、API/Worker/SSE和生产部署按计划留到Step 03集中验收。

当前任务：已完成并由Step 03集中验收覆盖。
