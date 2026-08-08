# Step 02 — StateGraph迁移与第一阶段等价性

## 目标

将第一阶段已验证的受控编排迁入LangGraph StateGraph，首先达到行为等价，不在本步引入PostgreSQL、Skill、长期Memory或新API。

## 前置条件

- Gate 01已通过；
- Graph State和节点Schema已审核；
- 第一阶段回归基线可重复运行。

## 子任务

1. 将Interpret、Plan、Plan Validation、Tool Execution、Evidence、Report、Report Validation和Completion映射为节点；
2. 将程序控制的受限分支映射为条件边；
3. 保留Structured Planner、确定性降级和Replan=0；
4. 保留现有Tool Registry、Evidence Builder和Validator接口；
5. 将并行Tool执行封装为可追踪Graph节点，节点内部暂时复用已验证的`PlanExecutor`执行DAG、并发和Tool重试；
6. 将模型和Tool副作用隔离在明确节点中；本步不启用Graph级自动重试，持久化幂等键在Step 03/05实现；
7. 加入节点级超时、错误归一化和中止语义；
8. 使用`InMemorySaver`跑通完整路径；
9. 保留现有同步`/analyze`为兼容层，不改客户端Schema；
10. 增加节点单测、Graph路径测试和终态一致性测试；
11. 对20题逐题对比Intent、Tool Trace、Evidence、报告结构和Validator结果；
12. 保留旧编排作为可配置回退，直至Step 03稳定。

## 验证节奏

- 子任务完成时只做静态检查或1—2项冒烟测试；
- 不因文档、小修或单一断言重复构建镜像、执行全量测试；
- Step 02功能和文档完成后，集中执行一次LangGraph专项、一次正式镜像全量回归、一次20题对照和一次真实API链路；
- Gate测试发现问题后集中修正，再做一次有针对性的确认，不循环运行无关测试。

## 测试清单

- 每类Intent的预期Graph路径；
- Tool成功、部分失败、全部失败和超时；
- 模型Schema失败与降级计划；
- Evidence不从模型文本直接创建；
- Validator失败时最多修订1次；
- Completion终态仅写入一次；
- 20题与旧运行时差异可解释。

## 交付物

- 完整StateGraph与节点单测；
- 新旧运行时切换配置；
- 20题等价性比较报告；
- Graph路径图和错误对照表；
- 已更新的`PROGRESS.md`。

## Gate 02

- 20题全部进入合法终态；
- Tool/Evidence/Validator边界未改变；
- 无模型自由选边或越权工具调用；
- 关键品质指标不低于第一阶段基线；
- 用户审核等价性报告。

## 停止条件

如果迁移必须改写Tool/Evidence业务语义才能继续，回到Step 01重新划分边界。
