# 05 Agent编排设计

## 1. 原则

模型参与语义不确定的环节，程序控制确定性环节。

```text
模型：理解、有限规划、基于证据表达
程序：校验、调度、查询、计算、预算、异常和完成判定
```

## 2. 第一步执行状态

```text
CREATED
→ INTERPRETING
→ PLANNING
→ VALIDATING_PLAN
→ EXECUTING
→ BUILDING_EVIDENCE
→ GENERATING_REPORT
→ VALIDATING_REPORT
→ COMPLETED / FAILED
```

允许一次`REVISING`，不允许无限循环。

## 3. Query Interpreter

输入：用户问题和当前日期。

输出：股票代码、日期范围、意图、分析维度和缺失字段。

策略：规则优先处理股票映射和相对日期；模型处理复杂语义；输出必须通过Pydantic。无法确定股票时请求澄清，不猜测。

## 4. Planner

Planner输出有限任务DAG，而不是自然语言思维链。

标准模板：

- Market：Market Query → Indicator；
- Report：Report Search；
- Comprehensive：Market和Report并行，Indicator依赖Market；
- Financial：Financial Query，可与Report并行。

模型只能选择注册工具，不能生成代码、SQL和未知工具。

## 5. Plan Validator

检查：

- 任务数不超过6；
- 工具在白名单；
- 参数符合对应Schema；
- 日期和股票合法；
- 依赖存在且无环；
- 只读属性；
- 预计工具调用不超过预算；
- 模拟数据工具不在正式模式可用列表。

## 6. Executor

- 无依赖任务最多4并行；
- 有依赖任务按拓扑执行；
- 单工具超时15秒（可按工具调整）；
- 临时错误最多重试2次；
- 工具失败转换为结构化ToolResult；
- 失败结果不转换为Evidence；
- 综合报告允许部分成功，但必须披露缺失部分。

## 7. Evidence Builder

工具自行返回领域结果，Evidence Builder统一生成可引用事实，分配Evidence ID，添加source locator、数据日期和研究对象。

## 8. Reporter

输入仅包含QuerySpec、成功Evidence和Report Schema。输出包含summary、claims、risks、data_as_of。每个claim至少引用一个Evidence ID。

## 9. Validator

第一步：Entity、Date、Citation、关键结构化Numeric校验。失败时最多修订一次。

第二步：加入Completion Checker、风险措辞、来源覆盖率、矛盾检测和运行策略。

## 10. Replan策略

第一步不启用动态Replan。计划参数错误由结构化校验和规则Planner重新生成处理，不在执行中开放动态扩展任务；数据不存在也不自动扩大搜索范围。

## 11. 模型适配

模型Provider必须支持结构化输出或可校验JSON。Provider是可替换组件；Orchestrator不依赖具体模型SDK。规则Planner与模板Report作为开发降级路径。

## 12. 已确认与待审核决策

- 已确认：第一步动态Replan为0；
- 已确认：Planner失败时使用规则计划，正式报告生成失败时明确报错，不使用模板冒充正式报告；
- 第一版是否需要Streaming？建议只流式返回阶段状态，不流式暴露模型草稿。
