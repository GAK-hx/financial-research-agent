# 第一阶段资源摘要

最终空闲快照：

| 服务 | 实际内存 | 限制 | 状态 |
|---|---:|---:|---|
| App | 461.4MiB | 900MiB | Pass |
| Milvus | 638MiB | 1800MiB | Pass |
| etcd | 48.59MiB | 256MiB | Pass |

- App镜像大小：470,268,861 bytes（约448.5MiB）；
- App为CPU-only RAG镜像；
- 模型缓存位于独立Docker Volume；
- Milvus、etcd、Iceberg和Artifact使用独立Volume/挂载；
- 资源数据为单次快照，不等同于长期并发压测峰值。
