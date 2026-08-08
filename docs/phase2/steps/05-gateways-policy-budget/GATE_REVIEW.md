# Gate 05 审核

状态：`READY_FOR_REVIEW`

## 验收项

- [x] 正式LangGraph规划、报告和Tool执行无Gateway绕过；
- [x] Policy允许与拒绝均有版本化审计；
- [x] Skill外Tool、写操作、模拟域、股票、日期和行数越权被拒绝；
- [x] Model/Tool逻辑调用与Attempt分开计数；
- [x] PostgreSQL事务Reserve防止并发超限；
- [x] 成功Commit，失败Release，不可逆Attempt仍Commit；
- [x] DeepSeek Usage、缓存Token和费用可追溯；
- [x] Completion Checker检查Evidence、报告、Validator和开放Reservation；
- [x] 全量Docker回归107/107；
- [x] 真实DeepSeek V4 Pro 1M正式链路通过；
- [x] API Key、完整Prompt和隐藏推理未写入审计与产物。

## 建议接受的默认值

继续使用现有稳定默认值，并允许Skill进一步收紧：

```text
Run timeout       240s
Model calls       3
Tool calls        8
Parallel tools    4
Evidence          40
Report revisions  1
Replan            0
Model attempts    9
Tool attempts     24
```

网络配置：

```text
Single request timeout  90s
Maximum retries         4
Backoff                 3s → 6s → 12s → 20s
```

Model/Tool Attempt总预算仍是最终边界，不能因提高网络重试而无限请求。

Token和费用暂不设拍脑袋硬上限，只记录真实Usage；严格上限留待有代表性的多类型
Run样本完成请求前预留设计后启用。

## Gate决定

- 用户接受：将Step 05标记`COMPLETED`，进入Step 06 Memory与Context Compression；
- 用户要求调整：只修改默认预算或Policy边界，不回退已通过的Gateway主路径；
- 用户拒绝：记录原因并停止，不进入Memory实现。
