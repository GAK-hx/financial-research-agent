# 运行手册

## 1. 离线验证

```bash
cd /path/to/financial-research-agent
PYTHONPATH=src IDENTITY_MODE=local WEB_SEARCH_ENABLED=false \
  ELASTICSEARCH_ENABLED=false .venv/bin/pytest -q tests/test_retrieval_cache.py
```

该流程使用 fake Provider 和内存文档索引，不会访问网络，也不会读取真实 key。它验证 URL/版本、
Evidence、single-flight、部分交叉、TTL、租户隔离和分析依赖失效。

## 2. 仅验证 Tavily，不启动 ES

在本地 `.env` 增加下列配置；不要把 key 写进受版本控制文件：

```dotenv
WEB_SEARCH_ENABLED=true
WEB_SEARCH_PROVIDER=tavily
WEB_SEARCH_API_KEY=<private-key>
ELASTICSEARCH_ENABLED=false
```

此模式使用 Tavily + 进程内文档索引，适合先验证 Provider 参数与 Evidence。跨进程共享仍由
PostgreSQL RetrievalSnapshot 完成，但网页全文不会在服务重启后保留，因此不作为最终生产配置。

## 3. 启动可选 Elasticsearch

只有 Docker Desktop 已启动时执行：

```bash
docker compose --profile search up -d elasticsearch
```

本地应用连接宿主机端口时配置：

```dotenv
ELASTICSEARCH_ENABLED=true
ELASTICSEARCH_URL=http://localhost:9200
ELASTICSEARCH_INDEX_NAME=web_documents_v1
ELASTICSEARCH_INDEX_ALIAS=web_documents
```

初始化索引：

```bash
PYTHONPATH=src .venv/bin/python -m financial_research_agent.retrieval.cli init-index
```

容器内应用使用默认 `http://elasticsearch:9200`。ES 是 `search` profile，不会因普通 Compose 配置检查
自动启动。当前配置只增加一个 ES 容器、一个 volume、JVM 512 MB 和总内存 1100 MB。

## 4. 数据库迁移

在 PostgreSQL 可用后执行：

```bash
.venv/bin/alembic upgrade head
```

当前 head 是 `20260815_0008`。离线 SQL 可用下列方式检查，不连接数据库：

```bash
BUSINESS_DATABASE_URL=postgresql+asyncpg://agent:agent@localhost/financial_agent \
  .venv/bin/alembic upgrade head --sql
```

## 5. 在线最小 Gate

建议只查询一组公开信息，默认模型保持 `deepseek-v4-flash`：

```text
请分析 600519 和 300750 最近公开公告、经营进展与风险消息，列出来源与数据截止时间。
```

检查响应：

1. `plan.tasks[*].tool_name` 包含 `web_search`；
2. Evidence 的 locator 为可访问 HTTP(S) URL；
3. 发布时间未知时不得用抓取时间伪造；
4. 第二次相同查询出现 `fresh`；
5. 两个用户交叉股票出现 `inflight` 或 `partial` 汇总；
6. `presentation.lineage` 不包含其他用户记忆或最终文本。

若只配置 DeepSeek 而没有搜索 key，应先用财务或行情 Tool 验证模型链路，并单独确认 Web Tool 返回
`WEB_SEARCH_NOT_CONFIGURED`。这只能证明 Flash Agent 和失败关闭行为正常，不能替代 Tavily 联合 Gate。

2026-08-16 已通过的最小模型查询为：

```text
分析贵州茅台2025年营收和归母净利润，简要说明同比变化。
```

该请求由模型规划，调用 `financial_query`，选中 `financial_growth_analysis@1.1.0`，报告完成且校验通过。

## 6. 常见结构化错误

| 错误 | 含义 | 处理 |
|---|---|---|
| `WEB_SEARCH_NOT_CONFIGURED` | Provider 或 key 未配置 | 检查 `.env`，不要写入 Git |
| `WEB_SEARCH_RATE_LIMITED` | 搜索供应商限流 | 由 Tool 重试；持续失败后稍后重试 |
| `WEB_SEARCH_TIMEOUT` | 网络超时 | 保留失败状态；普通请求可回退旧快照 |
| `WEB_SEARCH_EMPTY` | 无可追踪来源 | 调整日期/主题，不生成虚构 Evidence |
| `WEB_DOMAIN_FORBIDDEN` | 请求域名不在白名单 | 修改服务端 allowlist，而不是让模型绕过 |
| `WEB_INDEX_UNAVAILABLE:*` | ES 不可用 | 检查 ES 健康；Tool 会按 transient 策略重试 |
| `CACHE_JOIN_TIMEOUT` | 共享工作未在等待期完成 | Job 可独立重试，过期租约可被接管 |

## 7. Git 与密钥

- `.env` 和私人 config 不上传；
- `.env.example` 只包含空占位符；
- 公开仓库前再次执行 secret scan；
- 本 Step 不改变仓库可见性，也没有提交或推送。

## 8. 网络较差时的镜像构建

Dockerfile 已设置 pip 默认超时 600 秒、20 次重试，并使用 BuildKit wheel cache。构建中断后直接重复
同一条 Compose build 命令即可复用已下载依赖；不要清理当前项目 build cache，否则会失去该能力。
