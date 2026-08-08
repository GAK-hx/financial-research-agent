# Step 03：分析工具、Skill 与受控循环

## 1. 目标

把项目从“能取数和生成受控报告”扩展成“能执行多种可复核股票分析”的 Agent。增加能力的主要
手段是确定性分析引擎和真正的 Skill 包，而不是开放任意代码执行。

## 2. 数据与股票池

- 建立 `security_master` 和版本化 `universe_membership`；
- 首批扩展至 20～50 只高流动性 A 股，保留 600519、300750；
- 每次截面分析记录股票池版本、观察日、过滤条件和缺失样本；
- 行情和因子字段带 `trade_date/as_of_date/available_at`；
- 没有可靠首次披露时间的历史财务数据只做当前或明确边界的基本面分析，不进入时点回测；
- 因子计算由 Spark/PySpark 批处理并写入 Iceberg，在线 Tool 只读结果和元数据。

## 3. 第一批确定性指标与因子

### 3.1 行情与风险

- `momentum_20d`、`momentum_60d`；
- `reversal_5d`；
- `volatility_20d`；
- `max_drawdown_60d`；
- `relative_volume_20d`；
- `amihud_liquidity_20d`。

### 3.2 基本面

- `revenue_growth`；
- `profit_growth`；
- `roe`；
- `operating_cashflow_to_profit`；
- `debt_to_assets`。

每个因子在 `Factor Registry` 中声明公式、输入字段、复权方式、窗口、方向、空值规则、去极值/
标准化规则、版本和可用时间。因子值、截面排名、风险结果和运行产物分别保存，不让 LLM 自行计算。

## 4. Tool 设计

保持模型可见 Tool 数量较少，按 Skill 动态暴露：

| Tool 组 | 能力 |
|---|---|
| Market/Financial | 精确日线、区间统计和财务指标读取 |
| Technical Analysis | 趋势、动量、波动、回撤、量价和数据质量 |
| Cross-sectional/Factor | 股票池筛选、因子排名、分组和暴露说明 |
| Event Knowledge | 按股票、时间、类型检索已激活事件及原始来源 |
| Report Search | 研报混合检索、父块加载和引用定位 |
| Comparison/Risk | 多股票对比、风险向量和情景输入输出 |

所有 Tool 使用 LangChain 结构化 Schema，内部继续经过同一 Gateway。Tool 描述必须写明适用条件、
不适用条件、输入单位、时间语义、返回 Evidence 类型、错误和限制。

## 5. Skill 能力包

每个 Skill 目录至少包含：

```text
manifest.yaml
prompts/
references/
workflow.yaml
validators/
examples/
```

Manifest 声明版本、意图、先决条件、可见 Tool、预算、Evidence 最低要求、输出 Schema 和终止规则。
首批 Skill：

1. `single_stock_technical`：单股趋势、动量、波动、回撤和量价；
2. `single_stock_fundamental`：增长、盈利、现金流和偿债；
3. `cross_section_screening`：指定股票池的截面对比和筛选；
4. `factor_research`：因子定义、排名、覆盖度和简单分组分析；
5. `event_impact`：事件时间线、价格窗口和来源置信度；
6. `comprehensive_stock_analysis`：组合行情、基本面、事件和风险证据。

现有 `concise`、`risk` 调整为报告 Profile，只影响篇幅和展示重点，不再冒充分析能力。

## 6. LangGraph 受控循环

目标节点：

```text
interpret
→ semantic_align
→ select_skill
→ plan
→ execute_tools
→ build_evidence_manifest
→ check_evidence_sufficiency
→ [optional_replan → execute_tools]（最多一次）
→ generate_report
→ validate_report
→ [revise_report]（最多一次）
→ complete
```

受控修正规则：

- 只能由结构化的 `MissingEvidence` 触发；
- `replan_count <= 1`；
- 不得新增股票、扩大时间范围、改变原始意图或申请新权限；
- 补充任务必须引用原计划缺口，并通过 Plan Validator；
- 重复 Action Hash、无新增 Evidence、预算不足或致命错误时立即终止；
- 终态明确区分成功、部分成功、证据不足、预算终止、无进展、取消和系统错误。

生成者和检查者使用隔离 Prompt/上下文；即使都由 Flash 承担，也不让检查者看到生成者的隐藏推理。
确定性检查先于模型 Reviewer。

## 7. 报告输出

报告至少包括：

- 分析范围和数据截止日；
- 可追溯的关键发现；
- 技术、基本面、事件和数据置信度风险向量；
- 乐观/基准/压力情景及其假设；
- 缺失数据、时间口径和因子限制；
- Evidence 引用和计算版本；
- 研究辅助免责声明，不给出自动买卖指令。

## 8. 交付物

- Security/Universe/Factor Schema 与 Registry；
- Spark 因子批处理、Iceberg 表和查询 Repository；
- 新 Tool 组及其 Evidence Schema；
- 六个版本化 Skill 包和报告 Profile；
- 受控修正、进展检测和终止节点；
- 分析专项评测、失败案例、演示脚本和 Gate 报告。

## 9. 测试安排

开发中每类引擎只使用一个固定样例做公式或连通性冒烟。Step 收尾集中执行：

- 公式、窗口、复权、缺失值、截面排名和时点确定性测试；
- Tool Schema、动态可见性、权限和错误规范；
- 六类 Skill 的任务覆盖和组合边界；
- 一次修正成功、越界修正拒绝、重复动作终止和部分结果；
- Docker 全量回归与真实 Flash 私有 Holdout；
- 延迟、Token、成本、无效 Tool 调用和轨迹重复率。

## 10. Gate

- 因子公式和时点测试 100%，每个输出记录 Registry 版本；
- Tool 无越权数据访问，模型无法执行任意 SQL/Python；
- 所有定量结论和因子排名的 Evidence 覆盖 100%；
- 受控修正不扩大原股票、时间、意图和 Tool 权限，P0 用例 100%；
- 重复 Action 或无新增 Evidence 不会无限循环；
- 真实 Flash 综合题集不低于 95%，失败题有分类和限制说明；
- 报告不把缺少 PIT 的财务数据包装成历史可交易时点信息。

## 11. 停止条件

- 因子只能由 LLM 临时计算而无法复现；
- 数据不具备时点字段却需要宣称无前视偏差；
- Skill 可以绕过 Gateway 或动态扩大权限；
- 为覆盖更多问题必须开放任意代码执行；
- 一次受控修正仍无法稳定终止。

