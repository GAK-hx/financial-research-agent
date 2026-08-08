# Step 09验收证据

## Docker

- Docker Engine：29.2.0；
- PostgreSQL、Milvus、etcd、LangGraph API、Job API和Worker可由Compose启动；
- LangGraph API与Job API健康检查通过；
- 正式模型配置恢复为`deepseek-v4-pro`。

## PostgreSQL备份恢复

```text
alembic_version=20260726_0005
table_count=26
backup_bytes=14720102
restore=passed
temporary_database=deleted
```

采用Custom格式`pg_dump`，先用`pg_restore --list`检查，再恢复到
`phase2_restore_audit`临时数据库。验证完成后只删除该临时数据库，没有覆盖或清空现有
数据卷。

## 同步Run

```text
dataset=regression
case=eval-07
model=deepseek-v4-pro
task_success=1/1
api_total_ms=15943
model_calls=2
all_scored_metrics=100%
```

产物：
`artifacts/phase2_step08/regression/step09-smoke/evaluation_report.json`。

## 异步Job

```text
run_id=0106ed15578b4b1885172608fbf0e877
status=completed
success=true
planner_source=model
skill=financial_growth_analysis@1.0.0
tool=financial_query
evidence_count=1
validation_passed=true
completion_passed=true
budget_open_reservations=0
event_count=34
node_count=13
model_calls=2
tool_calls=1
context_manifests=4
attempt_no=1
```

节点从`load_memory`、`interpret`、`select_skill`、`plan`、`execute_tools`、
`generate_report`、`validate_report`、`completion_check`到`finalize`完整可见。

## 最终测试

Step 08候选镜像最终测试：

```text
Ran 137 tests
OK (skipped=19)
```

Step 09只更新交付文档和运行证据，不改变生产代码。文档一致性检查未发现仍将
Step 04—09标为“目标设计”或“未实现”的陈述。Step末最终测试结果：

```text
Ran 137 tests in 1.461s
OK (skipped=19)
```

测试日志只有FastAPI `on_event`和Starlette TestClient弃用告警，没有失败。
