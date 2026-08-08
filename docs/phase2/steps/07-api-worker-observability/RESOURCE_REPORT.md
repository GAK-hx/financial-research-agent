# Step 07 Docker资源报告

采样场景：Job API、双Worker、PostgreSQL和Milvus同时运行，已完成20任务竞争与真实
V4 Pro Run。`docker stats --no-stream`单点采样：

| 容器 | CPU | 内存使用 / 上限 | 内存占比 |
|---|---:|---:|---:|
| job-api | 14.19% | 131.7MiB / 700MiB | 18.82% |
| worker-1 | 2.75% | 151.4MiB / 1000MiB | 15.14% |
| worker-2 | 0.57% | 181.1MiB / 1000MiB | 18.11% |
| PostgreSQL | 25.00% | 91.76MiB / 512MiB | 17.92% |
| Milvus | 39.16% | 547.3MiB / 1.758GiB | 30.41% |

CPU是瞬时采样，不解释为持续平均负载；所有容器均低于内存上限。双Worker合计常驻
约332.5MiB。第二阶段尚未做长时间稳态压测，该工作属于Step08。

健康检查实测：

```text
configuration ready
iceberg       ready
milvus        ready
postgres      ready
model         configured
```
