# Step 04 Progress

状态：`COMPLETED`　完成度：100%　审核：Pending

## 任务清单

- [x] Market输入输出模型
- [x] Market查询限制
- [x] Curated读取
- [x] Indicator输入输出模型
- [x] 六项指标
- [x] 数据日期披露
- [x] 公式版本
- [x] Evidence转换
- [x] 错误处理
- [x] 手算测试

## 指标验收

| 指标 | 测试样本 | 预期 | 实际 | 状态 |
|---|---|---:|---:|---|
| 区间收益 | 收盘100至119 | 0.19 | 0.19 | Passed |
| 波动率 | 收盘100至119 | 0.0075606342 | 0.0075606342 | Passed |
| MA5/MA20 | 收盘100至119 | 117 / 109.5 | 117 / 109.5 | Passed |
| 最大回撤 | 单调递增样本 | 0 | 0 | Passed |
| 相对成交量 | 1000至1019 | 1019 / 1009.5 | 1.0094106 | Passed |
| 区间高低 | high=close+1, low=close-1 | 120 / 99 | 120 / 99 | Passed |

## 工作日志

| 日期 | 内容 | 结果 |
|---|---|---|
| 2026-07-15 | 启动Step 04；实现独立Market/Indicator Tool及Evidence | In progress |
| 2026-07-15 | Docker内运行输入限制、固定公式、Evidence和Registry测试 | 19/19 passed |
| 2026-07-15 | 使用真实600519日线执行Market/Indicator Tool | 126行，两个工具均成功 |
| 2026-07-15 | 真实结果检查 | 实际日期2026-01-05至2026-07-14，Snapshot与公式版本完整 |
