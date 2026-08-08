# Step 02 — 现有增强能力接入LangChain/LangGraph

## 目标

一次将RAG、数据溯源、上下文、记忆和Skill接入LangChain/LangGraph标准扩展点，
使现有能力成为基础框架之上的金融Agent增强层。

## 实施内容

1. 将MilvusReportStore包装为BaseRetriever并输出Document；
2. 统一Document metadata中的机构、标题、日期、页码、Chunk和Source Locator；
3. 将Document和ToolMessage artifact转换为现有Evidence；
4. 保留Evidence ID、当前Run校验、数字和机构归因检查；
5. 将ContextBuilder接入Middleware或Runnable模型调用前处理；
6. 普通对话历史可使用LangChain摘要，结构化Evidence继续使用确定性压缩和保护；
7. 保留节点级Token预算、Context Manifest和模型摘要失败回退；
8. 为MemoryManager提供LangGraph Store兼容入口；
9. 保留Tenant/User/Session隔离、TTL、删除、版本和敏感信息检查；
10. 将SkillSelection映射为动态Prompt、可见StructuredTool和Evidence要求；
11. 使用Runtime Context注入用户、权限和运行信息；
12. 整理StateGraph节点依赖，必要时按规划、执行、报告三个稳定边界拆分子图；
13. 保持PostgreSQL Checkpointer、中断恢复、API/Worker和SSE接口。

## 验证

只运行一条同时包含研报检索、Session Memory、Context压缩和报告引用的组合冒烟链路，确认：

- Retriever返回标准Document；
- Document到Evidence到Claim的来源链完整；
- Context压缩不修改Evidence保护字段；
- Memory隔离和Skill Tool范围仍生效；
- LangGraph Runtime可注入运行身份，现有Checkpoint调用方式保持兼容。

本Step不重复运行完整测试集。由于Docker守护进程按用户要求保持停止，
PostgreSQL Checkpoint、API/Worker/SSE和Docker生产链路统一留到Step 03集中验收，
不在本Step重复启动基础设施。

## Gate 02

- Retriever、Document、Runtime和Store标准接口已接入；
- Context、Memory、Skill和Evidence增强能力无明显退化；
- 标准框架能力与项目增强能力边界清楚；
- 组合冒烟链路可运行。
