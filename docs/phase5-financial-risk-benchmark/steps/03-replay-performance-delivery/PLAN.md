# Step 03：历史回放、并发性能与岗位交付

## 目标

验证动态Agent在真实公司数据上的运行稳定性、多用户复用和部署效果，并形成Agent、数据分析、
数据开发三种岗位都能独立讲清楚的证据和演示。

## 工作包

### 1. 业务场景回放

- 从冻结的历史 `as_of_date` 重放输入；
- 记录端到端成功率、证据完整性、Tool错误、延迟、Token和成本；
- 不在自有公司数据上报告风险Precision、Recall、F1或校准指标；
- Agent效果结论引用Step 02公开Benchmark，自有回放只证明业务流程可运行；
- 计算移除某个子Agent后的延迟、成本和公开Benchmark边际贡献。

### 2. 缓存与多用户

- `RetrievalSnapshot`、`RiskAssessmentArtifact` 跨用户安全复用；
- 用户问题、偏好和最终 `UserReport` 保持 tenant/user 隔离；
- 同公司、同报告期、同版本使用 single-flight 合并；
- 数据更新时只刷新变化的特征、Evidence 和受影响风险假设；
- Redis 只保存可重建热状态，PostgreSQL 保存最终事实。

### 3. 数据开发性能

- 测试全量与增量 Spark 计算；
- 测试 Iceberg 分区裁剪、快照、回填和小文件整理；
- 可用500万～1000万行合成数据验证吞吐，并与真实正确性样本完全隔离；
- 记录扫描行数/字节、运行时间、失败恢复和重复写入；
- 补齐核心表血缘、质量规则和运行手册。

### 4. 多用户 Gate

- 1、5、20、50虚拟用户逐级执行；
- 用户查询20家公司，每人4～5家，设置约60%公司重叠；
- 分冷缓存、热缓存和增量更新三轮；
- 记录准入、排队、Tool、模型、校验和输出延迟；
- 注入 Worker 退出、Redis 不可用和 SSE 重连；
- 检查公平性、身份隔离、任务恢复和 Provider 限流。

### 5. 岗位交付

- Agent：架构、子 Agent Trace、Scorecard、消融与失败案例；
- 数据分析：指标字典、EDA、公开Benchmark分项结果和失败归因；
- 数据开发：分层模型、Spark/Iceberg增量、回填、血缘、质量和性能；
- Demo：选择2～3个历史案例展示候选风险如何被支持或推翻，不展示投资建议。

### 6. Docker 与 Kubernetes 部署管理

- 将 API、异步 Worker、数据采集、离线评测和数据库迁移拆成独立镜像/命令，不在一个容器内启动全部组件；
- 镜像使用固定依赖版本、多阶段构建、非 root 用户、只读根文件系统、健康检查和 SBOM/漏洞扫描；
- K8s 中API/Worker使用Deployment，迁移使用Job，湖命名空间幂等初始化使用CronJob；定时增量采集需在采集命令完成后再独立接入；
- 使用 ConfigMap 管理非敏感配置、Secret 管理 API Key/数据库凭据，禁止密钥进入镜像、Manifest 和日志；
- 配置 requests/limits、HPA、PodDisruptionBudget、readiness/liveness/startup probes 和优雅终止；
- 通过 NetworkPolicy 限制 API、Worker、数据库和外部 Provider 的访问边界，并使用 ServiceAccount 最小权限；
- PostgreSQL、Redis、Milvus/Elasticsearch 与 Iceberg Catalog 优先使用外部托管或独立 Stateful 服务；
  多副本环境禁止共享单机 SQLite Catalog；
- 验证滚动更新、配置回滚、Worker 驱逐、节点中断、Job 重试和重复终态防护；
- 本地用 kind/k3d 做 Manifest 与故障演练，正式云集群容量和成本单独记录，不把本地结果冒充生产结果。

## 最小可行性检查

- 1个历史案例能够按旧快照重放；
- 2个用户能够共享公共 Artifact 且看不到对方报告；
- 1次增量更新只重算受影响风险；
- 1个 Worker 退出后任务可恢复。
- 1个 kind/k3d 测试集群可完成 API/Worker 滚动更新，Job 重试不产生重复终态。

## Step 03 最终 Gate

- FinanceBench、FinQA、TAT-QA最终公开测试结果已由Step 02产出；
- P0为0错误，业务场景端到端成功率 >= 95%；
- 报告公开Benchmark分项指标及自有系统性能分布，不混合两类结果；
- 热缓存p95和重叠外部调用相对冷基线稳定、明显下降，并报告原始分布，不为简历目标追分；
- 1/5/20/50用户无跨租户、任务丢失、重复终态和长期饥饿；
- 增量计算和分区裁剪相对全量基线稳定、明显降低扫描量，并保留原始扫描行数/字节；
- 镜像以非 root 运行且高危镜像漏洞为0，Secret不进入镜像/Manifest/Git历史；
- K8s readiness 与优雅终止有效，滚动更新期间可用请求无5xx，Worker驱逐后任务可恢复；
- requests/limits、HPA、PDB、NetworkPolicy 和回滚步骤均有可执行 Manifest 与演练记录；
- 生成完整 Gate、失败案例、数据分析、数据开发和演示文档；
- 完成 Secret、数据许可和仓库历史检查，但 GitHub 继续保持私有直到用户授权。

## 达成效果

项目最终不再依赖“看起来像一篇专业报告”的主观展示，而是可以分别回答：

1. Agent 是否比规则/统计/单 Agent 更有效；
2. Supervisor 是否减少无价值子 Agent；
3. 风险信号是否在后续披露中具有解释力；
4. 数据链路是否可重放、可回填并通过质量 Gate；
5. 多用户共享分析是否真正降低延迟和外部调用。
