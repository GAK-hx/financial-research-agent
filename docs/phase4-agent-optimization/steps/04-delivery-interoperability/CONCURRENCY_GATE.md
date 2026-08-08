# Step 04 并发 Gate

## 冻结 Stub 结果

测试时间：2026-08-08。模式为 ASGI API + PostgreSQL Queue + 8 个 Stub Worker，
每个任务执行 15ms 确定性工作，不调用模型网络。

| VU | 完成 | 吞吐/s | API 接收 P95 | 首事件 P95 | 排队 P95 | 总耗时 P95 |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 1.159 | 600ms | 662ms | 8ms | 246ms |
| 10 | 10 | 7.215 | 909ms | 935ms | 257ms | 372ms |
| 30 | 30 | 17.516 | 1427ms | 1445ms | 612ms | 682ms |
| 50 | 50 | 14.646 | 1790ms | 1831ms | 2109ms | 2260ms |

91 个 Run 中：

- 丢失 Run：0；
- 重复终态：0；
- 跨租户读取：0；
- Provider 调用：0。

结果表明正确性通过，但 30→50 VU 时吞吐下降且排队上升。当前推荐容量是单实例最多约
30 个同时提交的研究请求；这不是 30 个同时调用模型的承诺，真实执行容量仍受 Worker、
DeepSeek 配额和 Tool 数据源约束。

本数据来自本机 Docker Desktop，不代表云生产 SLA。原始 JSON 位于本地
`artifacts/step4/load_test.json`。

## Flash Planner 并发结果

两条请求并发发送给 `deepseek-v4-flash`，仅包含问题、QuerySpec 与 Tool Schema：

| 用例 | 结果 | Tool | 延迟 | Token |
|---|---|---|---:|---:|
| technical | 通过 | `technical_analysis` | 3844ms | 1943 |
| comparison | 通过 | `stock_comparison` | 3359ms | 1951 |

两条均精确复制 QuerySpec，结果为 2/2。该 Gate 验证模型并发和结构化 Planner，不冒充完整
Evidence/Report 端到端测试；Step 03 的真实报告 Gate 仍是报告正确性证据。

