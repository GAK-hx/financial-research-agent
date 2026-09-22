# 评测方法

## 原则

Agent效果只使用公开标注Benchmark。自有公司数据用于流程、数据质量、性能、缓存和部署验证，不报告风险
Precision、Recall或F1。合成数据只验证Spark/Iceberg工程行为。

## 数据集

- FinanceBench：财报问答与Evidence；
- FinQA：数值推理与官方程序执行；
- TAT-QA：表格、文本和混合算术问答；
- V4FinBench：公开财务风险预测与公司分组五折。

## 比较对象

- 确定性规则或统计模型；
- 单Agent；
- 固定多Agent；
- Supervisor动态团队与Evaluator。

同一比较使用相同题目、上下文、Tool结果和评分器。推理输入不包含Gold答案、Gold Evidence或Gold Program。
失败按0计入，不通过删题、无限重试或自建标签改善分数。

## 指标

- FinanceBench：数值准确率、Evidence Recall和Precision；
- FinQA：Execution Accuracy、Program Accuracy；
- TAT-QA：EM、F1、Scale Accuracy；
- V4FinBench：PR-AUC、ROC-AUC、F1、Recall@Precision和校准；
- 工程：PIT泄漏、主键重复、缓存复用、扫描量、任务丢失、重复终态和跨租户读取。

小规模复杂子集结果必须明确样本数，不外推为完整数据集成绩。
