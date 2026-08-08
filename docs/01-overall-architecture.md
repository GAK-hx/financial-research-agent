# 01 总体架构

## 1. 系统定位

系统是一个面向A股日线及中长期研究的证据驱动金融研究Agent。它不是自由聊天机器人，也不是自动交易系统，而是一个受约束的研究任务执行系统。

核心目标：

- 统一管理行情、财务和研报数据；
- 将数据能力封装成可验证、可追溯的工具；
- 让模型负责语义理解、有限规划和报告表达；
- 让程序负责数据处理、权限、预算、调度和校验；
- 让最终报告的数字和观点都能回到Evidence。

## 2. 逻辑架构

```text
数据源层
├── AkShare日线行情
├── AkShare财务数据
├── 证券研报PDF
└── Mock行情（实验域）
        ↓
数据管理层
├── 采集与增量同步
├── 标准化与质量校验
├── Iceberg表与快照
├── Milvus向量索引
├── 元数据与数据血缘
└── 数据生命周期
        ↓
领域服务层
├── Market Domain
├── Financial Domain
├── Research Document Domain
├── Indicator Domain
└── Evidence Domain
        ↓
工具层
├── Market Query Tool
├── Indicator Tool
├── Financial Tool
├── Comparison Tool
└── Report Search Tool
        ↓
Agent编排层
├── Query Interpreter
├── Planner
├── Plan Validator
├── Tool Executor
├── Evidence Builder
├── Report Generator
└── Report Validator
        ↓
Harness治理层（第二步）
├── Workspace
├── Memory Manager
├── Context Manager
├── Budget/Policy
├── Recovery
├── Trace/Eval
└── Completion Checker
        ↓
接口与产物层
├── FastAPI/SSE
├── Markdown/JSON报告
├── Evidence清单
└── Trace与评测结果
```

## 3. 第一步：Agent编排闭环

第一步只解决一次研究请求如何可靠完成：

```text
ResearchRequest
→ QuerySpec
→ AnalysisPlan
→ ToolResult
→ Evidence
→ ResearchReport
→ ValidationResult
```

第一步需要单次Run工作记忆，但不需要跨会话长期记忆。所有状态可以在一次请求期间保存在内存中，并选择性保存最终结果用于调试。

## 4. 第二步：Agent Harness

第二步解决持续运行和治理：

- 一个任务跨多个请求继续；
- 进程重启后恢复；
- 长上下文裁剪和摘要；
- 运行产物持久化；
- 预算和权限统一治理；
- 失败降级与完成判定；
- Trace、反馈和评测闭环。

## 5. 不采用的架构

- 第一版不做多Agent角色聊天；
- 第一版不做动态任意SQL；
- 第一版不让LLM计算金融指标；
- 第一版不引入ClickHouse/HDFS/K8s；
- 第一版不把Mock分钟行情包装成真实数据；
- 不将LangGraph等框架作为领域核心依赖。

## 6. 架构不变量

1. 所有正式结论必须来自真实数据域或研报知识域；
2. 模型只有工具调用权，没有数据源直接访问权；
3. 指标由确定性程序计算；
4. Tool Result不能未经转换直接进入最终报告；
5. Evidence必须携带来源、时间和研究对象；
6. Report Claim必须引用Evidence ID；
7. 模拟域与真实域物理或逻辑隔离；
8. 任何框架替换都不能破坏领域模型和工具接口规范。
