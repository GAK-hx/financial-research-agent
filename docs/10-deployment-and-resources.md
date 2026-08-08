# 10 部署与资源设计

## 1. 第一步服务

部署原则：**Docker优先**。项目主体、依赖和任务运行环境均放入Docker；宿主机不承担Python依赖和数据处理逻辑，只负责Docker Compose、环境变量、卷目录和管理命令。

| 服务 | 内存上限 | 说明 |
|---|---:|---|
| Etcd | 256MB | Milvus元数据 |
| Milvus | 1800MB | 研报索引 |
| App | 900MB | API、编排、Iceberg查询 |
| Rag Index（一次性） | 约1500MB建议 | 不常驻 |

Kafka/Flink不在第一步常驻Compose。旧项目保留实验链路，需要演示时独立启动，不能与真实域共表。

## 2. 端口

- App：8000；
- 新Milvus宿主端口：19531，容器内部19530；
- 避免与旧项目Milvus 19530冲突。

## 3. 数据卷

- `lake_data`：Iceberg Warehouse和SQLite Catalog；
- `milvus_data`：向量数据；
- `etcd_data`：Milvus元数据；
- 研报：第一阶段只读挂载旧项目已验证PDF，审核后可复制到独立数据目录。

## 4. 任务运行方式

- 常驻：App、Milvus、Etcd；
- 一次性容器：日线采集、财务采集、RAG索引、数据质量检查和评测；
- 单写者：采集任务写Iceberg时API保持只读；
- 索引任务完成后停止，释放模型内存。

建议通过Compose Profiles区分：

```text
default：app + milvus + etcd
ingestion：market-ingest + financial-ingest
indexing：rag-index
evaluation：evaluator
experimental：后续可挂接旧Kafka/Flink实验链路
```

容器共享接口模型代码和配置，但使用不同启动命令。禁止在宿主机手工安装一套依赖、容器内再维护另一套依赖。

## 5. 第二阶段已实现扩展

- PostgreSQL保存Run、Memory、Job、Gateway/Budget审计和LangGraph Checkpoint；
- 独立Job API与Worker处理异步任务；
- SSE、状态、Cancel/Resume和Trace已实现；
- Artifact保存在宿主目录，正式评测产物已版本化；
- 稳定实时源出现后再评估Kafka/Flink和在线存储。

## 6. 不做事项

- 第一阶段不做Kubernetes；
- 不增加HDFS/MinIO；
- 不为简历堆叠无实际用途的中间件；
- 不在没有稳定实时源时增加ClickHouse。

## 7. 待审核决策

- 是否继续只读挂载旧研报，还是将6份PDF复制进新项目？
- App是否需要常驻Embedding模型？建议索引与查询实测内存后决定。
- 第二步Run Store选PostgreSQL还是先SQLite？建议PostgreSQL，但等Harness设计冻结后决定。
