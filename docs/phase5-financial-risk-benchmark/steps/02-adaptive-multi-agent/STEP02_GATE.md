# Step 02最终Gate

- 总状态：`SUCCESS`；
- 自动检查：7/7；
- 结论：动态多Agent按任务路由，不作为全局默认；
- 分数要求：只验证稳定、明显的相对改善，不继续为简历目标调参。

| 检查项 | 结果 | 说明 |
|---|---|---|
| V4FinBench A1/A2 | PASS | 官方公司分组五折；A2固定参数；A1/A2各996,500条预测完整覆盖 |
| Supervisor与Harness最小闭环 | PASS | 三类任务选择成功，选择阶段Gold不可见 |
| B/C/D冻结复杂题推理 | PASS | 8组所需配置均20/20成功；FinanceBench C因D未超过B而停止补跑 |
| 官方或确定性评分 | PASS | 8组评分均覆盖20题且无推理失败 |
| 推理Gold隔离与失败归档 | PASS | Gold标志均为false；本轮8组运行失败数为0 |
| 按任务路由证据 | PASS | FinanceBench走B；FinQA复杂题走C；TAT-QA指定复杂类型允许D |
| FinQA程序格式回归 | PASS | 历史4题格式失败降为0/4，Evaluator接受4/4；官方Execution 3/4、Program 2/4 |

## 默认路由

- FinanceBench与简单题：单Agent；
- FinQA复杂题：固定表格推理+量化分析团队；
- TAT-QA复杂算术或table-text：动态Supervisor团队；
- 无法确认复杂度或证据不足：回退单Agent或明确拒答。
