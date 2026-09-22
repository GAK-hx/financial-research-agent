# Step 08.3 多用户并发与恢复 Gate 报告

## 结论

状态：`PASS`。

本轮在真实 Spring Gateway、Redis、FastAPI Job API、PostgreSQL 和 Python Worker 上完成集中验收。
高并发部分使用冻结 Worker，避免把调度压测变成模型费用压测；最后使用
`deepseek-v4-flash` 完成两条真实 Agent 端到端查询。

## 5 用户交叉查询

使用 5 个独立 API client，映射到 4 个租户和 5 个用户。每个用户提交 5 个单股票任务，共 25 个
逻辑任务，覆盖 17 支股票；`600519`、`300750`、`601318`、`600036` 等标的在用户间重复。

| 检查 | 结果 |
|---|---:|
| 首次并发提交 | 25/25 返回 202 |
| tenant/user 身份映射错误 | 0 |
| 25 个幂等重放 | 25/25 `created=false` 且 run_id 不变 |
| 同租户跨用户读取 | 404 |
| 跨租户读取 | 404 |
| 单用户瞬时 15 请求 | 10 个 202，5 个 429 |
| 测试任务清理 | 25/25 cancelled |
| 模型调用 | 0 |

原始结果：`artifacts/step8/gateway_multiuser_gate.json`；人读摘要：
`artifacts/step8/gateway_multiuser_gate.md`。

## 公平队列与 50 路上限

冻结 Worker 分别执行 1、10、30、50 VU，共 91 个任务。50 VU 时吞吐为 38.497 run/s，API P95
为 928.828 ms，排队 P95 为 536 ms，总耗时 P95 为 583 ms。

所有档位共同满足：

```text
lost_runs=0
duplicate_terminal=0
cross_tenant_leaks=0
provider_calls=0
```

原始结果：`artifacts/step4/load_test.json`；人读摘要：`artifacts/step4/LOAD_TEST.md`。

Step 07 已证明 5 用户、25 个原子检索、11 个去重标的只执行 11 次外部工作，14 个请求加入
inflight，重复外部调用为 0。本轮没有重复执行该外部检索压测，而是通过全量回归确认共享检索
single-flight、依赖版本和输出身份隔离没有被 Spring/Redis 接入层破坏。

## Redis、Spring、Worker 与 SSE 恢复

1. 经 Gateway 创建任务，冻结 Worker 领取后直接退出，留下 `attempt_no=1` 和 30 秒租约；
2. 在租约存续期间重启 Redis 和 Spring Gateway；
3. 租约过期后由第二个冻结 Worker 接管并完成，`attempt_no=2`；
4. 客户端使用 `Last-Event-ID: 2` 重连 SSE，仅收到事件 3 `job_reclaimed` 和事件 4
   `job_terminal`；
5. 最终状态为 `completed`，终态事件只有一个，trace 中模型调用和工具调用均为 0。

这证明 Redis 通知和 Spring 进程都不是任务事实来源；PostgreSQL Job、Event 和租约足以恢复执行与
事件回放。

## DeepSeek V4 Flash 端到端

| Case | 结果 | Model/Tool | 说明 |
|---|---|---:|---|
| `cross_stock_comparison` | PASS | 2/1 | 600519、300750 比较，报告校验通过 |
| `single_technical` 修复后复测 | PASS | 2/1 | 600519 技术分析，报告校验通过 |

默认模型由运行中 Worker 确认为 `deepseek-v4-flash`。单股票首次执行为 cache miss；修复后复测命中
fresh AnalysisArtifact，`refresh_performed=false`、`external_calls_saved=1`，说明查询、分析与输出分离
后可以复用分析，但仍为当前用户重新生成报告。

原始结果：

- `artifacts/step8/flash_e2e_gate.json`：初次两案例及失败原文；
- `artifacts/step8/flash_e2e_gate.md`：初次人读报告；
- `artifacts/step8/flash_e2e_retest.json`：修复后单案例完整结果；
- `artifacts/step8/flash_e2e_retest.md`：修复后人读报告。

## 集中修正

首次单股票报告的事实和 Evidence 正确，但校验器误判：

```text
risk[2]:NUMERIC_UNSUPPORTED:60.0
risk[2]:NUMERIC_UNSUPPORTED:-10.45%
```

根因有两个：

1. “过去 60 天”中的窗口长度被当成需要 Evidence 精确匹配的业务数值；
2. 最大回撤按正数幅度保存，但后文“价格下跌 10.45%”被再次施加负号。

修复后，`日/天`窗口不进入事实数值比较；同一句最大回撤描述保持幅度语义。普通“同比下降 12.10%”
仍按负方向匹配，未放松一般数值真实性检查。新增针对性用例通过，原失败报告无需再次调用模型即可在
本地通过校验，随后真实 Flash 复测通过。

## 集中回归

```text
Python unittest: 187 run, 24 skipped, all non-skipped passed
Java Gateway: 3 tests passed
Java 21/Maven Docker package: PASS
5-user Gateway Gate: PASS
1/10/30/50 VU frozen queue Gate: PASS
Redis/Spring/Worker/SSE recovery Gate: PASS
DeepSeek V4 Flash final cases: 2/2 PASS
```

FastAPI `on_event`、TestClient 和本机 PyArrow CPU 探测仍有既有弃用/权限提示，不影响本轮结论。

## 最终运行状态

- 临时 5 用户测试凭据已经撤销，Gateway 恢复 `.env` 正常配置；
- Gateway、Job API、Redis、PostgreSQL 健康，Worker 正常运行；
- 当前仍是开发 Compose 形态，调试端口保留；生产端口隔离使用
  `docker-compose.gateway.yml`；
- GitHub 不公开、不推送，继续等待用户完成组件介绍与密钥清理后的明确许可。
