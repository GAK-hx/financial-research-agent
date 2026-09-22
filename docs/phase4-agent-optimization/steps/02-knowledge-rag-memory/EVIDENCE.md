# Step 02 实现与验证证据

## 1. 外部事件知识流水线

- 新增 `KnowledgeSource` 协议和可分发本地演示来源；当前不声称已接入实时新闻；
- 原始载荷追加到 Iceberg `knowledge.raw_events_v1`；
- PostgreSQL 保存来源游标、标准化事件、状态和迁移历史；
- 事件必须经过 `CANDIDATE → ACTIVE/REJECTED`，在线接口和 LangGraph 只读取 ACTIVE；
- 来源、四类时间、内容哈希、原始版本、抽取版本、URL、Iceberg Locator 和冲突组均保留；
- Alembic `20260808_0006` 在 PostgreSQL 成功升级。

真实故障恢复验证：第一次 Cursor upsert 失败前，Iceberg 和标准化事件已提交；修复后重跑识别
`duplicates=2`，没有生成第二份有效事件，并推进游标到 `2`。再次运行结果：

```text
cursor_before=2, cursor_after=2, raw_rows=0, duplicates=0
```

PostgreSQL 只读核验为 `local_demo_events / active / 2`。API
`GET /knowledge/events?symbol=600519` 只返回 ACTIVE，并保留 `fixture=true`、`realtime=false`。

## 2. 研报混合 RAG

- 6 份登记 PDF 解析为 130 个父子 Chunk；
- BGE `BAAI/bge-small-zh-v1.5`，Embedding 维度 512；
- Dense 使用 Milvus `research_reports_v2`，关键词使用 SQLite FTS5；
- RRF 使用 Dense Anchor 保护第一条语义 Evidence，关键词补充和重排后续候选；
- 增量任务按文档内容版本只重算变化文档；无变化复跑结果为
  `changed_documents=0, inserted=0`；
- Milvus 与关键词索引收尾计数均为 130。

冻结集修复前，Hybrid Recall 为 1.0，但 NDCG 为 0.8577，未通过 Gate；修复后：

| 路径 | Recall@5 | MRR@5 | NDCG@5 | 平均延迟 |
|---|---:|---:|---:|---:|
| Dense | 1.0000 | 1.0000 | 1.0000 | 7.13 ms |
| Hybrid | 1.0000 | 1.0000 | 1.0000 | 8.52 ms |

逐题结果由本地Gate生成到`artifacts/phase4/step02/rag_evaluation.json`，运行产物不进入Git。

## 3. 记忆与上下文

- Memory 明确区分 Session、Preference 和 Episodic；程序记忆继续由 Git + Skill Registry 管理；
- 情节记忆只允许验证通过的终态 Run 反思写入，默认 TTL 180 天并标记历史用途；
- 支持写、读、更新、反思、遗忘、到期和不可变版本历史；
- PostgreSQL 实测租户/用户隔离、跨会话偏好、同会话指代、TTL、删除、并发版本和反思幂等；
- Context Manifest 记录 Item 来源、版本、选择/裁剪原因、估算 Token 和输出预留；
- 确定性压缩不覆盖 Evidence，模型摘要只处理 Memory，且禁止引入来源中不存在的新数字；
- 稳定前缀用于服务商可能提供的 Prefix Cache；客户端未伪造 KV Cache。

## 4. 集中验证

| 验证 | 结果 |
|---|---:|
| Compose 配置解析、Python 静态编译、diff whitespace | 通过 |
| Step 02 聚焦测试（修复后） | 27/27 通过 |
| Knowledge Iceberg + PostgreSQL 故障恢复 | 通过 |
| Knowledge 游标空批次复跑 | 通过 |
| RAG 首次索引 | 6 文档 / 130 Chunk |
| RAG 无变化增量复跑 | 0 文档变化 / 0 写入 |
| Dense/Hybrid 冻结集 Gate | 通过 |
| Docker + PostgreSQL 完整回归 | 157/157 通过 |
| 最新 App、Job API、Worker | 健康并运行 |
| ACTIVE-only Knowledge HTTP | 通过 |
| 真实 DeepSeek v4 Flash | 通过 |

## 5. 真实 DeepSeek v4 Flash Gate

用户明确授权后执行一条端到端问题：

```text
结合已验证事件和研报，分析贵州茅台渠道改革的影响与风险
```

结果：

| 字段 | 结果 |
|---|---|
| Run ID | `2980b8d5c69d45789006941e66c33ed9` |
| 模型 | `deepseek-v4-flash` |
| Planner | 模型结构化规划 |
| Tool | Hybrid `report_search`，成功，5 条 Evidence |
| Knowledge Context | 1 条 ACTIVE 事件，含 Iceberg Locator 和抽取版本 |
| 模型调用 | 3 次 |
| Tool 调用 | 1 次 |
| Token | 19,120 |
| 报告修订 | 1 次受控修订 |
| Completion | 通过 |
| 最终 Validator | 通过，0 错误、0 警告 |
| 总耗时 | 34,997 ms |

初稿的一个校验错误进入 `revise_report` Context，修订后通过；Evidence 保护哈希在生成和修订阶段
一致，预算 `open_reservations=0`。

本次也验证了责任边界：ACTIVE Event 已进入 Context，但当前报告 Schema 只允许引用正式
Evidence ID，Step 02 尚未提供 Event Evidence Tool，因此最终报告只使用 5 条研报 Evidence，
没有把 Context 中的事件冒充成可引用证据。事件分析 Tool/Skill 在 Step 03 实现。

## 6. 已知限制

- 当前事件来源是项目演示 Fixture，不是实时公告或新闻；替换真实来源前必须审核授权、稳定性和
  时间字段；
- 冻结 RAG 集只有 4 题、6 份 PDF，只证明当前小样本无回归，不代表广泛泛化能力；
- Hybrid 比 Dense 平均增加约 1.38 ms；扩大语料后应重新评估 Recall、NDCG、P95 和资源占用；
- PyMuPDF 的 `fitz` 导入方式有弃用警告，后续可机械迁移为 `pymupdf`；
- FastAPI `on_event` 和 TestClient 存在上游弃用警告，不影响本 Step 正确性。
- 当前 Knowledge 是受控 Context 输入，还不是报告可引用的 Event Evidence；正式事件结论需等待
  Step 03 的事件 Tool 与 Skill。
