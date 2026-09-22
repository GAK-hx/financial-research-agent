# 工程验证

## 历史回放

5个分析截止日共生成126,880条PIT特征和39,040条风险候选，PIT输出泄漏和业务主键重复均为0。相邻快照
潜在增量影响约5.1%～9.4%。这是source-time backfill，不冒充当年系统的knowledge-time快照。

## 缓存与并发

冻结响应测试覆盖1、5、20和50用户。50用户的250次交叉查询只执行20次唯一公司分析；热态新增分析0次；
两家公司数据变化只重算两家公司。公共产物中tenant/user/session泄漏为0。

毫秒级结果来自进程内冻结响应，仅验证缓存语义，不作为生产API延迟。

## Spark与Iceberg

Spark 4.2在Docker内处理500万行合成数据。5%公司增量将输入扫描从500万行降至25万行，Iceberg计划文件
从20个降至1个，均减少95%。失败提交不产生Snapshot；重跑后主键重复0、未受影响分区变化0。

## Kubernetes恢复

Kind v0.33.0 / Kubernetes v1.37.0的1个control-plane和2个worker逻辑节点完成演练：

- Gateway、API、Worker、PostgreSQL和Redis全部Ready；
- Worker强制退出后任务由新Worker接管，终态只写入一次；
- Redis停机时已完成任务仍可读，新任务明确返回可重试503；
- Gateway滚动更新期间80/80请求成功，回滚后Ready；
- SSE从`Last-Event-ID`续传无重复终态；
- 所有者读取任务返回200，其他租户读取同一ID返回404。

Kind节点共享一台Mac；本地未安装metrics-server，不声明多机高可用或HPA动态扩缩容已经完成生产验证。
