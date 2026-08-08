# 第三阶段：以 LangChain 为基础框架的架构调整

## 阶段定位

本阶段不是推翻现有实现，而是将项目从“LangGraph 编排 + 自定义组件”调整为：

> LangChain 统一 Agent 开发接口，LangGraph 承担状态化运行时，现有金融治理能力作为框架增强层。

LangChain 负责模型、Prompt、结构化输出、Tool、Message、Retriever、Middleware、
Callback 等标准接口；LangGraph 负责 StateGraph、Checkpoint、条件路由、恢复、子图和流式事件；
项目现有的 Gateway、Policy、Budget、Evidence、Context、Memory、Validator 继续保留。

## 文档入口

- `MASTER_PLAN.md`：三步总实施计划；
- `ARCHITECTURE.md`：目标架构与模块归属；
- `OPTIMIZATION_POINTS.md`：相较 LangChain 默认能力的项目增强点；
- `CHECKLIST.md`：阶段验收清单；
- `PROGRESS.md`：第三阶段总进度；
- `steps/*/PLAN.md`：每一步详细实施方案；
- `steps/*/PROGRESS.md`：每一步实时进度。

## 当前状态

三个Step均已完成：LangChain核心模型/工具接口以及Retriever、Context、Memory、
Skill和Runtime增强入口均已接入；LangChain/LangGraph已经切换为默认正式路径，
PostgreSQL、API/Worker/SSE、Docker和Regression集中验收通过。
