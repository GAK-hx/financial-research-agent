# 01 项目概览

## 1. 项目是什么

Financial Research Agent 是一个面向 A 股日线和中长期研究的只读 Agent。

用户可以直接提问：

```text
分析贵州茅台今年的行情与券商观点
宁德时代最近三年的营收和利润如何
机构如何评价宁德时代的技术创新
```

系统不会让模型直接连接数据库。它会先识别股票、日期和研究意图，再生成结构化计划，调用经过白名单和参数校验的只读工具，最后基于真实 Evidence 生成报告。

## 2. 为什么要做这个项目

普通工具调用型 Agent 往往存在几个问题：

- 模型可能选择错误工具或修改用户的股票、日期；
- 报告中的数字难以追溯；
- 模型失败、进程重启后无法继续；
- 重试可能造成重复调用；
- 多轮上下文容易混入过期结论；
- 很难回答“为什么允许这次调用”和“这次运行花了多少预算”。

本项目的目标是把这些问题从 Prompt 要求变成程序约束。

## 3. 当前已经实现

### 数据与工具

- AkShare 日线与财务数据采集；
- PyIceberg 正式数据表；
- PDF 研报解析、BGE 向量和 Milvus 检索；
- 行情、指标、财务和研报四类只读工具；
- Pydantic 输入输出和结构化错误。

### Agent编排

- QuerySpec 问题理解；
- LangChain ChatModel/Runnable与Structured Output；
- LangChain StructuredTool、ToolMessage artifact和BaseRetriever；
- LangGraph StateGraph与显式规则降级；
- 计划白名单、参数和依赖校验；
- 受控并行工具执行；
- Evidence Builder；
- 报告生成、一次修订和数字/引用校验；
- 默认使用LangChain/LangGraph正式路径，旧实现仅作为显式回退。

### 持久化与恢复

- PostgreSQL `AsyncPostgresSaver`；
- Run、Event、Attempt、Model/Tool Call 和唯一终态；
- 模型/工具幂等键和调用租约；
- Interrupt、Resume、Cancel 底层语义；
- 跨进程恢复、数据库短断恢复和重复 Resume 验证；
- Docker Compose 部署和 Alembic 迁移。

## 4. 已完成的增强能力

| 能力 | 当前实现 |
|---|---|
| Skill | 版本化、可审核、可快照的7类研究Skill |
| Gateway | 统一模型和工具调用、重试、Usage和脱敏 |
| Policy/Budget | 调用前授权和PostgreSQL事务预算 |
| Memory | 可隔离、过期、删除和显式确认的Memory |
| Context | 节点级构建与压缩，Evidence确定性保护 |
| Job服务 | API/Worker、SSE、Cancel/Resume和Trace |
| 最终评测 | Regression、Holdout、稳定性、安全和故障注入 |

## 5. 核心技术栈

| 层 | 技术 |
|---|---|
| API | FastAPI、Pydantic |
| Agent基础接口 | LangChain |
| Agent运行时 | LangGraph StateGraph |
| 模型 | DeepSeek OpenAI-compatible Adapter |
| 持久化 | PostgreSQL、SQLAlchemy Async、asyncpg、Alembic |
| Checkpoint | AsyncPostgresSaver |
| 数据湖 | PyIceberg |
| 研报检索 | PyMuPDF、BGE、Milvus |
| 部署 | Docker Compose |
| 测试 | unittest、故障注入、版本化评测集 |

## 6. 项目最重要的设计边界

### 模型能做

- 理解自然语言问题；
- 在允许的工具中生成结构化计划；
- 根据当前 Run Evidence 生成报告；
- 根据 Validator 错误修订一次报告。

### 模型不能做

- 直接查询数据库；
- 执行 SQL、Shell 或 Python；
- 自由增加工具；
- 修改 Policy 或 Budget；
- 跳过 Validator；
- 把历史结论当作当前事实；
- 下单或修改外部金融数据。

## 7. 一次成功结果包含什么

- 原始问题和结构化 QuerySpec；
- 实际执行的 Plan；
- 每个 Tool 的成功/失败和耗时；
- 当前 Run 的 Evidence；
- 带 Evidence ID 的报告 Claim；
- ValidationResult；
- 模型、Prompt、Tool、Skill 和 Policy 版本；
- 节点、调用、预算和终态审计；
- 可恢复的 Checkpoint。

## 8. 如何理解项目价值

项目的重点不是“接入了多少框架”，而是建立一条可以证明的受控研究链路：

```text
自然语言
  → 强类型计划
  → 受控真实数据
  → 可追溯Evidence
  → 经校验报告
  → 可恢复、可审计终态
```

LangChain解决模型、Tool、Retriever和Message接口标准化，LangGraph解决图运行和恢复；
项目本身解决金融Tool、Evidence、权限、预算、Memory和完成判断。
