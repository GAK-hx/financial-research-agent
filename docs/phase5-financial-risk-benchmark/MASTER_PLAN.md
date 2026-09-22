# 第五阶段总计划

## 1. 目标

在现有 LangChain、LangGraph、Harness、Iceberg、Spark、检索、Evidence、PostgreSQL Job、Redis 和
Spring Gateway 基础上，完成一个可用数据和 Benchmark 证明的企业财务风险系统。

核心问题不是“Agent 能否写一篇风险报告”，而是：

1. 能否在严格的 Point-in-Time 边界下发现财务风险候选；
2. 能否用财报、公告和结构化数据支持或推翻候选风险；
3. Supervisor 能否只创建必要的子 Agent，并控制成本和重复调用；
4. 相比规则、统计模型、单 Agent 和固定多 Agent，动态编排是否有稳定增量；
5. 多用户查询重叠公司时，能否安全复用公共分析产物。

## 2. 任务定义

### 2.1 分析单元

`issuer_id + as_of_report_period + data_snapshot_id`

输入包括公司、分析截止日、问题和可选关注维度。输出统一为 `RiskAssessmentArtifact`，至少包含：

- 风险状态：`CLEAR`、`WATCH`、`ESCALATE` 或 `INSUFFICIENT_DATA`；
- 风险类型、严重度和置信度；
- 观测信号、支持证据和反向证据；
- 计算口径、数据截止日和快照；
- 缺失数据、替代解释和人工复核建议。

### 2.2 风险范围

只覆盖四类相互紧密的财务风险：

1. 偿债与流动性；
2. 盈利质量与现金流；
3. 资产质量与减值；
4. 财务披露与审计异常。

行情、因子、普通新闻和研报只能作为辅助证据，不扩展为独立选股、预测或交易任务。

## 3. 三个完整 Step

| Step | 目标 | 主要产物 | 进入条件 |
|---|---|---|---|
| 01 | 建立Point-in-Time数据底座并接入公开Benchmark | 财务事实/特征表、FinanceBench/FinQA/TAT-QA适配器和评分入口 | 现有项目可读取；无需在线多Agent |
| 02 | 实现 Supervisor 动态组队、风险假设、证据取证、反证和 Evaluator | 动态 LangGraph、`RiskHypothesis`、`AgentScorecard`、消融报告 | Step 01 Gate 通过 |
| 03 | 完成历史回放、多用户复用、Docker/K8s交付、性能 Gate 和三类岗位交付 | 回放报告、并发报告、容器与集群运行手册、数据分析报告、最终演示 | Step 02 Gate 通过 |

一次只实施一个完整 Step。小阶段只做导入、Schema、单案例等最小可行性检查；每个 Step 最后集中执行
大规模测试和修正。

## 4. 暂定总体效果

### 4.1 必须达到的硬门槛

- 未来数据泄漏、跨租户读取、未授权 Tool、重复副作用和终态丢失均为 0；
- 报告期、主体和数据快照绑定准确率 100%；
- 重大结论引用精确率 100%，无 Evidence 的重大风险结论为 0；
- 公开Benchmark的Agent输入不得包含Gold答案、证据或推理程序。

### 4.2 待 Step 01 基线确认的研究目标

- FinanceBench、FinQA、TAT-QA均报告官方或官方口径指标；
- 绝对准确率目标在公开单Agent基线完成后确定，不预写高分；
- 动态多 Agent 在公开Benchmark复杂子集上相对单Agent取得稳定增益，或在质量相当时减少至少25%调用；
- 动态 Supervisor 相比固定多 Agent 的子 Agent/模型调用减少至少 25%，质量下降不超过 1 个百分点；
- 热缓存 p95 比冷查询降低至少 30%，重叠查询外部调用减少至少 50%。

这些是暂定目标，不写入 README 或简历为既成结果。Step 01 得到真实基线后，可以在不降低 P0 门槛的前提下修订
统计目标，并记录修订原因。

## 5. 对比配置

| 配置 | 内容 | 回答的问题 |
|---|---|---|
| A | 确定性风险规则 | 不使用 LLM 时能做到什么 |
| B | 规则/统计候选 + 单 Agent | 单 Agent 的增量是什么 |
| C | 固定多 Agent | 多方法并行本身是否有效 |
| D | 动态 Supervisor + Evaluator + Scorecard | 自主管理能否提高质量/成本比 |

所有配置必须使用相同数据快照、问题、Tool 结果口径和评分器。不得让某个配置看到更多未来信息。

## 6. 测试与网络策略

- 离线确定性测试优先，不需要模型的问题不得调用模型；
- 在线开发与多轮验证全部默认使用 DeepSeek V4.1 Flash（`deepseek-flash`）；
- 随机性明显的 Holdout 案例重复 3 次，确定性案例运行 1 次；
- 网络错误最多重试 6 次，遵循 `Retry-After`，否则使用带抖动的 5/10/20/40/60/90 秒退避；
- 达到预算或连续无新增证据后停止，不通过无限重试掩盖错误；
- 失败案例保存输入、配置、Trace、原始输出和判分原因到 JSON/Markdown；
- 成功案例只保存结构化 Trace 和指标，避免评测产物无限增长。

## 7. 暂定数据与资源预算

- 正确性小池：20家公司，用于自动数据对账；
- 业务演示池：100家公司、至少8个可用报告期，只用于流程和性能测试；
- 效果Benchmark：FinanceBench、FinQA、TAT-QA官方公开数据和官方split；
- 性能数据：可单独生成 500 万～1000 万行明确标记的合成数据，只验证 Spark/Iceberg，不参与业务结论；
- 新增原始数据、索引和评测产物默认总上限 10 GiB，超过前必须重新评估和清理策略；
- Step 01 在线模型预算不超过 30 次调用；Step 02 开发预算暂定 800 次；Step 03 总 Gate 暂定 2500 次，
  实际调用前输出预计样本数和 Token 预算；
- Step 01 数据采集和离线评测优先在专用 Docker 容器运行，不加载模型密钥或启动无关中间件；
- Step 03 增加 Kubernetes 部署管理验证，但不在本地 Demo 中伪造云集群结果；
- K8s 本地测试集群为1个control-plane加2个worker逻辑节点，三者共享本机资源；生产容量需另行评估，
  持久数据应使用外部对象存储/数据库，不把单机SQLite Catalog或容器本地盘当作生产共享存储；
- 不在本阶段引入 Ray、Kafka、Flink 或新的大模型部署。

## 8. 岗位交付

- Agent：动态 Supervisor、Tool/Harness、Evidence、Evaluator、Scorecard、消融实验；
- 数据分析：风险指标体系、时间切分、统计基线、PR 曲线、校准、误报归因和提前量；
- 数据开发：ODS/DWD/DWS/ADS、Spark/Iceberg 增量、回填、快照、质量、血缘和性能报告。
- 平台交付：多阶段镜像、非 root/最小权限容器、K8s Deployment/Job、HPA、PDB、NetworkPolicy、
  Secret/ConfigMap、探针、滚动发布与回滚演练。
