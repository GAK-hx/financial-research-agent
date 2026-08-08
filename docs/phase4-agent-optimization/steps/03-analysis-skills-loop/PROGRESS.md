# Step 03 进度

- 状态：`COMPLETE`
- 前置条件：Step 02 Gate 通过
- 计划审核：已确认并实施
- 实现开始：2026-08-08
- Gate 结论：`TECHNICAL_GO`

## 已冻结设计

- [x] 使用 `demo_liquid_a_share@2026.08.v1` 的 20 只常见 A 股演示池；
- [x] 演示池不代表官方指数，截面结果必须同时返回真实覆盖数和缺失股票；
- [x] 12 个因子的公式、方向、窗口、空值、复权、版本与 PIT 资格进入 Factor Registry；
- [x] 报告增加技术、基本面、事件、数据置信度风险向量和三情景结构；
- [x] `concise`、`risk` 迁移为报告 Profile，六个分析 Skill 独立版本化；
- [x] 证据不足只允许一次同实体、同日期、同意图、同工具权限的受控补充。

## 已实现

- [x] Security/Universe/Factor Schema、Registry 和 Iceberg Repository；
- [x] Spark 4.2 批计算与 PyIceberg 批量落湖；
- [x] 技术、基本面、因子筛选、多股票对比和事件 Evidence Tool；
- [x] 六个 Skill 包、三种报告 Profile 和 LangChain StructuredTool 适配；
- [x] LangGraph Evidence 充分性节点、最多一次补充、重复动作与无进展终止；
- [x] 风险向量、情景结构及确定性报告校验；
- [x] 分析 Docker Profile 和网络重试配置。

## 已完成实跑

- [x] Spark/PyIceberg 运行成功：20 只 × 12 因子 = 240 条结果；
- [x] 数据实际覆盖 600519、300750 共 2 只，其余 18 只明确标记缺失；
- [x] `factor_screen` 成功读取版本化排名、缺失列表和 PIT 限制。

## 集中验证

- [x] Docker 全量发现 161 项：141 项通过，20 项按 PostgreSQL 开关跳过；
- [x] PostgreSQL/治理/Memory/Job 集成批次：44 项通过；
- [x] 最终修复聚焦批次：36 项通过；
- [x] 默认 `deepseek-v4-flash` 真实 Event Tool + 一次受控补充 Gate 通过；
- [x] Evidence、失败样例、Runbook、设计说明和 Gate 报告已补齐；
- [x] Step 03 关闭，可进入 Step 04。
