# Step 03集中验收证据

日期：2026-07-28

## 1. 默认正式路径

- `Settings.agent_framework`默认值：`langchain`；
- `Settings.orchestration_runtime`默认值：`langgraph`；
- `.env.example`显式声明同一默认组合；
- Docker Compose的`app`、`job-api`和`job-worker`均使用该组合；
- 重复的`langgraph-app`服务已删除；
- `native/legacy`保留为显式诊断回退，不是默认入口。

正式容器有效配置核对：

```json
{
  "agent_framework": "langchain",
  "orchestration_runtime": "langgraph",
  "model": "deepseek-v4-pro",
  "checkpoint_backend": "postgres",
  "api_key_configured": true
}
```

只检查Key是否存在，没有输出Key内容。

## 2. LangChain结构化输出修复

真实Pro任务首次在`generate_report`出现：

```text
ProviderUnavailable:structured output validation failed: OutputParserException
```

修复内容：

1. 规划和报告Prompt显式携带Pydantic JSON Schema；
2. 报告Prompt增加最小合法结构示例；
3. `include_raw=True`返回的解析错误不再被误记为成功Attempt；
4. 解析错误按模型重试策略重试，并继续经过Model Gateway与Budget；
5. 新增“第一次解析失败、第二次成功”的单元测试。

修复后真实Pro异步任务：

- 状态：`completed`；
- `planner_source=model`；
- Skill：`market_trend_analysis@1.0.0`；
- `market_query`与`indicator_calculator`均成功；
- Evidence：2；
- Report Claim：5；
- Report Validator：通过；
- Completion Checker：通过；
- Model调用：2；
- Tool调用：2；
- 开放Budget Reservation：0；
- SSE终态：`job_terminal/completed/success=true`。

## 3. 自动化测试

### 本地环境

```text
122 passed, 19 skipped, 15 warnings in 4.97s
```

19项跳过均为需要真实PostgreSQL的可选测试。告警来自FastAPI旧`on_event`生命周期
接口和Starlette TestClient兼容提示，不阻断当前功能。

### 最终Docker镜像

启用`RUN_POSTGRES_TESTS=1`执行全部测试：

```text
Ran 141 tests in 9.641s
OK
```

覆盖Checkpoint、跨图实例恢复、幂等Tool结果、Policy、事务Budget、Memory隔离、
Context压缩、Skill、Job Lease、Cancel/Resume和SSE。

### 修改文件静态检查

```text
All checks passed!
```

项目全库Ruff仍有102项历史风格问题，主要是旧迁移、UTC别名和导入排序，不属于
本次框架调整；本次修改涉及的Python文件在排除既有规则后通过检查。

## 4. Docker与接口

正式服务：

```text
app         healthy  8000
job-api     healthy  8002
job-worker  running
postgres    healthy
milvus      running
etcd        running
```

`app`与`job-api`的`/health`均返回`ready`，Iceberg、Milvus、PostgreSQL和模型配置
全部为`ready`。

SSE验证观察到完整节点序列：

```text
load_memory → interpret → remember_query → select_skill
→ initialize_governance → plan → validate_plan
→ execute_tools → build_evidence → generate_report
→ validate_report → completion_check → finalize
```

事件只包含节点、状态、受控错误码、Tool摘要和Budget Snapshot，没有Prompt、
API Key、模型隐藏推理或完整原始上下文。

## 5. 真实模型

### Pro少量可行性

LangChain直接结构化规划：

```json
{
  "framework": "LangChainModelProvider",
  "model": "deepseek-v4-pro",
  "task_names": ["financial_query", "report_search"],
  "request_id_present": true,
  "total_tokens": 593,
  "latency_ms": 4125,
  "message_type": "ai"
}
```

### Flash集中回归

- 首次20题：19/20，任务成功率95%；
- Intent、Skill、Tool、参数、Evidence覆盖、引用和Budget闭合：100%；
- P50：8.436秒；
- P95：14.143秒；
- 唯一失败题：`eval-05`，原因是“20日平均成交量”中的窗口标签`20`被误判为
  待验证事实数值；
- 增加与“20日均线/均量”一致的窗口标签规则后，`eval-05`定向复测全部指标100%。

原始机器产物：

- `artifacts/phase2_step08/regression/step03-langchain-flash/`
- `artifacts/phase2_step08/regression/step03-langchain-flash-repair/`

## 6. 来源链

真实任务保持以下链路：

```text
PyIceberg snapshot
→ FinancialTool ToolResult
→ LangChain ToolMessage artifact
→ current-run Evidence
→ ResearchReport Claim.evidence_ids
→ ReportValidator
→ Completion Checker
```

真实Evidence保留表名、Snapshot ID、实际数据日期、计算公式版本和Source Locator。
Context压缩后的Evidence保护检查通过，模型不能以压缩摘要替换可追溯事实。

## 7. 验收结论

- 默认LangChain/LangGraph路径：通过；
- Model/Tool Gateway与金融治理增强：通过；
- PostgreSQL Checkpoint与业务持久化：通过；
- API/Worker/SSE与Docker：通过；
- 核心成功率门槛`>=95%`：通过；
- Evidence覆盖、引用与Budget闭合：100%；
- 阻断性缺陷：0。
