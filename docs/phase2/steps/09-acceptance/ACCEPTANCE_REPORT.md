# Step 09阶段验收报告

验收日期：2026-07-27  
代码状态：交付候选  
Gate结论：`PASSED`，等待用户最终人工确认

## 1. 验收结论

第二阶段计划内的九个Step均已实现。当前系统是基于LangGraph和PostgreSQL的可恢复、
只读金融分析Agent，并在框架外实现了Skill、Model/Tool Gateway、Policy/Budget、
Memory/Context、Evidence/Validator、Completion和Job Worker治理。

本次没有清空现有持久卷。为避免破坏已经采集的Iceberg、Milvus和评测数据，“空环境”
验收采用以下等价且安全的方式：

1. 使用Dockerfile重新构建候选镜像；
2. 由Compose和Alembic重新创建/检查服务与Schema；
3. 将生产结构的PostgreSQL备份恢复到新建临时数据库；
4. 使用当前镜像执行完整测试、同步烟雾Run和异步Job Run；
5. 删除只为恢复验证创建的临时数据库。

这证明镜像、迁移、备份和运行入口可复现，但不声称在本轮重新下载了所有历史数据或
重新生成了全部向量索引。

## 2. Docker与恢复验收

| 项目 | 结果 |
|---|---|
| Docker Engine | 29.2.0 |
| LangGraph API | Healthy，宿主端口8001 |
| Job API | Healthy，宿主端口8002 |
| PostgreSQL | Healthy |
| Milvus / etcd | Running |
| Alembic版本 | `20260726_0005` |
| 临时恢复库表数 | 26 |
| 备份格式与大小 | PostgreSQL Custom，14,720,102 Bytes |
| 恢复验证 | 成功；临时数据库已删除 |

## 3. 最终运行证据

### 同步烟雾Run

- 数据集：Regression `eval-07`；
- 模型：`deepseek-v4-pro`；
- 任务成功率：1/1；
- Intent、Skill、Tool、参数、Evidence、引用、数字、Completion与Budget闭合：100%；
- 端到端耗时：15.943秒；
- 模型调用：2次。

原始产物：
`artifacts/phase2_step08/regression/step09-smoke/evaluation_report.json`。

### 异步Job Run

- Run ID：`0106ed15578b4b1885172608fbf0e877`；
- 问题：分析贵州茅台最近三年的营收和利润；
- 状态：`completed`，`success=true`；
- Planner：Model；
- Skill：`financial_growth_analysis@1.0.0`；
- Tool：`financial_query`；
- Evidence：1；
- Validator、Completion：通过；
- Budget开放Reservation：0；
- Event：34条；
- Trace：13个节点、2次Model Call、1次Tool Call、4个Context Manifest；
- 执行尝试：1次。

Trace包含从`load_memory`到`finalize`的完整节点序列，证明Job API、Worker、LangGraph、
Gateway、Evidence和终态审计使用同一条正式路径。

## 4. 完整测试与评测

- 最终镜像：137项测试通过，19项按可选外部环境条件跳过；
- Regression / Pro：20/20；
- Holdout / Pro：29/30，96.67%；
- Harness 10×3：Skill、Tool、Evidence、Evidence数字和报告结构稳定性均为100%；
- 原预算泄漏缺陷修复后连续3次复测：Budget闭合100%；
- 阻断项：越权、Memory泄漏、Evidence来源丢失、重复副作用、Budget超限和凭证泄漏均为0。

详细数字见
[`../08-reliability-evaluation/FINAL_EVALUATION_REPORT.md`](../08-reliability-evaluation/FINAL_EVALUATION_REPORT.md)。

## 5. 验收清单

| 能力域 | 状态 | 主要证据 |
|---|---|---|
| LangGraph状态图与恢复 | 通过 | Step 02、03 Evidence |
| PostgreSQL Checkpoint与业务审计 | 通过 | Step 03；本次备份恢复 |
| Skill Registry与版本快照 | 通过 | Step 04 Evidence |
| Gateway、Policy与Budget | 通过 | Step 05；Step 08缺陷审计 |
| Memory与Context Compression | 通过 | Step 06；A/B产物 |
| Job API、Worker、SSE与Trace | 通过 | Step 07；本次异步Job |
| Regression/Holdout/Stability | 通过 | Step 08最终报告 |
| Docker部署与资源边界 | 通过 | Compose、健康检查和资源报告 |
| 运维、演示和技术交付文档 | 通过 | 本Step文档 |

## 6. 最终边界

- 当前只读，不下单，不执行交易；
- 数据面向日线和中长期分析，不宣称分钟或实时行情；
- 股票池和正式评测主要覆盖`600519`、`300750`；
- Replan预算固定为0，当前不允许模型自主循环扩展任务；
- 模型只能通过受控Tool读取数据，不能运行SQL、Shell或任意Python；
- LangGraph提供图运行和Checkpoint，金融治理层由项目实现；
- Hermes、Pi仅用于设计参考，未作为实际运行时；
- Flash适合开发回归，当前正式报告使用V4 Pro。

## 7. Gate 09

工程验收项已全部完成。唯一剩余动作是用户人工查看演示、文档与边界，确认后将
`docs/phase2/PROGRESS.md`和本Step状态从`Pending Review`改为`Accepted/COMPLETED`。

