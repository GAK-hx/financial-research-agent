# Step 05 验证证据

验证日期：2026-07-26

## 1. Docker与数据库

- 当前生产镜像：`financial-research-agent-langgraph-app:latest`；
- Alembic成功升级：`20260726_0002 → 20260726_0003`；
- 新增`policy_decisions`、`run_budgets`、`budget_entries`；
- Model/Tool Call新增Gateway、Policy、Budget和Attempt字段；
- Model Call新增Token、Usage估算标记和费用字段。

## 2. 全量回归

在LangGraph生产依赖镜像和真实PostgreSQL上执行：

```text
python -m unittest discover -s tests -v
Ran 107 tests in 4.595s
OK
```

其中Step 05新增覆盖：

- 官方V4 Pro请求参数、思考模式和Usage字段；
- Tool白名单、只读、非模拟域、股票、日期和行数Policy；
- 未知Model Operation拒绝；
- 并发Reserve不能突破同一Run上限；
- Commit/Release幂等；
- 失败Tool释放逻辑调用、保留Attempt消费；
- Tool异常不泄露模拟密钥；
- Model调用记录Gateway/Policy/Budget/Token/费用；
- 正式LangGraph规划、Tool、报告全部经过Gateway；
- Completion Checker无开放Reservation。

## 3. 真实DeepSeek V4 Pro 1M

真实Run：

```text
run_id               3ca2fa863a84435b81053b538e48c839
model                deepseek-v4-pro
thinking             disabled
http_status          200
success              true
planner_source       model
reporting_status     completed
validation_passed    true
evidence_count       1
revision_used        false
api_total_ms         39551
```

产物：`artifacts/model_runs/deepseek-v4-pro_financial.json`

该Run的预算终态：

| 资源 | Commit |
|---|---:|
| Model Calls | 2 |
| Model Attempts | 2 |
| Tool Calls | 1 |
| Tool Attempts | 1 |
| Evidence | 1 |
| Tokens | 6177 |
| Cost | 22854人民币微元 |
| Open Reservations | 0 |

数据库核对：

```text
model_calls       2 rows / 2 attempts / 6177 tokens / 22854 microunits
tool_calls        1 row  / 1 attempt
policy_decisions  6 rows
```

两个DeepSeek请求均返回HTTP 200，没有触发重试。生产日志只包含URL、状态、耗时和
业务摘要；V4 Pro产物的`sk-`扫描结果为Clean。

## 4. 官方能力核对

DeepSeek官方文档确认：

- OpenAI格式Base URL为`https://api.deepseek.com`；
- 模型ID为`deepseek-v4-pro`；
- 上下文1M、最大输出能力384K；
- 支持JSON Output和Tool Calls；
- 思考模式用`thinking.type`控制，默认开启；
- 思考模式Tool Call后必须回传`reasoning_content`；
- Usage包含Prompt、Completion、Total、Cache Hit和Cache Miss Token。

参考：

- <https://api-docs.deepseek.com/zh-cn/quick_start/pricing/>
- <https://api-docs.deepseek.com/api/create-chat-completion/>
- <https://api-docs.deepseek.com/guides/thinking_mode/>
- <https://api-docs.deepseek.com/guides/json_mode/>

## 5. 结论

`TECHNICAL_GO_READY_FOR_USER_REVIEW`

正式调用已经能追溯到Gateway、Policy、Budget、版本和Usage；Policy反例、预算竞态、
失败释放、脱敏、终态一致性与真实V4 Pro链路均通过。
