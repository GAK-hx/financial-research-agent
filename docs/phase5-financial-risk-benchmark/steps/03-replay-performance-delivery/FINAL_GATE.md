# Step 03 最终Gate

## 结果

状态：`PASS_WITH_LIMITATIONS`。

Step 03已完成历史回放、跨用户公共分析复用、Spark/Iceberg增量处理和本地Kubernetes故障恢复。所有
效果准确率继续只引用公开Benchmark；自有公司数据和合成数据只用于流程、性能、恢复与部署验证。

## 03-A 历史回放

- 5个`as_of_date`共生成126,880条特征和39,040条候选；
- 2025和2026回放覆盖100家公司；
- PIT输出泄漏0，特征与候选主键重复0；
- 相邻快照潜在增量影响约5.1%～9.4%；
- 这是source-time backfill，不冒充当年系统knowledge-time快照。

## 03-B 并发与缓存

- 冻结响应Gate覆盖1/5/20/50用户，50用户250次交叉查询只执行20次唯一公司分析；
- 热态新增分析0次；两家公司变更只重算两家公司；
- 公共Artifact中用户身份泄漏0，Artifact一致性失败0；
- 延迟是进程内冻结响应数据，只用于比较缓存语义，不是生产API指标。

## 03-C Spark与Iceberg

- Docker内Spark 4.2处理500万行明确标记的合成数据；
- 5%公司增量将扫描行和Iceberg计划文件都减少95%；
- 失败提交不产生Snapshot，恢复后提交成功；
- 相同增量重跑业务主键重复0，未受影响分区变化0。

## 03-D Kubernetes

- Kind v0.33.0 / Kubernetes v1.37.0的3个逻辑节点全部Ready；
- Gateway、API、Worker、PostgreSQL、Redis、迁移Job和湖初始化Job真实运行；
- Worker强制退出后任务由新Worker接管，任务丢失0、重复终态0；
- Redis停机时已完成Job仍可读，新任务明确返回可重试503；
- Gateway滚动更新80/80请求成功，回滚后Ready；
- SSE从`Last-Event-ID`续传无重复终态；其他租户读取任务返回404；
- 初始化Job修正镜像后幂等完成。

## 未通过本Gate宣称的能力

- HPA已配置但本地无metrics-server，未做动态扩缩容压测；
- Kind三节点共享同一台Mac，不是生产多机或多可用区高可用；
- RWO湖PVC、本地PostgreSQL和Redis不是云上生产存储方案；
- CronJob只验证命名空间初始化，不代表定时增量采集已经实现；
- 未完成镜像漏洞/SBOM Gate和云上容量测试；
- 所有本地延迟均不作为生产SLA或简历性能数字。

## 证据入口

- `artifacts/phase5_step03/replay_v1/report.json`
- `artifacts/phase5_step03/cache_gate_v1/report.json`
- `artifacts/phase5_step03/spark_iceberg_v1/report.json`
- `artifacts/phase5_step03/k8s_manifest_v1/manifest-gate.json`
- `artifacts/phase5_step03/k8s_runtime_v1/report.json`
- `03D_FAILURES.md`
