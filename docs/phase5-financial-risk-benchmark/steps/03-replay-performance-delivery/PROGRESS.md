# Step 03 进度

- 状态：`COMPLETE_WITH_LIMITATIONS`；
- 前置：Step 02 Gate 已完成（7/7）；
- 当前工作包：`03-D Docker/K8s与最终交付`；
- 最近更新：2026-09-21。

## 任务

- [x] 5点历史source-time Point-in-Time回放，PIT泄漏与主键重复均为0；
- [x] 公开V4FinBench一年期前瞻与概率校准报告；不扩展多期限刷分；
- [x] 子Agent边际贡献引用Step 02公开同题消融，不在自有数据上制造准确率；
- [x] 公共 Artifact 与用户报告缓存隔离；
- [x] 1/5/20/50用户 Gate；
- [x] Spark/Iceberg性能与恢复；
- [x] Agent/数分/数开交付文档；
- [x] 锁定Step 02公开Benchmark结果，不新增私有Holdout；
- [x] Kubernetes Base/Kind清单与离线Manifest Gate；
- [x] Kind三逻辑节点运行、滚动更新、回滚和故障恢复演练；
- [x] 最终 Gate 与失败案例报告。

## 进度记录

| 日期 | 状态 | 说明 |
|---|---|---|
| 2026-09-06 | BLOCKED_BY_DEPENDENCY | 仅完成计划，等待 Step 01 和 Step 02 |
| 2026-09-20 | READY | Step 01和Step 02 Gate均已通过，可以开始历史回放、并发性能和部署交付 |
| 2026-09-20 | IN_PROGRESS | 启动03-A；采用source-time backfill replay，明确不冒充当年knowledge-time快照 |
| 2026-09-20 | IN_PROGRESS | 03-A完成：5点回放126,880条特征、39,040条候选，PIT泄漏和主键重复为0；相邻快照潜在受影响键约5.1%～9.4%，进入03-B |
| 2026-09-20 | IN_PROGRESS | 03-B完成：风险数据快照、公共分析和用户展示完成分层；Docker冻结响应Gate覆盖1/5/20/50用户，50用户250次查询只执行20次唯一公司分析，热态新增分析0次；2家公司更新只重算2家，用户身份泄漏0。延迟仅作同环境相对诊断，不作为生产或简历数字；进入03-C |
| 2026-09-20 | IN_PROGRESS | 03-C完成：Docker内Spark 4.2处理500万行合成数据；5%公司增量使扫描行与Iceberg计划文件均减少95%；错误Schema提交未产生Snapshot，相同增量重跑业务主键重复0、未受影响分区变化0；进入03-D |
| 2026-09-20 | IN_PROGRESS | 03-D离线部分完成：Base/Kind清单、Secret边界、安全上下文、HPA/PDB/NetworkPolicy和交付文档已通过Manifest Gate；Kind v0.33.0二进制下载停滞，未虚报集群运行、滚动更新或驱逐演练 |
| 2026-09-21 | COMPLETE_WITH_LIMITATIONS | Kind v0.33.0三逻辑节点全部Ready；正常任务、Worker租约接管、Redis降级、Gateway滚动更新/回滚、SSE续传、多租户隔离和初始化Job幂等均通过。HPA动态扩缩容、云多机高可用、镜像漏洞扫描和生产SLA未声明完成 |
