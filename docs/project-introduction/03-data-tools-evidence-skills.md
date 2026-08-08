# 03 数据、工具、Evidence与Skill

## 1. 数据底座

项目面向日线及更长周期研究，不假设已有稳定的分钟级数据源。

### 行情与财务

- AkShare 提供当前可复现的 A 股日线与财务报表来源；
- 采集层保存 Raw 响应、批次元数据和质量报告；
- 标准化层校验股票代码、日期、OHLC、重复业务键和缺失值；
- PyIceberg 保存正式日线、财务表和计算后的指标；
- Tool 查询时读取正式数据，不把模拟流式数据混入 Evidence。

### 研报

- PyMuPDF 抽取 PDF 页文本；
- BGE 生成向量；
- Milvus 保存 Chunk、股票代码、机构、页码和来源元数据；
- 检索强制按股票代码过滤；
- 原始 PDF 与索引版本可追溯。

## 2. Repository与Tool边界

Repository 负责具体存储访问，Tool 负责对 Agent 暴露受控能力。

目标 Tool：

| Tool | 数据域 | 主要输出 |
|---|---|---|
| `market_query` | Iceberg日线 | 区间行情与实际覆盖日期 |
| `indicator_calculator` | Iceberg日线 | 收益、回撤、均线等可复算指标 |
| `financial_query` | Iceberg财务 | 营收、利润、增长与盈利能力 |
| `report_search` | Milvus研报 | 带机构、页码和来源的相关Chunk |

所有 Tool 必须：

- 有 Pydantic Input/Output；
- 声明版本、数据域、只读属性和超时；
- 限制股票池、日期范围、行数和 Top K；
- 返回结构化错误，不把异常堆栈交给模型；
- 不允许模型传入 SQL、文件路径或任意代码；
- 通过 Tool Gateway 调用，禁止节点直接访问 Repository。

## 3. Evidence为什么是核心

Plan 说明“准备做什么”，ToolResult 说明“工具执行结果”，Evidence 才是报告可以引用的事实单元。

```text
Data Source
  ↓
Repository
  ↓
ToolResult
  ↓
Evidence Builder
  ↓
Evidence
  ↓
ResearchReport Claim
  ↓
Validator
```

这种分层带来三个好处：

1. 报告模型看不到数据库连接，只看到受控事实；
2. 每条 Claim 可以回溯到 Evidence 和数据来源；
3. Tool 更换实现时，只要 Evidence 语义不变，报告和校验层可以复用。

## 4. Skill的定义

Skill 是版本化研究流程约束，不是可执行 Python 插件。

```yaml
id: comprehensive_stock_research
version: 1.0.0
status: ACTIVE
triggers:
  intents: [comprehensive]
allowed_tools:
  - market_query
  - indicator_calculator
  - financial_query
  - report_search
required_evidence:
  - market
  - indicator
  - research_report
workflow_constraints:
  replan: 0
  max_revision: 1
context_policy: comprehensive_v1
validator_profile: strict_financial_v1
budget_profile: comprehensive_v1
```

### 首批研究Skill

- 行情趋势分析；
- 财务增长分析；
- 盈利能力分析；
- 综合个股研究。

### 首批报告Skill

- 研究报告检查；
- 简版报告；
- 风险优先报告。

## 5. Skill选择

当前选择过程分两层：

1. 程序按 Intent、数据域和状态过滤候选；
2. 程序校验版本、权限、Evidence 要求、调用上限和冲突。

模型候选排序是目录扩展后的可选能力，当前没有启用，避免为七个确定性Skill
增加网络调用和非确定性。

无 Skill 命中时回退已验证的默认流程。模型不能凭空创建 ACTIVE Skill，也不能通过组合两个 Skill 扩大权限。

多个 Skill 合并时：

- Tool 权限取交集；
- Budget 取更严格值；
- Validator 要求取并集；
- Workflow 冲突直接拒绝；
- Run 开始时保存 Skill Version Snapshot，中途发布新版本不影响当前 Run。

## 6. Skill生命周期

```text
DRAFT → REVIEWED → ACTIVE → DEPRECATED
```

- 人工或离线生成流程可以创建 DRAFT；
- REVIEWED 必须有人工审核记录；
- 只有 ACTIVE 版本能进入正式 Run；
- DEPRECATED 版本仍可用于历史审计，但不能分配给新 Run；
- 任何版本变更都生成新记录，不覆盖历史内容。

## 7. 数据与Skill的共同约束

Skill 只能描述“允许如何使用工具”，不能：

- 直接访问 Iceberg、Milvus 或 HTTP；
- 放宽 Tool 输入 Schema；
- 跳过 Evidence Builder；
- 关闭 Validator；
- 提高当前用户或租户的预算；
- 把历史 Memory 当作当前事实；
- 执行交易或外部写操作。
