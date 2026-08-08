# 06 质量、安全、评测与最终交付

## 1. 质量目标

项目完成的标准不是“能生成报告”，而是能够用保存的原始结果证明：

- 正确选择 Intent、Skill 和 Tool；
- 参数和股票/日期不被模型改写；
- Evidence 完整且来源可追溯；
- 数字和引用通过校验；
- 故障后恢复不产生重复副作用；
- Policy、Budget 和 Memory 隔离不可绕过；
- Docker 环境可复现。

## 2. 评测矩阵

| 数据集 | 数量 | 用途 |
|---|---:|---|
| Phase 1 Regression | 20题 | 验证既有行为不退化 |
| Phase 2 Holdout | 至少30题 | 验证未见问题 |
| Stability | 10题×3次 | 验证路径和结论稳定性 |
| Fault Cases | 按故障类型 | 验证恢复与幂等 |
| Security Cases | 按策略类型 | 验证越权、注入和隔离 |

Holdout 不能用于开发调参。评测必须冻结：

- 代码和镜像；
- 配置；
- Skill 和 Prompt；
- 模型；
- 数据 Snapshot；
- 评分规则。

## 3. 核心指标

- 合法终态率；
- 恢复成功率；
- 重复 Model/Tool 副作用率；
- Intent/Skill/Tool/参数准确率；
- 必需 Evidence 覆盖率；
- 引用有效率和数字一致率；
- Policy 攻击拦截率与误拦率；
- Budget 超限率；
- Memory 跨租户泄漏率；
- Compression 数字/来源保留率；
- P50/P95、Token、费用、CPU、内存和数据库增长。

## 4. 故障注入

目标故障：

- Worker Kill；
- API 重启；
- PostgreSQL 短断；
- Provider DNS、连接超时、ReadTimeout、429、5xx；
- Tool超时和数据为空；
- SSE断开；
- Lease过期和双 Worker 竞争；
- Artifact写入失败。

每个故障都要验证：

1. 是否进入明确状态；
2. 是否保存最近合法 Checkpoint；
3. 是否可以继续；
4. 是否重复外部调用；
5. 是否只写一个终态；
6. 是否留下可定位的 Event 和指标。

## 5. 安全测试

阻断性场景：

- Prompt Injection 诱导调用未授权 Tool；
- 模型生成 SQL、Shell 或 Python；
- Skill 组合扩大权限；
- 参数越过日期、行数或股票范围；
- Budget 并发 Reserve 超限；
- Memory 污染和跨用户/租户访问；
- 日志、SSE 或 Trace 泄漏 Key/隐藏推理；
- Simulation 数据进入正式 Evidence；
- 未通过 Validator 的报告被标为成功。

任何越权成功、跨租户泄漏、重复副作用或 Evidence 来源丢失都阻止进入最终验收。

## 6. A/B测试

分别比较：

- Skill 开/关；
- Memory 开/关；
- Compression 开/关。

观察质量、Token、费用、延迟、Validator通过率和数字/引用一致性。只有实测证明收益且不破坏 Evidence，功能才默认启用。

## 7. 最终验收

Phase 2 Step 09与Phase 3 Step 03已经执行：

1. 构建固定镜像；
2. Docker Compose 启动；
3. 初始化数据库、数据和索引；
4. 健康检查；
5. 提交完整 Run；
6. 观察 SSE；
7. 查看 Tool、Evidence、报告和 Trace；
8. 注入一次中断并 Resume；
9. 验证 Memory 查询与删除；
10. 执行关键 Regression、安全和恢复用例；
11. 采集资源、Token 和费用；
12. 用户人工确认。

## 8. 演示脚本

最终演示应体现系统价值，而不是只展示聊天：

```text
提交问题
  → 返回Run ID
  → SSE显示Interpret/Skill/Plan
  → 展示受控Tool与参数
  → 展示Evidence来源
  → 展示报告Claim与引用
  → 展示Validator/Completion
  → 杀掉Worker
  → 新Worker从Checkpoint继续
  → Trace证明没有重复调用
```

## 9. 最终交付物

- LangChain ChatModel/Runnable、Structured Output、StructuredTool、Message与Retriever；
- LangGraph StateGraph 与 PostgreSQL Checkpoint；
- 业务 Store 与 Alembic；
- Skill Registry 与首批 Skill；
- Model/Tool Gateway；
- Policy Engine 与 Budget Ledger；
- Memory Manager 与 Context Compression；
- Job API、Worker、SSE、Cancel/Resume；
- Regression/Holdout/Stability/Fault/Security 报告；
- Docker Compose、Runbook、API文档和演示脚本；
- 技术总结、已知限制与简历表述。

## 10. 必须长期披露的边界

- 当前数据主要支持日线和中长期研究；
- 只支持只读研究，不执行交易；
- 第一版不允许无限 Replan；
- 模型输出必须通过 Evidence 与 Validator；
- Provider 网络和模型质量是外部不确定性；
- 评测数字只代表冻结数据、模型和 Prompt 版本；
- LangChain是标准Agent接口，LangGraph是状态运行时，金融治理层由项目实现；
- Hermes/Pi 只作为设计参考，不冒充项目依赖或实现。
