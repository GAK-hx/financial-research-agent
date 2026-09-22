# Agent岗位交付说明

## 系统做什么

系统面向企业财务风险监测与证据复核。确定性数据层先按公司、报告期和分析截止日生成偿债、盈利质量、
资产质量、披露审计四类候选；Supervisor再根据任务复杂度选择必要的子Agent，Evaluator负责证据、数值、
口径和冲突复核，最多允许一次定向修复。

## 关键实现

- LangChain统一模型与Tool接口，LangGraph保存运行状态并执行动态fan-out；
- Harness控制Tool白名单、参数、预算、超时、重试和取消，模型不能直接访问数据库；
- Skill Registry冻结检索、表格推理、量化计算、反证和报告策略版本；
- 上下文构建按身份、时间和预算筛选，压缩只移除低价值内容，不修改原始Evidence；
- `RiskAssessmentArtifact`绑定主体、报告期、截止日、数据快照、证据、限制和AgentScorecard；
- 公共分析与用户展示分离，重叠查询对分析过程使用single-flight。

## 效果证据

效果只引用公开Benchmark：FinanceBench、FinQA、TAT-QA和V4FinBench。动态团队不是全局默认：

- FinanceBench复杂题保留单Agent，因为动态团队未改善数值准确与证据召回；
- FinQA复杂题默认固定团队，动态团队只增加5个百分点且成本更高；
- TAT-QA复杂算术/table-text任务使用动态团队，EM从30%提升至60%，F1从37.9提升至63.35；
- V4FinBench固定参数LightGBM相对逻辑回归的PR-AUC提升66.7%，但校准变差被如实保留。

这些结果说明路由依据是“同题质量/成本证据”，而不是把多Agent当作卖点强制使用。

## 面试中应主动说明的限制

- 自有公司数据不具备风险Gold，只用于业务演示和系统性能；
- FinanceBench自由文本Judge与候选模型同源时可能有偏差，因此保留数值和Evidence确定性指标；
- 多用户缓存Gate使用冻结响应，不能当作生产模型延迟；
- Kind三逻辑节点已完成本地运行与恢复演练，但共享同一物理主机，不能表述为生产多机高可用；
- 本地未安装metrics-server，HPA只完成配置验证，不能表述为已完成动态扩缩容压测。
