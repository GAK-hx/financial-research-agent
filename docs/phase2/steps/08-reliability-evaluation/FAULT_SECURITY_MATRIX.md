# Step 08故障与安全矩阵

## 故障

| 场景 | 注入方式 | 预期 |
|---|---|---|
| Worker Kill/Lease丢失 | 运行中取消Research Task并触发Lease Lost | 当前执行停止，Job可被回收 |
| API重启 | Worker执行期间重建API进程 | Run继续，状态仍在PostgreSQL |
| DB短断 | Heartbeat续租失败 | Worker停止当前执行，不持有过期Lease继续写 |
| 模型连接失败 | 连续NetworkError后恢复 | 按退避策略重试并记录Attempt |
| 模型429 | 连续429后恢复 | 仅对可重试状态重试，最终成功或显式失败 |
| Tool超时/不可用 | Hanging Tool、Milvus不可用 | 返回结构化错误，不生成伪Evidence |
| SSE断开 | 使用游标重新连接 | 不影响Worker，按Last-Event-ID续传 |

## 安全

| 场景 | 控制点 | 预期 |
|---|---|---|
| Prompt Injection要求执行Shell | Model Policy、Tool枚举、白名单 | 无Shell能力，操作被拒绝 |
| 注入未知Tool参数 | FinancialTool参数入口 | `TOOL_ARGUMENT_INVALID` |
| 越权股票/日期/行数 | Policy Engine | 拒绝并记录Policy Decision |
| Skill升权 | Skill有效Tool交集 | `SKILL_TOOL_FORBIDDEN` |
| 写Tool/Simulation | Tool Definition与Policy | 拒绝 |
| 伪造Evidence引用 | Report Validator | `CITATION_UNKNOWN` |
| Memory污染 | Key/Value/敏感信息白名单 | 拒绝写入并审计 |
| 跨Tenant/User Memory读取 | 复合Scope过滤 | 返回空集合 |
| 隐藏推理/凭证进入事件 | 递归脱敏与安全Payload | SSE/Trace中不可见 |

认证和外部身份提供方不属于本地Demo范围；本步骤验证的是应用内部Tenant/User Scope，
不把调用方可自报身份包装成完整的生产认证能力。
