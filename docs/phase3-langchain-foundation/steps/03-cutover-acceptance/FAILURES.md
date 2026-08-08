# Step 03失败与修复记录

本文件保留集中验收中出现的真实失败。失败产物不会因后续通过而删除。

## 1. 非Docker环境缺少`/lake`

现象：

```text
/lake/iceberg_catalog.db unavailable
```

原因：本地进程没有Docker的`lake_data:/lake`卷，不能代表正式部署失败。

处理：正式构造与端到端测试全部在Docker中执行。Docker健康检查中Iceberg为
`ready`。未给本地路径添加绕过逻辑。

## 2. 首次Pro调用发生DNS错误

现象：

```text
APIConnectionError
nodename nor servname provided, or not known
```

重试间隔为3、6、12秒。原因是受限执行环境无法解析外部域名，不是DeepSeek返回的
业务错误。允许外部网络后，同一LangChain结构化调用成功，593 Token、4.125秒。

## 3. 真实异步任务报告结构化解析失败

Run：`f348832183594ebd895f71c81e0c76e3`

安全保留的节点输出：

```json
{
  "node_name": "generate_report",
  "status": "failed",
  "error_code": "ProviderUnavailable:structured output validation failed: OutputParserException"
}
```

完成门禁输出：

```json
{
  "passed": false,
  "errors": [
    "COMPLETION_REPORT_NOT_COMPLETED",
    "COMPLETION_CONTEXT_MANIFEST_MISSING:generate_report"
  ]
}
```

模型HTTP请求实际返回200，行情与指标Tool均成功，问题位于LangChain JSON Mode的
Pydantic解析阶段。根因是Prompt没有像旧Provider一样显式携带输出Schema，而且
`include_raw=True`的`parsing_error`没有进入重试。

修复后Run：`56fa6504f95d4f998655c8b0f55fe4cb`

```json
{
  "status": "completed",
  "success": true,
  "tool_calls": 2,
  "evidence_count": 2,
  "report_claims": 5,
  "validation_passed": true,
  "completion_passed": true
}
```

出于安全边界，系统不持久化完整Prompt、API Key或模型隐藏推理；保留的是结构化
响应、解析错误类型、节点轨迹、受控Evidence和最终报告。这比保存所谓“原始思维链”
更符合生产审计要求。

## 4. 本机代理截获Flash评测请求

现象：

```text
HTTP_EXPECTED:200:ACTUAL:0
JSONDecodeError: Expecting value: line 1 column 1
```

Flash容器访问日志未收到请求，说明请求在到达API前被本机代理截获。该运行在第一题
后停止，不计入模型质量。

处理：将评测器放入同一Docker容器，通过`127.0.0.1:8000`直连API。随后20题全部
收到合法HTTP响应。

## 5. `eval-05`指标窗口标签误判

首次安全输出：

```json
{
  "case_id": "eval-05",
  "task_success": false,
  "validation_errors": [
    "claim[4]:NUMERIC_UNSUPPORTED:20.0"
  ],
  "claim": "相对20日平均成交量（RVOL）为0.97"
}
```

Evidence实际包含：

```json
{
  "relative_volume_20d": 0.9700961136648558,
  "ma5": 1202.468,
  "ma20": 1197.288
}
```

`20`是技术指标的窗口量纲，不是价格、收益率或成交量事实值。校验器原已排除
“20日均线、20日均量、20日相对成交量”，但漏掉“20日平均成交量”变体。

处理：

- 将“日平均成交量”加入窗口标签集合；
- 扩充Validator回归用例；
- 不放宽价格、比例、金额和日期校验；
- 定向复测`eval-05`：全部指标100%。

