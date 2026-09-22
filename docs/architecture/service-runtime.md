# 服务与部署

## 服务职责

- Spring Gateway：外部认证、身份头清洗、Redis限流、超时与SSE代理；
- FastAPI Job API：任务创建、查询、取消、恢复、Trace和事件；
- Worker：领取任务、执行LangGraph、续租和写入终态；
- PostgreSQL：Job、事件、租约、Checkpoint、审计和公共分析事实；
- Redis：限流、并发槽位、single-flight热索引和事件通知；
- Iceberg Catalog与湖存储：分析事实和Snapshot。

## 可靠性语义

- Idempotency Key在租户范围内唯一；
- Worker使用租约和心跳，退出后可由其他Worker接管；
- 终态写入幂等且只能出现一次；
- Redis不可用时新建昂贵请求失败关闭，已完成任务仍从PostgreSQL读取；
- SSE通过`Last-Event-ID`从持久事件续传；
- 外部传入的tenant/user头会被Gateway删除并重新建立。

## 部署形态

Docker Compose用于本地开发和集成测试。Kubernetes Base提供Deployment、Job、CronJob、HPA、PDB、探针、
NetworkPolicy、ServiceAccount和Secret边界；Kind Overlay用于单机三逻辑节点演练。

Kind只验证清单和恢复流程，不等价于多机、多可用区生产集群。生产环境应使用对象存储、共享Catalog、托管
PostgreSQL/Redis、Ingress或LoadBalancer以及外部Secret Manager。
