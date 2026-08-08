# Step 07 — Agent编排

## 目标

实现受约束的`问题 → 计划 → 工具`执行流程，并管理单次Run、Working和Evidence Memory。

## 依赖

- Step 01完成；
- Step 04和06完成；
- Step 05若完成则注册Financial Tool，否则计划能力相应降级。

## 任务

1. Query Interpreter解析股票、相对日期、意图和维度；
2. 实现15题规则解析测试；
3. 实现规则Planner标准轨迹；
4. 定义模型Provider和结构化Planner；
5. 模型输出失败时Pydantic校验并规则降级；
6. Plan Validator检查工具、参数、任务数、依赖环和预算；
7. Registry只暴露已验收只读工具；
8. Executor按依赖DAG和并发上限执行；
9. 工具超时和临时错误有限重试；
10. 建立单次RunContext；
11. Working Memory按节点构建最小上下文；
12. 成功Tool Result进入Evidence Builder，失败结果不进入；
13. 正式模式禁止simulation工具；
14. 实现阶段timing和统一错误。

## 标准轨迹

- Market：Market → Indicator；
- Report：Report Search；
- Comprehensive：Market与Report并行，Indicator依赖Market；
- Financial：只有工具已注册才可生成。

## 验收标准

- 15题QuerySpec正确；
- 计划只有白名单工具；
- 未知/循环依赖被拒绝；
- 并行关系符合预期；
- 模型不可用时标准问题仍可执行规则计划；
- 不超过任务、工具、并发和时间预算；
- 不同Run的Evidence不串线。

