# Financial Research Agent 项目介绍

## 先从这里开始

这是一组可以独立阅读的项目介绍，说明项目解决什么问题、现在做到了什么、完整版本准备怎么实现，以及为什么要这样设计。

如果只是想快速了解项目，阅读本页即可。想了解技术细节，再按照下方顺序继续。

> 当前以LangChain统一模型、Tool、Retriever、Message和结构化输出接口，
> 以LangGraph承担状态化运行与PostgreSQL Checkpoint；金融领域的Gateway、
> Policy/Budget、Evidence、Memory/Context、版本化Skill和报告校验均已接入默认路径，
> 第三阶段集中工程验收已经完成。

| 能力 | 当前状态 | 目标步骤 |
|---|---|---:|
| 受控金融研究闭环 | 已实现 | Phase 1 |
| LangChain标准Agent接口 | 已实现并切为默认 | Phase 3 |
| LangGraph StateGraph | 已实现 | Step 02 |
| PostgreSQL Checkpoint与业务审计 | 已实现并通过审核 | Step 03 |
| Skill Registry | 已实现并通过Gate | Step 04 |
| Model/Tool Gateway、Policy、Budget | 已实现并通过Gate | Step 05 |
| Memory与Context Compression | 已实现并通过Gate | Step 06 |
| Job API、Worker、SSE | 已实现并通过Gate | Step 07 |
| Holdout、安全与稳定性评测 | 已完成并通过Gate | Step 08 |
| Docker交付与最终验收 | 工程验收完成，待用户确认 | Step 09 |

## 1. 项目解决什么问题

项目是面向日线和中长期研究的只读金融 Agent。它接收自然语言问题，将问题转换为结构化查询和受控任务图，只允许通过白名单工具读取 Iceberg、Milvus 等真实数据，最后生成带 Evidence 引用并经过程序校验的研究报告。

它不是自动交易系统，不执行下单，不允许模型运行 SQL、Shell 或任意 Python，也不把模型生成的结论当作事实直接写入长期 Memory。

## 2. 一次研究请求会发生什么

```text
用户问题
  → 识别股票、时间和研究意图
  → 生成受约束计划
  → 校验计划和工具参数
  → 调用只读行情/财务/研报工具
  → 形成带来源的Evidence
  → 生成研究报告
  → 校验每条结论的数字和引用
  → 保存结果、状态和审计轨迹
```

模型负责理解、规划和表达，程序负责真实数据访问、权限、预算、恢复和最终正确性判断。

## 3. 阅读前只需要知道的术语

| 术语 | 通俗解释 |
|---|---|
| Run | 用户提交一次研究问题后产生的完整任务 |
| Node | Run中的一个明确步骤，例如规划、取数或报告校验 |
| Tool | 受程序控制的只读数据能力，例如查询行情 |
| Evidence | Tool返回并整理出的、带来源的事实 |
| Checkpoint | Run执行到某一步时保存的恢复点 |
| Skill | 经过审核的版本化研究流程，不是任意执行代码 |
| Gateway | 所有模型或Tool调用必须经过的统一入口 |
| Policy | 判断某次调用是否被允许的程序规则 |
| Budget | 对时间、调用次数、Token和费用的硬限制 |
| Memory | 经隔离、确认并可删除的跨请求信息 |

## 4. 完整目标架构

```text
Client / Demo UI
       │
       ▼
FastAPI Job API ───── SSE / Status / Cancel / Resume / Trace
       │
       ▼
LangGraph Runtime ───── StateGraph / Checkpoint / Store / Runtime
       │
       ▼
LangChain Agent Foundation
├── ChatModel / Runnable / Structured Output
├── StructuredTool / ToolMessage
└── BaseRetriever / Document
       │
       ▼
Financial Control Plane
├── Skill Registry
├── Policy Engine
├── Budget Ledger
├── Memory Manager
├── Context Builder
└── Completion Checker
       │
       ▼
Model Gateway / Tool Gateway
       │
       ├── DeepSeek-compatible Model Adapter
       ├── Market / Indicator / Financial Tools
       └── Report Search Tool
       │
       ▼
Iceberg + Milvus + PostgreSQL + Artifact Volume
```

## 5. 推荐阅读顺序

1. [01-project-overview.md](01-project-overview.md)：项目定位、使用方式、当前状态和最终能力；
2. [02-architecture-and-runtime.md](02-architecture-and-runtime.md)：架构分层、状态图和一次 Run 的完整生命周期；
3. [03-data-tools-evidence-skills.md](03-data-tools-evidence-skills.md)：数据底座、工具、Evidence 与 Skill；
4. [04-governance-memory-context.md](04-governance-memory-context.md)：Gateway、Policy、Budget、Memory 和上下文压缩；
5. [05-api-worker-deployment.md](05-api-worker-deployment.md)：Job API、Worker、SSE、Docker、可观测与运维；
6. [06-quality-security-delivery.md](06-quality-security-delivery.md)：评测、安全、验收、演示和项目边界。
7. [07-current-implementation-guide.md](07-current-implementation-guide.md)：当前已实现组件、代码边界、运行链路和Docker部署。

按读者选择：

| 读者 | 建议阅读 |
|---|---|
| 招聘方或非技术读者 | 本页 + 01 |
| 后端/Agent开发者 | 01 → 02 → 03 → 04 |
| 架构或运维评审 | 02 → 04 → 05 → 06 |
| 面试准备 | 本页、01、02、06 |

## 6. 最终应如何介绍这个项目

一句话版本：

> 基于LangChain与LangGraph构建可恢复的股票投研Agent：使用LangChain统一模型、
> Tool、Retriever和结构化输出接口，使用LangGraph编排状态图与PostgreSQL
> Checkpoint，并扩展受控Skill、Model/Tool Gateway、Policy/Budget、Evidence校验
> 和隔离Memory，使模型只能通过可审计工具读取真实数据并生成可追溯报告。

职责边界版本：

- LangChain提供ChatModel/Runnable、StructuredTool、Message、Retriever和结构化输出标准接口；
- LangGraph提供状态图、Checkpoint、Store、中断与恢复；
- 项目自身提供金融领域 Schema、Tool/Evidence、Skill、Policy/Budget、Memory 规则和 Completion Checker；
- Iceberg 负责日线与财务数据底座；
- Milvus 负责研报向量检索；
- PostgreSQL 同时承载独立的 LangGraph Checkpoint 表和 Harness 业务审计表；
- Docker Compose 负责可复现的本地部署与演示。

这种描述既不把框架能力冒充为自研，也能清楚体现项目真正实现的领域治理价值。
