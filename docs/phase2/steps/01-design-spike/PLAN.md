# Step 01 — 设计规范与LangGraph技术验证

## 目标

在改动第一阶段主流程前，确认LangGraph与现有Pydantic Schema、异步Tool、DeepSeek Adapter和Docker环境兼容，并将核心边界转成可实现规范。

## 前置条件

- `DECISIONS.md`的14项Proposed决定已审核；
- 第一阶段20题回归基线、镜像和配置可复现；
- 仅允许实验性分支/目录，不替换现有默认运行时。

## 子任务

1. 固定Python、LangGraph、checkpointer、Pydantic和相关依赖候选版本；
2. 定义Graph State字段、序列化规则和禁止对象；
3. 定义节点输入/输出、条件边、终态和错误分类；
4. 定义Run ID、Thread ID、Checkpoint ID、Attempt ID和业务幂等键映射；
5. 定义Skill、Tool、Policy、Budget、Memory和Evidence边界；
6. 定义节点副作用如何包装为可恢复Task；
7. 定义Checkpoint与业务Store的数据归属；
8. 编写最小StateGraph Spike：解析 → 计划 → 一个模拟Tool → 报告；
9. 用`InMemorySaver`验证节点继续、中断、重放与结构化输出；
10. 用一个现有异步Tool和DeepSeek测试配置做集成验证；
11. 运行第一阶段20题，记录兼容性差异，不在Spike中追加新功能；
12. 产出风险清单、依赖锁定建议和Step 02迁移决定。

## 测试清单

- Graph State JSON安全序列化；
- Pydantic校验失败可分类；
- 同一Thread中断后可继续；
- 重放不重复产生模拟副作用；
- 异步Tool调用不阻塞事件循环；
- DeepSeek输出可进入现有Schema和降级路径；
- 20题回归结果可与第一阶段基线比较。

## 交付物

- 依赖版本决定和Spike代码/测试；
- Graph State、节点、状态转移和错误Schema；
- Checkpoint/业务Store责任矩阵；
- 兼容性报告和Step 02 Go/No-Go结论；
- 已更新的`PROGRESS.md`。

## Gate 01

- Spike全部测试通过；
- 无法序列化对象未进入Graph State；
- 第一阶段20题无不可解释退化；
- 用户审核关键Schema和技术验证结果。

## 停止条件

若LangGraph与现有异步Tool、Pydantic或Provider Adapter出现无法接受的兼容性问题，停在Step 01重新选型，不进入整体迁移。
