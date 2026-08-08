# Step 01 Progress

状态：`COMPLETED`　完成度：100%　审核：Accepted

## 开始前

- [x] 14项架构决定已审核
- [x] 第一阶段20题基线已封存
- [x] Spike范围已确认

## 执行

- [x] 依赖版本验证
- [x] Graph State/节点/错误Schema
- [x] Checkpoint边界
- [x] 最小StateGraph Spike
- [x] 异步Tool和DeepSeek集成
- [x] InMemorySaver中断/继续/重放
- [x] 20题兼容性测试

## 验收

- [x] 风险与差异已记录
- [x] Gate 01通过
- [x] 用户审核

当前记录：

- 2026-07-24：Docker `app`健康，Python 3.11；
- 2026-07-24：迁移前全量单测69/69通过；
- 2026-07-24：固定Step 01候选`langgraph==1.2.9`；
- 2026-07-24：确定旁路`harness` profile，不切换正式`app`运行时。
- 2026-07-24：LangGraph专项5/5通过，Harness依赖无冲突；
- 2026-07-24：DeepSeek Planner + 现有FinancialQueryTool + Iceberg真实链路通过；
- 2026-07-24：最终App镜像构建通过，70项正式测试通过，5项Harness测试按设计隔离；
- 2026-07-24：修复评测参考日期未冻结问题；
- 2026-07-24：20题冻结日期后确定性指标18/18；失败集中于Provider DNS和模型输出稳定性，详见`EVIDENCE.md`；
- 2026-07-24：用户确认继续，接受技术Go结论并关闭Gate 01。
