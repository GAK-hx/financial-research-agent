# 第二阶段Skill设计

## 1. 定位

Skill是“已审核的金融研究方法”，它将适用条件、可用工具、必需证据、报告结构、校验和预算组合为版本化声明。

Skill不是：

- 可任意执行的Python/Shell代码；
- 能绕过Tool Gateway的数据连接器；
- 可自行扩大权限或预算的Prompt；
- 用历史结论代替当前Evidence的知识库。

## 2. Skill类型

| 类型 | 作用 | 示例 |
|---|---|---|
| Research Skill | 定义问题如何拆解和取证 | 行情趋势、财务增长、盈利质量 |
| Retrieval Skill | 定义数据域、时间范围和证据组合 | 定期报告检索、日线区间分析 |
| Report Skill | 定义报告结构和表达重点 | 简版研报、风险优先报告 |
| Review Skill | 定义报告完整性与证据质量校验 | 引用覆盖、数字一致性 |

第一版不允许Skill改变Graph拓扑；Skill只能在已定义的节点中收紧工具、Context、Evidence、Validator和Budget。

## 3. SkillDefinition

```text
id: string
version: semver
status: DRAFT | REVIEWED | ACTIVE | DEPRECATED
name: string
description: string
skill_type: research | retrieval | report | review
triggers: list[TriggerRule]
allowed_intents: list[Intent]
allowed_tools: list[ToolRef]
required_evidence: list[EvidenceRequirement]
workflow_constraints: WorkflowConstraints
context_policy: ContextPolicyRef
report_sections: list[ReportSection]
validator_profile: ValidatorProfileRef
budget_profile: BudgetProfileRef
prompt_refs: list[PromptRef]
owner: string
created_at / reviewed_at / activated_at
supersedes: SkillVersionRef | null
checksum: string
```

运行时将Skill版本、Policy版本、Tool版本和Prompt版本写入Run，保证结果可追溯。

## 4. 选择流程

```text
QuerySpec
  ↓ 规则过滤（Intent / 数据域 / 权限）
Candidate Skills
  ↓ 结构化模型排序（可选）
Selected Skills
  ↓ 程序化校验（冲突 / Tool / Budget / Evidence）
Execution Snapshot
```

选择原则：

1. 只有`ACTIVE`版本可用于正式Run；
2. 确定性规则先缩小候选集，模型不能从全库任意发明Skill；
3. 模型只能在候选集中排序，输出必须通过Pydantic校验；
4. 选中多个Skill时，权限取交集，预算不累加突破Run上限；
5. 无适用Skill时使用第一阶段默认受控流程，不强制生成新Skill。

## 5. 发布和变更

```text
DRAFT → REVIEWED → ACTIVE → DEPRECATED
```

- 模型或开发者可创建`DRAFT`；
- 人工审核Schema、权限、Evidence、预算和测试后进入`REVIEWED`；
- 只有发布操作可将指定版本设为`ACTIVE`；
- 修改已激活Skill必须新建版本，不覆盖历史；
- Run开始后固定Skill Snapshot，中途发布不影响正在运行的任务。

## 6. 首批Skill

| Skill | 核心Evidence | 允许工具范围 | 主要Validator |
|---|---|---|---|
| `market_trend_analysis` | 价格、成交量、区间收益/波动 | 日线行情和指标工具 | 交易日、区间、数值一致性 |
| `financial_growth_analysis` | 营收、利润、现金流及同/环比 | 财务指标、报告检索 | 报告期、单位、公式版本 |
| `profitability_analysis` | 毛利率、净利率、ROE及解释 | 财务指标、报告检索 | 口径、来源、异常数值 |
| `comprehensive_stock_research` | 行情+财务+报告证据 | 上述工具交集 | 证据覆盖、结论边界 |
| `research_report_review` | 报告Claim与Evidence映射 | 不新增取数权限 | 引用、数字、缺失声明 |
| `concise_research_report` | 已验证Evidence | 无额外工具 | 篇幅、结构、引用 |
| `risk_focused_report` | 已验证Evidence与缺口 | 无额外工具 | 风险与事实区分 |

## 7. 评测

- Skill选择准确率与多选一致性；
- 不合法Skill、过期版本和越权Tool拦截率；
- 必需Evidence覆盖率；
- 同一Skill版本的结果结构稳定性；
- Skill引入前后第一阶段Regression不退化；
- DRAFT无法用于正式Run。

## 8. 本阶段不做

- Skill Marketplace和远程代码下载；
- Skill自主发布、自主修改权限；
- 用用户自由文本直接生成可执行Skill；
- 为每个问题新建Skill；
- 将Skill当作多Agent角色聊天。
