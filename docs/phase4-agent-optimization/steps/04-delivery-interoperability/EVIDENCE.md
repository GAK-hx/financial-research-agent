# Step 04 验收证据

## 1. 冻结并发基准

- 时间：2026-08-08；
- 结构：ASGI API + PostgreSQL Queue + 8 个确定性 Stub Worker；
- 负载：1、10、30、50 VU，共 91 个 Run；
- 模型调用：0；
- 丢失 Run：0；
- 重复终态：0；
- 跨租户读取：0；
- 原始产物：本地 `artifacts/step4/load_test.json`。

详细分层延迟见 [CONCURRENCY_GATE.md](CONCURRENCY_GATE.md)。

## 2. DeepSeek V4 Flash

- 仅验证 Planner 结构化并发；
- 输入只包含问题、QuerySpec 和 Tool Schema，不包含本地行情、财务、研报或 Event Evidence；
- 两条请求并发，2/2 通过；
- 模型：`deepseek-v4-flash`；
- 原始产物：本地 `artifacts/step4/flash_gate.json`。

## 3. 自动化回归

| 范围 | 结果 |
|---|---|
| 完整 PostgreSQL/Compose 回归 | 168/168 通过 |
| 离线完整回归 | 145 通过、23 项 PostgreSQL 条件测试跳过 |
| PostgreSQL JobStore 专项 | 5/5 通过 |
| Provider Capacity 专项 | 2/2 通过 |
| Ruff | 通过 |
| Compose 配置 | 通过 |
| Secret Scanner | 通过 |

PostgreSQL 回归使用项目 Compose 提供的正式数据库变量和重建后的 Python 3.11 镜像。记忆 API
测试使用 API Key 模式与随机租户/用户，重复执行不依赖历史数据库为空。

## 4. 部署验收

- App：Compose `healthy`，容器内 `/health` 返回 `ready`；
- Job API：Compose `healthy`，容器内 `/health` 返回 `ready`；
- Demo：`/demo` 返回 HTTP 200；
- 指标：`/metrics` 返回 HTTP 200；
- Worker：恢复运行，日志确认 `concurrency=2`；
- PostgreSQL：`healthy`，Alembic 已升级到当前 Head；
- Milvus：运行中。

## 5. 发布边界

- `.env`、Lake、模型缓存、第三方 PDF/研报和运行产物都在 Git 忽略范围；
- Step 04 Gate 使用的身份值是测试凭据，不是供应商 Key；
- 当前树通过仓库 Secret Scanner 后才可进入发布候选；
- 历史对话中出现过真实 DeepSeek Key，因此 GitHub 推送仍以控制台轮换为前置条件；
- 未创建远端仓库，也未执行提交或推送。
