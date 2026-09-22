# Step 06 Gate 报告

- 日期：2026-08-15
- 结论：`PASS`
- 默认模型：`deepseek-v4-flash`
- 部署方式：本地 Python 3.12 离线回归；本 Step 未启动 Docker

## 功能 Gate

| 场景 | 结果 |
|---|---|
| 非研报问题 | 研报节点常数时间旁路，不调用研报 Tool |
| 研报清单 | 只调用候选 Tool，不读取正文 |
| 深度研报分析 | `report_candidate_search -> Harness 选择 -> report_content_search` |
| 候选范围 | 默认 90 天，不足 3 份扩大到 180 天；显式日期不扩大 |
| 正文范围 | 仅允许已选候选对应文档，最多 3/5 份 |
| 结构化事实 | 目标价、评级、预测等绑定原文、文档、页码和 Evidence |
| 上下文 | 深析移除候选正文外信息，按文档和父块去重 |
| 校验 | 候选清单与深析使用不同校验档；普通研报叙述不再统一严扫数字 |
| 会话引用 | 最近候选集按租户、用户、会话和 TTL 保存，支持“第 N 份” |
| LangChain/LangGraph | 两个 StructuredTool、Tool artifact、状态和 checkpoint 均可序列化 |

## 测试 Gate

| 项目 | 结果 |
|---|---:|
| Step 06 专项测试 | 6/6 |
| 全量离线测试 | 164 通过 / 23 环境跳过 |
| Ruff | 通过 |
| `git diff --check` | 通过 |
| DeepSeek V4 Flash 合成证据测试 | 通过，校验 0 错误 / 0 警告 |

在线原始结果见 `ONLINE_FLASH_GATE.md`。测试仅使用合成研报内容，没有发送本地文件、真实用户
数据或密钥。全量回归中的跳过项为需要 PostgreSQL、Milvus/RAG 额外依赖或外部环境的既有条件
测试，不是失败。

## 环境修正

项目虚拟环境一度使用 Python 3.14，导致 PyArrow 21 无预编译 wheel 并尝试源码构建。已将
`.venv` 切换到 Python 3.12 并按 `uv.lock` 同步依赖。该问题与业务代码无关，Docker 镜像未改动。

## 结论与边界

Step 06 已完成，可以进入 Step 07 的统一网络检索、Elasticsearch、single-flight、增量缓存和
分析产物复用。当前研报来源仍是已经登记并建立索引的 PDF；Step 06 不宣称实时研报覆盖，
也不会在本地索引不足时静默联网补写。
