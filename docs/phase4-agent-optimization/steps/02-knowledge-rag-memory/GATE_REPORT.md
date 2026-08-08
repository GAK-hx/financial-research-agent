# Step 02 Gate 报告

- 日期：2026-08-08
- 结论：`TECHNICAL_GO`

## Gate 判定

| Gate | 结论 | 证据 |
|---|---|---|
| 知识任务可恢复且无重复有效事件 | 通过 | 故障重试 duplicates=2，ACTIVE 总数仍为 2，随后空批次 |
| Candidate 不进入在线报告 | 通过 | 状态机测试；HTTP 和 LangGraph 只调用 `search_active` |
| 知识结论保留来源、时间、版本和 Evidence | 通过 | API 实际响应含 URL、四类时间、版本、Locator 和引用 |
| 混合检索不低于 Dense | 通过 | 两者 Recall/MRR/NDCG 均为 1.0 |
| 增量索引不重算未变化文档 | 通过 | 6 文档未变化时 changed=0、inserted=0 |
| 跨用户记忆泄漏为 0 | 通过 | PostgreSQL 租户/用户/会话隔离测试通过 |
| 压缩保留数字、日期、实体和 Locator | 通过 | Evidence 保护哈希与新增数字拒绝测试通过 |
| 完整确定性回归 | 通过 | 157/157 |
| 默认 Flash 小规模真实链路 | 通过 | success/completion/validation 均通过，1 次受控修订 |

## 结论解释

Step 02 的代码、迁移、Docker、Iceberg/PostgreSQL/Milvus/SQLite 真实链路、157 项确定性测试和
一条真实 Flash 链路均通过，可进入 Step 03。真实请求使用模型规划、Hybrid RAG、Context
Manifest、Evidence 校验和一次受控报告修订，最终无校验错误且所有预算预留已关闭。

事件知识目前是带来源和版本的 Context 输入，还不是报告 Schema 可引用的 Event Evidence。模型在
本次测试中没有把事件 Context 冒充成正式证据；Step 03 需要增加事件查询 Tool/Skill，之后才能
对事件结论执行与研报相同的 Evidence 校验。

## 授权范围

实际发送范围为用户测试问题、已验证演示事件正文、研报检索命中的文本片段、Tool Schema、计划
上下文和 Evidence 元数据；未发送 `.env`、API Key、数据库口令或未命中的完整 PDF。本次只执行
一条请求链路，模型为 `deepseek-v4-flash`。
