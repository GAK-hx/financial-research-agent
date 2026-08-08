# Step 05 — Model/Tool Gateway、Policy与Budget

## 目标

将所有正式模型和Tool调用收口到统一Gateway，并在调用前后强制执行权限、参数、预算、审计和完成检查。

## 前置条件

- Gate 04已通过；
- Skill能声明Tool、Validator和Budget Profile；
- Tool/Model幂等和错误Schema已稳定。

## 子任务

1. 定义Model Request/Response、Usage、Error、Retry和Provider Capability Schema；
2. 定义Tool Call、Tool Result、Timeout、Row Limit、Domain和Idempotency Schema；
3. 实现Model Gateway：Provider Adapter、超时、结构化输出、Usage、有界重试和脱敏；
4. 实现Tool Gateway：白名单、Pydantic参数校验、只读、超时、行数/时间范围限制；
5. 实现Policy Engine，综合用户/租户、Intent、Skill、Tool、数据域和请求参数；
6. 实现Budget Ledger和`Reserve → Commit/Release`事务；
7. 记录时间、模型次数、Tool次数、并行数、Evidence、修订、Token和费用；
8. 将预算与Policy检查放在每个副作用前，返回后核销；
9. 为未返回Usage的Provider定义估算和未知处理；
10. 实现Completion Checker，统一检查终态、Evidence、Validator、Budget和Artifact；
11. 禁止Graph节点绕过Gateway直接调用Model Adapter或Tool；
12. 增加绕过检测、越权参数、预算竞态、重试风暴和脱敏测试。

## 默认运行预算（待实测后冻结）

| 项目 | 候选值 |
|---|---:|
| 总时长 | 180秒 |
| 模型调用 | 5次 |
| Tool调用 | 12次 |
| 并行Tool | 4 |
| Evidence | 60条 |
| 报告修订 | 1次 |
| Replan | 0 |

Token和费用上限必须依据DeepSeek实际Usage与压测结果确定，不在文档中凭空设值。

## 测试清单

- 未在Skill白名单的Tool被拦截；
- 时间、行数、域和参数越界被拦截；
- 并发Reserve不能突破Run上限；
- 失败调用Release，成功调用Commit；
- 重试次数计入预算并受限；
- 日志和Event不含API Key、完整敏感Prompt和隐藏推理；
- Completion Checker不允许“报告已生成但验证未通过”的成功终态。

## 交付物

- Model/Tool Gateway与Provider Adapter测试；
- Policy Engine、Budget Ledger和业务表；
- Completion Checker；
- 安全、竞态、预算和脱敏测试报告；
- 已更新的`PROGRESS.md`。

## Gate 05

- 正式Graph不存在Gateway绕过路径；
- Policy反例和Budget竞态测试全部通过；
- 每次Model/Tool调用均有预算、版本和审计记录；
- Completion Checker对所有终态给出可解释结果；
- 用户审核默认预算与权限策略。

## 停止条件

若任何正式调用无法追溯到Policy、Budget和版本，不进入Memory实现。
