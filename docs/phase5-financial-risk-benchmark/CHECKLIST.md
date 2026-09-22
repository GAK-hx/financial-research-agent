# 第五阶段总清单

## Step 01：数据底座与公开 Benchmark

- [x] 完成100家公司三表和Iceberg数据底座；
- [x] 完成PIT特征、质量检查和重复运行验证；
- [x] 明确自有数据只用于演示和性能测试；
- [x] 接入FinanceBench官方公开数据；
- [x] 接入FinQA官方train/dev/test；
- [x] 接入TAT-QA官方train/dev/test gold；
- [x] 完成Agent输入与Gold隔离；
- [x] 完成三个公开Benchmark评分入口的最小验证；
- [x] 更新并通过Step 01统一Gate（8/8）。

## Step 02：公开 Benchmark 上的 Agent 优化

- [x] 建立DeepSeek V4.1 Flash直接回答和单Agent基线；
- [x] 完成LangGraph动态编排与LangChain Tool兼容；
- [x] 完成检索、计算、反证、引用和报告Skills；
- [x] 完成动态子Agent与Evaluator；
- [x] 比较直接模型、单Agent、固定多Agent和动态多Agent；
- [x] 完成上下文、缓存、Evaluator和修复消融；
- [x] 在三个公开Benchmark上生成正式指标和失败报告。

## Step 03：自有数据的运行效率与部署

- [x] 完成100家公司事实→PIT特征→风险候选的端到端历史回放；
- [x] 完成1/5/20/50用户及重叠公司负载测试；
- [x] 完成PostgreSQL任务、Redis共享缓存和Elasticsearch检索验证；
- [x] 完成查询、分析和输出分离及增量复用；
- [x] 完成API、Worker、采集、迁移与Gateway职责拆分；
- [x] 完成K8s Deployment/Job/CronJob、HPA、PDB、NetworkPolicy和探针；
- [x] 完成滚动更新、回滚、Worker驱逐和Job幂等演练；
- [x] 完成延迟、缓存、增量与故障恢复报告，并明确本地结果不是生产SLA；
- [x] 当前保持GitHub私有；公开仍需用户再次明确授权。
