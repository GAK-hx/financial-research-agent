# Step 07 可观测性

## 1. 三类视图

- SSE：面向客户端的阶段、节点、Skill、Tool、Budget和终态事件；
- Trace：面向调试的节点Attempt、模型调用、工具调用和Context Manifest；
- Metrics：面向监控的Job状态数、模型调用、Token、费用和工具调用计数。

所有日志使用结构化JSON并带Run ID、Worker ID、Attempt和事件名。HTTP响应带
`X-Request-ID`；API层可用请求ID定位Run，Worker层用Run ID贯穿Checkpoint、
Gateway和Job事件。

## 2. 隐私边界

SSE和Trace不会返回Prompt、Messages、模型`reasoning_content`、Chain of Thought、
API Key或Authorization。Trace只保留状态、版本、Token、费用、错误码和Context
压缩统计。Token计数属于安全数值遥测，不会被误当作凭证字段脱敏。

真实V4 Pro Run产生34个事件，覆盖：

```text
job_queued / job_claimed / run_created
node_started / node_completed / skill_selected
run_terminal / tool_completed / budget_snapshot / job_terminal
```

从`Last-Event-ID: 31`重连只返回32、33、34，未重复旧事件；隐藏推理扫描结果为0。

## 3. 真实Trace

真实财务Run：

- 13个LangGraph节点均为Attempt 1且Completed；
- 2次模型调用，合计7090 Token；
- 1次`financial_query`，Attempt 1；
- 成本账本为24603 microunits；
- Validator与Completion Checker均通过。
