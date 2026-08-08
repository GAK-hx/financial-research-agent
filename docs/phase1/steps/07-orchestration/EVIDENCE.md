# Step 07 验收记录

## 已实现链路

```text
Question
→ Query Interpreter
→ QuerySpec
→ Structured Planner / Rule Fallback
→ Plan Validator
→ DAG Executor
→ Successful Tool Results
→ Run-local Evidence Memory
```

模型只接收用户问题、已解释的`QuerySpec`和Registry暴露的工具Schema。模型不持有数据库连接，不能执行SQL或Python，也不能绕过工具读取数据。

## 规则与预算

| 项目 | 实现 |
|---|---|
| 股票范围 | 600519、300750；未知股票不猜测 |
| 相对日期 | 天、月、半年、中文/数字年份及明确日期范围 |
| 计划任务 | 最多6个 |
| 工具调用 | 默认最多8次 |
| 并行工具 | 默认最多4个 |
| 工具重试 | 临时错误最多2次 |
| Run超时 | 默认60秒 |
| Evidence | 默认最多40条，按Run隔离 |
| 工具权限 | 只读白名单；Simulation拒绝注册 |

Plan Validator重新校验工具参数、股票绑定、解释结果绑定、任务预算和DAG。即使模型输出合法JSON，也不能把贵州茅台问题切换为宁德时代查询。

## 标准轨迹

| 类型 | 实际任务 | 依赖关系 | 结果 |
|---|---|---|---|
| Market | `market`、`indicator` | indicator依赖market | Pass |
| Report | `report` | 无 | Pass |
| Comprehensive | `market`、`report`、`indicator` | market/report并行，indicator依赖market | Pass |
| Financial | `financial` | 无 | Pass |

## 真实运行

### 贵州茅台综合分析

- 问题：分析贵州茅台最近一年的股价表现和研报观点；
- Planner：未配置模型时使用`rule_fallback`；
- Market与Report首批并行，Indicator在Market成功后执行；
- Market 1条、Indicator 1条、Report 5条，共7条Evidence；
- Iceberg实际行情日期：2025-07-15至2026-07-14；
- Milvus结果全部为600519；
- Run完成，无结构化错误。

### 宁德时代财务分析

- 问题：分析宁德时代最近三年的营收、利润和盈利能力；
- 中文“三年”解析为2023-07-15至2026-07-15；
- Financial Tool实际报告期为2023-09-30至2026-03-31；
- 生成1条Financial Evidence，Run完成。

## 测试结果

- 15题Query Interpreter样例全部通过；
- 模型非法结构自动降级规则计划；
- 未知工具、循环依赖、股票切换全部拒绝；
- 临时错误重试及依赖顺序通过；
- 两个并发Run的Evidence股票集合完全隔离；
- 全项目36/36项测试通过。

## 当前限制

- 尚未配置真实模型密钥，因此本步验证的是Provider适配、结构校验和模型不可用降级，未评估具体模型的规划质量；
- 当前不做动态Replan，工具失败不会自动扩大日期或跨股票检索；
- Working Memory是按节点重建的内存视图，不跨Run持久化；
- 本步只生成Evidence Memory，最终报告与引用校验属于Step 08。
