# 第二阶段Harness输入清单

> 本文只定义第二阶段输入，不在Step 10提前实现Harness。

## 1. 第一阶段可直接复用

- `ResearchRequest → QuerySpec → AnalysisPlan → ToolResult → Evidence → ResearchReport`强类型模型；
- 只读Tool Registry及输入Schema；
- Plan Validator、报告Validator和一次修订边界；
- DAG Executor的依赖、并发、超时和有限重试；
- Run/Working/Evidence单任务隔离；
- 统一API错误、run_id、结构化日志和阶段耗时；
- 20题回归集、确定性评分器和逐题Artifact。

## 2. Harness需要新增的板块

### 2.1 受控执行状态机

- 显式Run状态与合法状态迁移；
- 节点级Checkpoint；
- 进程重启后恢复；
- 取消、暂停、继续和最终状态幂等。

### 2.2 Policy与Budget

- 模型、工具、Token、费用、时长、重试和Evidence预算统一记账；
- 在调用前准入、调用后扣账；
- 超预算时确定性停止，模型不能自行放宽限制；
- 不同任务类型使用版本化Policy Profile。

### 2.3 Tool Gateway

- Harness成为唯一工具调用入口；
- 工具白名单、参数校验、只读/写入权限和域隔离；
- Idempotency Key、超时、熔断、限流和错误分类；
- 工具返回仍必须转换为Evidence后才能进入报告。

### 2.4 Model Gateway

- Provider适配与能力声明；
- 结构化输出、超时、限流、重试和降级；
- 精确Token/费用/调用次数采集；
- Prompt、模型、参数和响应版本追踪；
- Provider不可用时遵循Policy，不允许静默改用高风险路径。

### 2.5 记忆管理

- 保留第一阶段Run/Working/Evidence Memory；
- 新增Session Memory前先定义保留期、大小、隔离和删除策略；
- 长期记忆只保存经审核的摘要/偏好，不保存原始密钥或无限上下文；
- Memory读写也必须作为受控操作审计。

### 2.6 持久化与并发

- 选择Run Store与Checkpoint Store；
- 支持乐观锁、租约、幂等写和重复消息；
- 保持Iceberg单写者限制，明确并发写协调；
- Artifact、日志和状态记录建立一致生命周期。

### 2.7 观测与评测

- 节点跨度、模型Token/费用、工具重试、队列时间；
- 开发集与未见Holdout严格分离；
- 重复运行统计稳定性和置信区间；
- 失败分类：解释、计划、工具、数据、报告、校验、预算、基础设施。

## 3. 第二阶段开始前必须决策

1. Session Memory是否进入第二阶段，以及保留多久；
2. Run/Checkpoint持久化使用PostgreSQL还是其他存储；
3. 是否保留同步API，或新增异步Job API；
4. 单Run费用、Token和最长运行时间上限；
5. 是否需要人工批准节点及其触发条件；
6. 第二阶段首批允许的写操作是否仍为0；
7. Holdout规模、股票范围和重复运行次数。

## 4. 建议实施顺序

1. 冻结Harness状态、Policy和错误模型；
2. 实现持久化Run状态机与Checkpoint；
3. 将现有Model/Tool调用迁移到Gateway；
4. 接入统一Budget和Policy执行；
5. 增加Session Memory（若审核通过）；
6. 实现恢复、取消、幂等和故障注入；
7. 使用独立Holdout完成第二阶段验收。
