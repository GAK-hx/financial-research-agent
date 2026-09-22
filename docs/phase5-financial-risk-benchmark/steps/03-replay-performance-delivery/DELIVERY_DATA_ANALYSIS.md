# 数据分析岗位交付说明

## 分析问题

项目将“风险报告好不好看”改写为可测量问题：在严格Point-in-Time边界下，规则、统计模型和Agent分别能
发现什么；多Agent在什么题型有增量；提高召回是否牺牲精度、校准和成本。

## 指标体系

- 类别极不平衡的V4FinBench以PR-AUC、Recall@Precision和校准为主，ROC-AUC只作补充；
- FinanceBench报告答案正确性和Evidence Recall；
- FinQA报告Execution与Program Accuracy；
- TAT-QA报告EM、F1和Scale Accuracy；
- 自有场景只报告PIT泄漏、成功率、缓存复用、延迟和恢复，不报告虚构的Precision/Recall。

## 主要结论

- V4FinBench树模型相对线性基线的排序与低精度约束召回明显提升，但ECE变差，说明“更会排序”不等于
  “概率更可信”；
- 复杂题分组后，多Agent收益高度依赖题型。TAT-QA的跨表格/文本计算收益明显，FinanceBench并无稳定增益；
- 规则候选只作为Agent复核入口，不是风险标签；缺失数据必须保持`INSUFFICIENT_DATA`，不能填0；
- 公开测试失败按0进入指标，不通过重试或删题美化结果。

## 可继续分析

- 按风险类别、行业、公司规模和缺失模式分解V4FinBench误差；
- 对树模型做独立时间切分校准，比较Platt、Isotonic与不校准结果；
- 对多Agent路由构建质量—Token—延迟Pareto前沿；
- 将历史回放中的状态迁移作为监测稳定性分析，不把它伪装成风险正确率。
