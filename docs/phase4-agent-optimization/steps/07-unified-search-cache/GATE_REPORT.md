# Step 07 Gate 报告

## 结论

状态：`PASS_PARTIAL_ONLINE`。

统一检索、single-flight、增量刷新、分析依赖和输出隔离已通过离线 Gate；真实 PostgreSQL 迁移、
Elasticsearch 读写以及 DeepSeek V4 Flash Agent 流程已通过在线 Gate。当前没有 Tavily key，因此
“Tavily 网络检索 -> ES -> Flash 报告”的完整联合流程仍保持 `PENDING`。

## 并发样例

5 个用户各查询 5 只股票，共 25 个逻辑检索：

```text
u1: 600519 300750 601318 000858 600036
u2: 600519 300750 000858 002594 601166
u3: 600519 002594 601166 600276 000333
u4: 300750 601318 600276 000333 600030
u5: 600036 000858 002594 600030 601398
```

| 指标 | 结果 |
|---|---:|
| 逻辑检索 | 25 |
| 去重股票 | 11 |
| 实际外部工作 | 11 |
| inflight join | 14 |
| 重复外部调用 | 0 |
| 首轮调用节省 | 14 / 25（56%） |

第二轮用户查询 `600519、300750、601398、600104、000001`：前三只直接复用，只为后两只创建工作，
即 5 个逻辑任务只新增 2 次外部工作。

将 `600519、300750、601398` 的 TTL 人工过期后，三只股票各产生一次 `stale` generation；网络 Tool
使用旧水位减 24 小时作为新起点，不重查不受影响的其他股票。

## 权限与分析失效

- `public` key 主动删除 tenant_id，不同租户得到相同公共 key；
- `tenant` key 强制包含 tenant_id，不同租户 key 不同；
- 未校验 AnalysisArtifact 被拒绝写入；
- 依赖快照的 Evidence hash 改变后，仅对应 AnalysisArtifact miss；
- AnalysisArtifact 不保存用户记忆、偏好、问题原文或最终报告；
- PresentationEnvelope 每次重新绑定当前 tenant/user/session。

## 全量回归原始摘要

```text
168 passed, 23 skipped, 19 warnings in 11.07s
```

跳过项为需要 PostgreSQL/Docker/外部服务的既有可选集成测试。warnings 为 FastAPI `on_event` 和
TestClient 的既有弃用提示，不是本 Step 新增失败。

## 真实基础设施与模型 Gate

| 检查 | 结果 |
|---|---|
| PostgreSQL migration | PASS，数据库升级至 `20260815_0008`，5 张新增表可查询 |
| Elasticsearch | PASS，9.3.6 单节点健康，cluster=`green` |
| ES 索引与 alias | PASS，`web_documents_v1` / `web_documents` |
| ES 文档生命周期 | PASS，首次写入 `new=1`、同内容 `unchanged=1`、内容变化 `updated=1` |
| ES 版本与查询 | PASS，更新后 `content_version=2`，BM25/过滤查询命中 1 条 |
| Provider 未配置 | PASS，返回 `WEB_SEARCH_NOT_CONFIGURED`，不伪造 Evidence |
| DeepSeek V4 Flash | PASS，HTTP 200，模型规划、Tool、Skill、报告与校验链路完成 |

Flash 最小查询使用公开的贵州茅台财务问题，不包含用户私有数据。结果摘要：

```text
run_id=862a9f34b1764e428fef06d21c3a0f97
planner_source=model
tool=financial_query, success=true, cache_decision=miss
selected_skill=financial_growth_analysis@1.1.0
evidence_count=1
reporting_status=completed
validation_passed=true
```

首次在线运行发现 8 个内置 Skill 的实现已变化但版本仍为 `1.0.0`，持久化治理按预期拒绝静默覆盖。
本轮将这些 Skill 升级为 `1.1.0` 并声明 supersedes，随后在线流程通过。网络波动期间 Flash 调用发生
自动重试，最终多次请求均返回 200。

## 其他检查

| 检查 | 结果 |
|---|---|
| Python compileall | PASS |
| Ruff | PASS |
| Alembic offline SQL | PASS，662 行，head=`20260815_0008` |
| Docker Compose 配置解析 | PASS |
| ES/Python client | server 9.3.6 / client 9.3.0，同 minor 兼容 |
| 默认模型 | `deepseek-v4-flash` |
| Docker 服务 | app/job-api/PostgreSQL/ES 健康，Worker 正常运行 |
| ES + Flash 在线 Gate | PASS |
| Tavily + ES + Flash 在线 Gate | PENDING（缺少 `WEB_SEARCH_API_KEY`） |

## 集中修正记录

1. 首次设计把完整用户问题放入公共检索键，导致股票重叠但问法不同无法合并；已改为稳定事件主题。
2. 旧 `event_search` Skill 测试与新 `web_search` 冲突；保留旧 Tool 兼容，新流程优先 Web Tool。
3. Tool 调用已完成但共享快照写入前崩溃时可能遗留租约；恢复路径现在会用已持久化 ToolResult 幂等补写。
4. 普通请求刷新失败曾直接丢失旧数据；现在允许带明确标记的 stale fallback，“最新”请求仍失败关闭。
5. 同 URL 在多股票并发索引时可能覆盖股票标签；upsert 现在合并 stock/topic 标签。

## Docker 清理与构建修正

- 保留本项目 8 个既有容器，删除 9 个旧项目镜像和 6 个带 `financial-agent` 标签的旧 volume；
- 删除清理时发现的 40.28 GB build cache；未删除来源无法确认的匿名 volume；
- 为依赖构建增加 pip 600 秒超时、20 次重试及 BuildKit cache mount，网络中断后可以复用已下载 wheel；
- 当前项目重新构建产生的新镜像与 2.425 GB build cache 均保留，它们不是遗留垃圾。

## 尚未宣称通过的内容

- 未验证真实 Tavily 账户的限流、日期和正文返回；
- 未执行真实 Web Search Evidence 到 DeepSeek Flash 最终报告的在线演示；
- 未因此重写最终 README，也未把 Step 标为 `COMPLETE`。
