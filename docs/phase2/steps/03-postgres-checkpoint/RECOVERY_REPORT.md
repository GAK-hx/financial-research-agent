# Step 03 恢复、幂等与一致性报告

## 结论

PostgreSQL Checkpoint 和业务持久化满足 Gate 03 的技术条件：跨进程恢复成功、重复 Resume 不重复工具调用、数据库短断后状态可恢复、终态唯一、业务 Alembic 不修改 LangGraph 表。

## 验证结果

| 场景 | 结果 |
|---|---|
| 首进程 Interrupt | `interrupted=true`，Tool 调用 0 |
| 新进程 Resume | `stage=completed`，Tool 调用 1 |
| 完成后重复 Resume | `stage=completed`，Tool 调用 0 |
| PostgreSQL 停机时 Resume | 明确 `OperationalError`，Tool 未执行 |
| PostgreSQL 恢复后 Resume | 原 Thread 正常完成，Tool 调用 1 |
| 已完成 Tool 结果复用 | 第二次执行不调用 Tool |
| 已完成 Run 重放 | 第二个 Service 实例不调用 Model/Tool |
| Cancel | 首次写入成功，重复请求幂等 |
| 活跃租约 | 未过期调用不能被重复占用 |
| 唯一终态 | 29 Runs / 29 Terminal Results / 重复终态 0 |
| 残留执行 | Running Attempts/Model Calls/Tool Calls 均为 0 |

## 迁移责任边界

在独立临时数据库中先由 `AsyncPostgresSaver.setup()` 创建 Checkpoint 表，再执行 Alembic upgrade/downgrade。降级后查询结果：

```text
checkpoint_tables=4
business_tables=0
```

说明业务迁移只删除 7 张 Harness 业务表，不触碰 LangGraph 的
`checkpoint_migrations`、`checkpoints`、`checkpoint_blobs` 和
`checkpoint_writes`。

## Serializer与安全

- 关闭 Pickle fallback；
- 严格 MsgPack allowlist；
- 单个序列化值默认上限 2 MB；
- AES 开关 Round Trip 通过；
- 错误 AES Key 无法解密；
- Key 不进入 State、数据库、日志或文档；
- 最终运行未出现严格 MsgPack 降级告警。

## 容量基线

完成测试、恢复审计和 20 题回归后：

```text
database_bytes=12,924,595
checkpoint_blobs=974,848
checkpoint_writes=1,490,944
checkpoints=573,440
terminal_results=532,480
tool_calls=385,024
model_calls=172,032
```

Step 03 只记录增长，不启用自动清理；清理、保留和备份演练进入 Step 08/09。

## 已知边界

- Provider 不提供服务端幂等键时，响应返回与本地提交之间仍有极小崩溃窗口；
- 当前所有 Tool 只读，因此租约过期后的恢复不会产生外部写副作用；
- Cancel/Resume 是 Service 底层能力，Job API 端点属于 Step 07；
- 自动清理、跨租户隔离和 Worker 领取不在 Step 03 范围。
