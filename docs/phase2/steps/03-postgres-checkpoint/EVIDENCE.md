# Step 03 验收证据

状态：`READY_FOR_REVIEW`

## 已交付

- Docker PostgreSQL `17.10-alpine3.23`、健康检查、Volume 和 512 MiB 上限；
- `AsyncPostgresSaver`、严格 Serializer、2 MB 上限和可选 AES；
- SQLAlchemy Async + asyncpg + Alembic 业务 Store；
- Run、Event、Attempt、Model Call、Tool Call、Artifact Ref、Terminal Result；
- Model/Tool 幂等键、输入 Hash、180 秒调用租约和终态唯一；
- 跨进程 Interrupt/Resume、Cancel 安全边界和数据库短断恢复；
- 数据字典、持久化设计、运行手册、恢复报告和失败明细。

## 最终测试

```text
模型重试 + PostgreSQL专项：12/12 OK
最终完整回归：90 tests OK，6项按环境条件跳过
跨进程恢复：Tool 0 → 1 → 0
迁移降级边界：Checkpoint 4 / Business 0
终态一致性：Runs 29 / Terminal 29 / Duplicate 0
执行残留：Attempt 0 / Model 0 / Tool 0
```

## 20题 PostgreSQL Checkpoint 回归

首次 14/20，其中 5 题为 Provider 网络错误。仅对网络错误题重试一次，并按用户要求把模型网络策略调整为单次 45 秒、最多 2 次重试、2/4 秒指数退避。最终：

```text
Intent              18/18
Tool Selection      18/18
Arguments           18/18
Citation            18/18
Numeric             17/18
Task Success        18/20
P50                 18.347s
P95                 52.794s
```

最终失败：

- `eval-11`：Planner 3 次连接失败后规则降级；Tool、Evidence、Report、Validator 全部成功，因评分器要求模型 Planner 而失败；
- `eval-16`：模型报告数字未通过 Evidence 数字校验，被正确阻止成为成功终态。

详见 `FAILED_CASES.md` 和原始 `artifacts/phase2_step03/postgres_gate/evaluation/`。

## Gate 03技术结论

结论：`TECHNICAL_GO_READY_FOR_USER_REVIEW`

- 进程重启和 DB 短断后可恢复至合法终态；
- 测试中已完成副作用重复率为 0；
- 终态、Attempt 和 Event 一致；
- Checkpoint 与业务 Store 责任分离；
- 20 题确定性 Intent/Tool/Arguments 保持 18/18；
- 两个失败均有明确归因，未发现 PostgreSQL Checkpoint 语义回归。

在用户审核前不开始 Step 04。
