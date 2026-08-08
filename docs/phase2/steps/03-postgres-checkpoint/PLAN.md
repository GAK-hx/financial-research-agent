# Step 03 — PostgreSQL Checkpoint与业务持久化

## 目标

将StateGraph从进程内运行升级为可恢复运行，同时分离LangGraph Checkpoint和Harness业务审计数据。

## 前置条件

- Gate 02已通过；
- Graph State稳定且可序列化；
- Docker主体部署原则和数据保留策略已确认。

## 子任务

1. 在Compose中增加PostgreSQL服务、健康检查、Volume和资源上限；
2. 配置`AsyncPostgresSaver`，由官方Setup管理Checkpoint表；
3. 为Checkpoint Serializer增加允许类型、大小限制和生产加密配置；
4. 使用SQLAlchemy Async + asyncpg + Alembic建立业务Store；
5. 建立Run、Run Event、Node Attempt、Model Call、Tool Call、Artifact Ref和Terminal Result表；
6. 定义Run/Thread/Checkpoint映射与外键约束；
7. 实现终态唯一、Attempt唯一和副作用幂等键；
8. 实现Interrupt/Resume与Pending Writes恢复；
9. 实现Cancel标记和节点安全检查点，尚不开放Job API；
10. 测试Worker中止、进程重启、DB短断和重复Resume；
11. 验证Checkpoint表不由业务Alembic修改；
12. 记录DB大小、Checkpoint增长、清理和恢复耗时。

## 最小业务表

```text
runs
run_events
node_attempts
model_calls
tool_calls
artifact_refs
terminal_results
```

Skill、Budget和Memory表在后续步骤增加，本步不提前实现其业务逻辑。

## 测试清单

- 重启后从最近合法Checkpoint继续；
- 已完成的幂等Task不重复外部调用；
- 重复Resume不产生两个终态；
- 非法序列化数据被拒绝；
- 状态加密开关不影响恢复；
- Alembic升降级只作用于业务表；
- 20题在PostgreSQL Checkpoint下仍通过。

## 交付物

- PostgreSQL Compose配置和运维说明；
- Checkpointer集成与Serializer策略；
- 业务Schema、Alembic迁移和数据字典；
- 恢复/幂等/一致性测试报告；
- 已更新的`PROGRESS.md`。

## Gate 03

- 进程重启后Run可恢复至合法终态；
- 测试中重复Tool/Model副作用为0；
- 终态、Attempt和Event序列一致；
- Checkpoint与业务Store责任未混用；
- 用户审核持久化与恢复结果。

## 停止条件

若无法保证副作用幂等或终态唯一，不进入Skill层。
