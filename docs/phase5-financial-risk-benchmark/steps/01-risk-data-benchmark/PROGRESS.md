# Step 01 进度

- 状态：`COMPLETE`；
- 当前里程碑：数据底座、公开Benchmark适配和评分入口全部通过；
- 最近更新：2026-09-16。

## 已完成的数据底座

- 100/100家公司三表，156,352条标准化事实；
- 29,107条PIT特征和8,956个程序化风险候选；
- 原始响应程序化对账156,352/156,352；
- 关键值完整率99.18%；
- 主键重复、不可用值污染和PIT输出泄漏均为0；
- 财务事实、特征和候选重复运行复用Iceberg Snapshot；
- 主Docker镜像不挂载源码的12/12基础检查通过。

上述结果只证明自有数据和运行链路，不作为Agent效果Benchmark。

## 当前任务

- [x] FinanceBench官方公开150例适配；
- [x] FinQA官方train/dev/test适配，共8,281例；
- [x] TAT-QA官方train/dev/test gold适配，共16,546例；
- [x] Agent输入和Gold答案/证据/程序隔离；
- [x] FinQA/TAT-QA官方评分脚本与FinanceBench Gold Schema最小验证；
- [x] 新Step 01统一Gate，8/8通过。

## 完成结果

- 公开Benchmark合计24,977例，保留官方ID和官方split；
- Gold目录仅评分器可读，Agent输入不包含答案、证据或程序字段；
- 5例Oracle只用于验证评分入口：FinanceBench、FinQA、TAT-QA均通过，不作为Agent成绩；
- 最终报告：`artifacts/phase5_step01/final_gate_v1/report.md`。

## 已废止的设计

- 不自建风险Benchmark；
- 不要求用户人工标注或双人标注；
- 不计算自有数据的风险Precision/Recall或Cohen's kappa；
- 原300例结构不进入效果Benchmark，最多保留为内部流程/性能样例；
- PDF机器检查可保留为采集诊断，但人工PDF核对不阻塞Step 01。
