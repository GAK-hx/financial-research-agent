# Step 02：自适应多 Agent 与证据复核

## 目标

在 Step 01 冻结数据和评分器上，实现“确定性候选筛查—Supervisor 动态组队—子 Agent 取证与分析—
Evaluator 反证—一次定向修复”的受控闭环，并通过 A/B/C/D 消融证明质量和成本变化。

## 工作包

### 1. 类型化产物

- `RiskCandidate`：公式、阈值、当前值、历史基准和数据版本；
- `SubAgentSpec`：目标、风险域、公司、期间、Tool、Evidence、Token/调用/时间预算；
- `RiskHypothesis`：信号、支持/反向证据、假设、严重度、置信度和缺失；
- `SubAgentEvaluation`：覆盖、证据、冲突、冗余和建议动作；
- `AgentScorecard`：按任务/风险域保存正确率、贡献、成本和校准；
- `RiskAssessmentArtifact`：最终公共分析产物，不包含用户私有文本。

### 2. 动态编排

- 确定性筛查先缩小候选风险；
- Supervisor 只能从注册模板创建子 Agent；
- Harness 校验 Tool、实体、期间、预算和依赖；
- 最多4个研究子Agent、1个Evaluator、1次定向修复；
- 子 Agent 不允许创建孙 Agent；
- 简单数值/检索问题走单路径，复杂风险才动态 fan-out。

### 3. 子 Agent

- 偿债风险：现金短债、债务期限、融资和担保；
- 盈利质量：利润/现金流、应收、存货和非经常性项目；
- 资产质量：减值、商誉、资产处置和资本开支；
- 披露取证：财报、公告、审计和修订证据；
- 反证复核：季节性、行业共性、口径变化和替代解释。

### 4. 评估与修复

- 主体、日期、数值、单位、Evidence 和权限由代码评分；
- Evaluator 只评价开放式归因、遗漏、冲突和证据充分性；
- 输出只允许 `ACCEPT`、`ACCEPT_WITH_LIMITATIONS`、`TARGETED_REPAIR`、`REJECT` 或
  `INSUFFICIENT_DATA`；
- 修复只补指定缺口，不能重写全部分析或扩大任务范围；
- Scorecard 在线只读，版本更新由离线 Gate 发布。

### 5. 消融

- A：规则；B：单 Agent；C：固定多 Agent；D：动态 Supervisor + Evaluator；
- 使用FinanceBench、FinQA、TAT-QA相同官方split、模型、Tool和评分器；
- 分别报告质量、Token、Tool调用、延迟、冗余和修复收益；
- 若 D 没有增量，保留实验结论，不强行上线复杂方案。

## 最小可行性检查

- 1个简单问题只启动1条路径；
- 1个现金流异常触发正确子 Agent；
- 1个不充分结论被 Evaluator 降级；
- 1个越权 Tool 计划被 Harness 拒绝；
- 1次修复后正确终止。

## Step 02 最终 Gate

- 所有 Agent P0 为0错误；
- 三个公开Benchmark均输出官方或官方口径指标；
- Agent输入不存在Gold答案、证据或程序泄漏；
- Team Selection只报告运行行为、调用量和边际贡献，不使用自建Gold集合；
- 确定性规范化优先于模型修复；历史程序格式失败不得继续造成误拒，模型修复的实际触发与结果如实报告；
- D相对单Agent在公开Benchmark复杂子集上的效果—成本变化有完整统计和失败分析；
- D相对B/C使用冻结同题样本报告逐题结果、质量—成本变化和失败分析；20题开发集不强制包装为统计置信结论；
- Flash 网络失败原始输出进入 Markdown/JSON 失败报告。

## 达成效果

- Agent 岗位：可以讲动态组队、受控自治、证据裁决和消融；
- 数据分析岗位：可以量化 Agent 相对规则/统计基线的增量；
- 数据开发岗位：公共 RiskArtifact 可版本化、缓存和复用。
