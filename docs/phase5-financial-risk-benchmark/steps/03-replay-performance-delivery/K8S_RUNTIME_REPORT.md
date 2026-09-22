# Kubernetes运行与故障恢复报告

## 结论

03-D已经从“Manifest可渲染”推进到真实本地集群运行。Kind创建1个control-plane和2个worker逻辑节点，
Gateway、API、Worker、PostgreSQL和Redis均处于Ready；数据库迁移、Iceberg Catalog接入、端到端模型任务、
Worker接管、Redis降级、Gateway滚动更新与回滚、SSE续传和租户隔离均完成验证。

这证明的是本地Kubernetes部署和恢复流程可执行，不等价于生产多机高可用、自动扩缩容或容量SLA。

## 运行拓扑

- Kind v0.33.0，Kubernetes v1.37.0，Apple Silicon arm64；
- 3个节点容器共享同一台Mac；
- Gateway、API和Worker分别部署；PostgreSQL保存Job事实，Redis承担限流与热状态；
- API、Worker和初始化任务共享2 GiB RWO湖PVC；Iceberg Catalog使用PostgreSQL；
- 从原Docker湖注册9张已有Iceberg表，未重写Parquet数据。

## 实测场景

### 正常任务

数据迁移后提交真实查询，任务在第1次尝试完成，得到1条Evidence，报告校验通过。总耗时19,719 ms，
其中排队375 ms、执行19,344 ms。该数字只说明本地链路贯通。

### Worker退出与任务接管

任务进入running后强制删除Worker Pod。新Worker在30秒租约到期后接管，任务第2次尝试完成。55个事件ID连续，
`job_reclaimed`、`run_terminal`和`job_terminal`各出现1次，因此没有任务丢失或重复终态。

### Redis降级

Redis缩容到0期间，Gateway readiness保持UP，已有完成任务仍可从PostgreSQL读取并返回200；新任务因限流后端
不可用返回明确的可重试503，而不是静默放行。Redis恢复后组件重新Ready。

### Gateway更新、回滚与SSE

Gateway滚动更新期间连续80次读取全部返回200。随后对Pod模板增加无业务影响注解，完成滚动更新，再执行
`rollout undo`，两次均恢复Ready。SSE以`Last-Event-ID=52`重连只收到53、54、55号事件，终态一次。

本地端口转发会随旧Pod退出而断开，这属于调试通道行为；重新连接Service后事件可以续传。

### 多租户隔离

以tenant-a/user-a提交的任务，所有者读取返回200；tenant-b/user-b读取相同任务ID返回404 `JOB_NOT_FOUND`。
任务最终完成且校验通过，未暴露任务是否属于其他租户。

### 初始化Job

首次CronJob使用采集镜像，与PostgreSQL Iceberg Catalog依赖不匹配而失败。初始化职责改用已具备完整驱动的API
镜像后，手动任务4秒完成并输出`all namespaces already exist`。该结果验证初始化幂等性，不声称已经实现
Kubernetes定时增量采集。

## 尚未覆盖

- 本地未部署metrics-server，HPA目标显示`unknown`，仅验证资源存在、上下限和指标配置；
- 没有验证跨物理节点、多可用区、云负载均衡、托管数据库或对象存储；
- Kind中的PostgreSQL与Redis使用本地临时存储，不能直接作为生产设计；
- 共享RWO PVC只适合本机演练，生产应使用对象存储和共享Catalog；
- 未把本地耗时包装为生产延迟，也没有进行镜像漏洞与SBOM交付验证。

机器可读结果见`artifacts/phase5_step03/k8s_runtime_v1/report.json`，完整异常过程见`03D_FAILURES.md`。
