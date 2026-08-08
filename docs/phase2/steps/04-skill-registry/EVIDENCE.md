# Step 04 验收证据

状态：`READY_FOR_REVIEW`

## 1. 镜像、迁移与运行

- 最终Harness镜像构建成功；
- Alembic从`20260724_0001`升级至`20260726_0002`；
- 新增`skills`、`skill_versions`、`skill_reviews`、
  `skill_activations`和`run_skill_snapshots`；
- 正式`langgraph-app`健康检查中Iceberg、Milvus和PostgreSQL均为ready；
- 内置目录初始化结果：7 ACTIVE、7 Review、7 Activation。

## 2. 自动化回归

最终镜像执行97项测试，97/97通过。新增专项覆盖：

- 只有ACTIVE可选，DRAFT不能进入Run；
- Content Checksum不随生命周期状态变化；
- 多Skill Tool取交集、预算取更严格值；
- 冲突Skill拒绝；
- 越权Tool和超调用上限在执行前拒绝；
- 缺必需Evidence时拒绝；
- DRAFT→REVIEWED→ACTIVE人工生命周期；
- Run Snapshot重复写幂等、不同内容不可覆盖；
- LangGraph轨迹包含`select_skill`。

## 3. 真实API链路

问题：`分析贵州茅台最近三年的营收和利润`

```yaml
success: true
planner_source: model
selected_skills:
  - financial_growth_analysis@1.0.0
reporting_status: completed
```

数据库同时存在对应Run Snapshot和`skill_selected`事件。

## 4. 20题真实评测

```text
Task Success          19/20
Intent                18/18
Tool Selection        18/18
Arguments             18/18
Citation              18/18
Numeric Consistency   17/18
P50 / P95             7.752s / 18.215s
```

18个合法输入均选择到预期研究Skill；两个非法输入在Interpret阶段受控拒绝。原始
结果位于`artifacts/phase2_step04/skill_gate/evaluation/`。

与Step 03结果比较：

- 20/20产物齐全；
- 0个回归；
- `eval-11`从Provider网络失败恢复；
- 18个双方成功用例结构化语义18/18一致；
- `eval-16`仍为已知数字格式校验失败，详见`FAILED_CASES.md`。

## 5. Gate 04结论

`TECHNICAL_GO_READY_FOR_USER_REVIEW`

Skill选择可解释、可追溯；DRAFT、冲突、越权和缺Evidence均被拦截；20题未出现
Skill引入的语义退化。等待用户审核Skill内容、发布流程和当前边界。
