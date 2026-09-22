# LangGraph 动态团队 Canary 报告

## 范围

使用 DeepSeek V4.1 Flash（`deepseek-flash`）在 Docker 内运行三个公开 Benchmark 各前5题。
推理阶段未读取 Gold 答案、Gold Evidence 或 Gold Program；运行完成后才调用公开评分器。

样本数仅为5题，结果用于验证图结构和发现退化，不可作为最终效果结论或简历指标。

## 同题对照

| Benchmark | 指标 | 单 Agent / 直接回答 | 动态团队 | 当前判断 |
|---|---|---:|---:|---|
| FinanceBench | 语义正确率（同模型裁判，仅开发诊断） | 80% | 80% | 持平；不能宣称多 Agent 更优 |
| FinanceBench | 单位感知数值诊断准确率 | 60% | 80% | 改善；该指标不适用于全部开放式问题 |
| FinanceBench | Evidence Recall / Precision | 93.3% / 60.0% | 93.3% / 78.3% | 覆盖检查后召回持平、引用更精简 |
| FinQA | Execution / Program | 40% / 20% | 40% / 40% | 程序格式改善，计算正确率未改善 |
| FinQA + 公开训练程序 Skill | Execution / Program | 40% / 20% | 80% / 80% | 5题开发信号为正，需扩大样本确认 |
| TAT-QA | EM / F1 / Scale | 0% / 25.8% / 100% | 40% / 58.2% / 80% | 初步正增量，需扩大样本确认 |

FinanceBench 官方公开集没有可直接复用的自动语义评分器，因此这里额外使用参考答案感知的
DeepSeek V4.1 Flash 裁判。候选模型和裁判模型相同，结果可能存在同源偏差，只用于开发回归；
正式结论仍需采用更可靠的独立裁判或官方人工评审口径。

## 已实现的运行闭环

1. Supervisor 只读取问题、上下文形态和有限预览，选择最小研究团队；
2. Harness 从代码模板注入 Benchmark 级工具白名单、调用/Token/超时预算；
3. LangGraph 使用动态 fan-out 并行运行已批准的研究子 Agent；
4. Evaluator 在 Gold 不可见的条件下检查单位、期间、证据、冲突和程序执行；
5. 只允许对一个既有 Agent 做一次定向修复，禁止创建孙 Agent；
6. 汇总后生成 RiskAssessmentArtifact 和 AgentScorecard；
7. 每题即时落盘，支持断点续跑及仅重试失败题。

## 真实工具执行

- FinanceBench：检索计划调用页级FTS5索引，最多执行3条首轮查询和1条缺失概念补查；
- FinQA：计算 Agent 生成函数式程序，本地白名单解释器执行，不使用 `eval`；
- FinQA 常量按公开规范归一为 `const_1`、`const_5`、`const_100` 等；
- FinQA 程序 Skill 只从公开 `train` split 建立SQLite FTS5索引，共6,251条；检索结果仅用于学习
  操作符、常量和程序结构，不能作为当前问题的答案证据；
- 模型不能自行增加工具或预算，子 Agent 只能读取 Harness 提供的受控上下文。

## 发现与修正

### 已修正

- 结构化输出不再因多给候选查询而整题失败；执行层截取预算内查询；
- JSON 结构错误先本地恢复，不再把同一请求机械重试四次；
- FinanceBench Evaluator 不重复读取全部12页，只读取子 Agent 提取的证据摘录；
- 单题总 Token 从约35.5k降至13.8k，答案与引用指标保持正确；
- TAT-QA 描述题保留完整来源 span，单题 F1 从33提高到94；
- FinQA 已验证程序由 Harness 保留，汇总节点不得改写成中缀表达式。
- FinQA 公开训练程序 Skill 已接入；同一5题上，官方 Execution / Program 从无 Skill 的
  40% / 40% 提升到80% / 80%。其中 Citi 和 DVN 样例由错误/缺失的两步计算修正为官方程序形式。

### 尚未解决

- FinanceBench 覆盖检查已改善小样本检索，但仍需在更大官方复杂子集验证；
- FinanceBench 开放式答案的百分比与百分点需要单位感知评分，不能只做字符串数字比较；
- FinQA Skill 当前使用词法FTS5相似度；在20题官方复杂子集上，多Agent Execution / Program
  达到50%～55% / 35%～40%，但仍需正式Gate重复验证；
- B/C/D 小样本消融已完成；A规则路径需在公开风险标签任务上单独评估；
- 定向修复路径已在FinQA 20题复杂子集中自然触发4次；正式Gate需统计修复前后正确率；
- 四类金融风险专用子 Agent 尚未接入当前公开 QA 图。

## 下一步

1. 冻结三个官方 Benchmark 的复杂子集，不继续针对当前5题调参；
2. 先扩大 B/D 对照，判断复杂任务上动态团队是否有稳定质量增量；
3. 仅在 B/D 结果支持时扩大固定团队 C 和三次重复稳定性测试；
4. 为真实财务风险任务接入四类风险子 Agent，并寻找公开风险标签数据评估规则路径A。
