# 第三阶段总实施计划

## 目标

在保持当前 API、数据底座、治理记录和评测基线的前提下，将 LangChain 标准接口提升为
Agent 开发基础层，将现有能力整理为金融领域增强层，并继续以 LangGraph 作为正式状态化运行时。

## 三步实施顺序

```text
01 LangChain核心接口改造
  ↓
02 现有增强能力接入LangChain/LangGraph
  ↓
03 正式路径切换与集中验收
```

| Step | 核心结果 | 当步可行性验证 | 详细计划 |
|---:|---|---|---|
| 01 | ChatModel/Runnable、Structured Output、StructuredTool和Message进入代码 | 一条规划—Tool—报告冒烟链路 | `steps/01-langchain-core/PLAN.md` |
| 02 | Retriever、Evidence、Context、Memory、Skill和Graph Runtime完成标准接口接入 | 一条含RAG、Memory和Context的冒烟链路 | `steps/02-enhancement-integration/PLAN.md` |
| 03 | LangChain路径成为默认路径，完成回归、Docker和文档 | 只在此步集中进行完整测试 | `steps/03-cutover-acceptance/PLAN.md` |

## 迁移策略

### 保留

- StateGraph、PostgreSQL Checkpointer、API/Worker；
- ToolGateway、ModelGateway、Policy、Budget；
- DAG Executor、EvidenceBuilder、ContextBuilder；
- MemoryManager、SkillRegistry、ReportValidator；
- Milvus、Iceberg、PostgreSQL 数据能力。

### 适配

- `OpenAICompatibleProvider` -> LangChain ChatModel/Runnable 后端；
- `FinancialTool` -> `StructuredTool`；
- `ToolResult` -> `ToolMessage(content, artifact)`；
- `MilvusReportStore` -> `BaseRetriever`；
- `MemoryManager` -> LangGraph `BaseStore` 兼容层；
- `ContextBuilder` -> Context Middleware/Runnable 前处理；
- `SkillSelection` -> 动态 Prompt、Tool 可见集和 Runtime 限制。

### 替换

- Prompt 中手写输出 Schema 的主路径 -> LangChain Structured Output；
- 自定义模型调用作为唯一入口 -> ModelGateway 管理的 LangChain Runnable；
- 仅业务字段的调用轨迹 -> 标准 Message + 业务状态双轨；
- 仅 `ainvoke` 的用户体验 -> `astream`/自定义事件。

## 测试策略

遵循“前两步只冒烟，最后一步集中测试”：

1. Step 01和02分别只运行一条端到端冒烟路径；
2. 不为每个Adapter单独扩张测试集，不重复运行全量测试；
3. Step 03统一运行必要单元测试、PostgreSQL、API、Docker和核心Regression；
4. 模型小规模能力验证优先使用 Pro，重复和稳定性验证优先使用 Flash；
5. 评测通过阈值沿用现有标准，总体成功率达到 95% 可通过；
6. 量纲、输入变体等可修复问题允许进入有限检查修复流程，但必须记录。

## 总体验收条件

- LangChain ChatModel/Runnable、StructuredTool、Message、Retriever、Structured Output 确实进入正式路径；
- LangGraph 仍是唯一正式状态化运行时；
- 正式 Model/Tool 调用不存在绕过 Gateway 的路径；
- 数据来源、数字和 Evidence 保护不退化；
- API 与Docker演示方式保持可用；
- 现有回归集不出现阻断性退化；
- 文档能明确区分框架原生能力与项目增强能力。

## 停止条件

出现以下情况时暂停当步，不继续扩大迁移范围：

- DeepSeek 与 LangChain Structured Output/Tool Calling 存在不可控不兼容；
- LangChain Adapter 绕过 Gateway、Policy 或 Budget；
- Message 转换导致 Evidence 或来源信息丢失；
- Store 适配破坏租户隔离、TTL 或删除语义；
- 新运行路径无法恢复到现有质量基线。
