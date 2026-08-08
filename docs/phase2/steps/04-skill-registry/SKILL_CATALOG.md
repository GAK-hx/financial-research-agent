# Step 04 Skill目录

## 1. 运行边界

Skill是经过审核的“研究方法声明”，不是可下载执行的插件。它不能运行
Python或Shell、不能直接连接数据源、不能添加Tool，也不能改写StateGraph
拓扑。真实数据仍然只能经受控Tool读取。

运行时只接受`ACTIVE`版本；选中多个Skill时，Tool取交集，调用上限和并行
上限取更严格值，Evidence要求取并集。同一Run保存完整Snapshot，因此发布
新版本不会改变正在运行或恢复中的任务。

## 2. 首批内置Skill

| ID | 类型 | 触发条件 | 必需Evidence | Tool上限 |
|---|---|---|---|---:|
| `market_trend_analysis@1.0.0` | research | market | market + indicator | 2 |
| `financial_growth_analysis@1.0.0` | research | financial + growth | financial | 2 |
| `profitability_analysis@1.0.0` | research | financial + profitability/leverage | financial | 2 |
| `comprehensive_stock_research@1.0.0` | research | comprehensive | market + indicator + research_report | 4 |
| `research_report_review@1.0.0` | review | report | research_report | 4 |
| `concise_research_report@1.0.0` | report | concise | 沿用研究Skill要求 | 4 |
| `risk_focused_report@1.0.0` | report | risk | 沿用研究Skill要求 | 4 |

`concise_research_report`与`risk_focused_report`第一版显式冲突：同时要求时拒绝
运行，而不是让模型自行决定优先级。

## 3. 当前实现范围

- 已实现：规则候选、状态过滤、组合校验、Tool收紧、Evidence校验、版本快照；
- 可选模型排序暂未启用：当前七个Skill数量少，确定性规则更容易解释和测试；
- 报告章节、Context、Validator和Budget Profile已进入Snapshot；
- Profile的完整执行器分别在Step 05和Step 06接入，本Step不提前复制治理逻辑。

目录源文件：`src/financial_research_agent/skills/catalog.json`。
