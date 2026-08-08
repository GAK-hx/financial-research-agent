# Step 03 评测失败明细

## 1. 结论

本文件记录 PostgreSQL Checkpoint 模式 20 题回归的失败过程和最终输出。所有原始响应均已脱敏保存，未包含 API Key。

重试策略调整前：

| 执行 | 结果 | 说明 |
|---|---:|---|
| 首次完整 20 题 | 14/20 | 5 个 Provider 网络错误，1 个报告数字校验失败 |
| 仅重试 5 个网络错误题 | 17/20 | 3 题恢复，2 题仍受网络影响 |

将模型请求调整为单次 45 秒、最多重试 2 次、指数退避 2/4 秒后：

| 最终指标 | 结果 |
|---|---:|
| Task Success | 18/20 |
| Intent | 18/18 |
| Tool Selection | 18/18 |
| Arguments | 18/18 |
| Citation | 18/18 |
| Numeric Consistency | 17/18 |
| P50 / P95 | 18.347s / 52.794s |

最终未通过 `eval-11` 和 `eval-16`。两题均进入合法、可解释的受控终态，没有持久化错误、工具越权、Evidence 丢失或未校验报告被标为成功。

完整机器可读产物：

- `artifacts/phase2_step03/postgres_gate/evaluation/evaluation_report.json`
- `artifacts/phase2_step03/postgres_gate/evaluation/runs/eval-11.json`
- `artifacts/phase2_step03/postgres_gate/evaluation/runs/eval-16.json`

## 2. eval-11：Planner 网络重试耗尽后规则降级

### 输入与期望

```text
问题：宁德时代机构如何看技术创新
期望 Intent：report
期望股票：300750
期望 Tool：report_search
```

### 网络与降级轨迹

Planner 请求发生 `ConnectError`，分别等待 2 秒和 4 秒后重试，总计 3 次仍未连接成功。系统随后执行既定的 `rule_fallback`，而不是让模型绕过流程或直接失败。

```text
model_request_retry attempt=1 max_retries=2 delay_seconds=2 error=ConnectError
model_request_retry attempt=2 max_retries=2 delay_seconds=4 error=ConnectError
planner_source=rule_fallback
```

### 实际计划和工具输出

```yaml
run_id: c02330a6a4b649339ddcbd5f642994aa
reporting_status: completed
plan:
  task_id: report
  tool_name: report_search
  arguments:
    stock_code: "300750"
    query: "宁德时代机构如何看技术创新"
tool:
  success: true
  latency_ms: 39319
  evidence_count: 5
validation:
  passed: true
```

报告摘要：

> 国信证券和交银国际证券均看好宁德时代的技术创新。国信证券认为公司产品全面升级，技术创新夯实龙头领先优势，并指出公司超级科技日推出超充、高能量密度等新品，先发钠电赛道并计划 2026Q4 量产。交银国际证券认为技术迭代驱动多维增长，补能生态加速布局，给予买入评级。

报告共生成 6 条 Claim，全部带当前 Run 的 Evidence ID；最终 Validator 为 `passed=true`，引用和数字评分也全部通过。

### 为什么评测仍判失败

```yaml
response.success: true
http_contract: true
intent_accuracy: true
tool_selection_accuracy: true
argument_accuracy: true
citation_accuracy: true
numeric_consistency: true
task_success: false
score_errors:
  - TASK_NOT_COMPLETED
```

评分器要求合法题必须由模型 Planner 完成，因此 `planner_source=rule_fallback` 被计为失败。这个结果说明业务链路已完成，但 Provider 网络稳定性不满足当前评测的模型路径要求。

## 3. eval-16：报告数字被 Validator 拒绝

### 输入与期望

```text
问题：600519今年行情与券商观点
期望 Intent：comprehensive
期望区间：2026-01-01 至 2026-07-15
期望 Tool：market_query、indicator_calculator、report_search
```

### 计划、工具与 Evidence

```yaml
run_id: 3bac42db87fc4f6ba4feeb3eca4f6cbb
planner_source: model
tools:
  - market_query: success, evidence_count=1
  - report_search: success, evidence_count=5
  - indicator_calculator: success, evidence_count=1
total_evidence: 7
report_attempts: 2
reporting_status: validation_failed
```

模型生成并修订了报告，但下列两条 Claim 将带千位分隔或组合格式的数字写入正文，当前 Evidence 数字匹配器无法证明所有拆分后的数字片段都由该 Claim 引用的单一 Evidence 支持：

```text
claim[3]:
万联证券报告显示，贵州茅台2025年营业收入172,054.17百万元，
归母净利润82,320.07百万元，每股收益65.74元，
市盈率21.35倍，市净率7.18倍。

claim[7]:
万联证券报告预测贵州茅台2026-2028年营业收入分别为
183,015.67/198,958.30/214,700.63百万元……
归母净利润分别为86,196.94/93,608.83/100,735.09百万元……
```

Validator 原始错误：

```text
claim[3]:NUMERIC_UNSUPPORTED:172.0
claim[3]:NUMERIC_UNSUPPORTED:54.17
claim[3]:NUMERIC_UNSUPPORTED:82.0
claim[3]:NUMERIC_UNSUPPORTED:320.07
claim[7]:NUMERIC_UNSUPPORTED:183.0
claim[7]:NUMERIC_UNSUPPORTED:15.67
claim[7]:NUMERIC_UNSUPPORTED:198.0
claim[7]:NUMERIC_UNSUPPORTED:958.3
claim[7]:NUMERIC_UNSUPPORTED:214.0
claim[7]:NUMERIC_UNSUPPORTED:700.63
claim[7]:NUMERIC_UNSUPPORTED:86.0
claim[7]:NUMERIC_UNSUPPORTED:196.94
claim[7]:NUMERIC_UNSUPPORTED:93.0
claim[7]:NUMERIC_UNSUPPORTED:608.83
claim[7]:NUMERIC_UNSUPPORTED:100.0
claim[7]:NUMERIC_UNSUPPORTED:735.09
```

最终 API 输出：

```yaml
http_status: 200
success: false
error_code: REPORT_VALIDATION_FAILED
validation.passed: false
citation_accuracy: true
numeric_consistency: false
task_success: false
```

### 判断

这不是网络错误，也不应通过增加网络重试解决。当前安全行为是正确的：报告即使已经生成，也只有通过数字与引用校验后才能成为成功终态。

后续可以在 Step 05/08 单独评估：

1. 数字规范化是否应把 `172,054.17` 视为一个整体，而不是逗号两侧的多个数字；
2. 报告 Prompt 是否应要求大数字不使用千位分隔符；
3. 修订节点是否应获得更精确的“原始数字—Evidence ID”映射。

在上述规则完成设计和回归前，不应放宽 Validator。
