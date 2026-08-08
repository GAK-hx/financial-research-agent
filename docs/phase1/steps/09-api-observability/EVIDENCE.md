# Step 09 验收记录

## API边界

- `/health`检查配置、Iceberg和Milvus；模型未配置时返回HTTP 200与`degraded`，不伪装为完全就绪；
- `/tools`仅公开白名单中的四个只读工具及参数Schema；
- `/analyze`统一返回`query_spec`、Plan、工具状态、Evidence、报告状态、耗时和运行版本；
- 输入错误返回HTTP 422及`code/message/run_id/details`；
- 工具已产生有效Evidence但报告生成失败时返回HTTP 200并携带业务错误，保留可审计的Run结果。

## 三条真实API Run

| 场景 | Run ID | HTTP | 工具结果 | 报告结果 | 总耗时 |
|---|---|---:|---|---|---:|
| Market | `7544e8cdcd8f454ea6ba92c691d994b4` | 200 | Evidence 2条 | `generation_failed` | 218ms |
| Report | `f2488459b3d44490aabf79b2aec4e9b4` | 200 | Evidence 5条 | `generation_failed` | 22070ms |
| Comprehensive | `707e7b655ccf4cd7a66b9efed48a34db` | 200 | Evidence 7条 | `generation_failed` | 52ms |

三个Run的报告失败原因均为`ProviderUnavailable:model provider is not configured`。这是当前环境的预期边界：Agent编排、真实数据工具和Evidence链路成功，但不使用模板冒充正式模型报告。Report首次检索包含BGE模型冷启动，因此耗时明显高于热路径。

Artifact：

- `artifacts/demo_runs/api_market.json`
- `artifacts/demo_runs/api_report.json`
- `artifacts/demo_runs/api_comprehensive.json`

## 日志与安全

- 日志为单行JSON，包含`request_id`、`run_id`、阶段耗时、各工具状态、模型与Prompt版本；
- 递归遮蔽包含`api_key`、`authorization`、`password`、`secret`、`token`的字段；
- 健康检查和Uvicorn访问日志降噪，保留业务请求与失败定位信息；
- 请求取消会记录取消事件；报告生成受Run剩余总预算约束，超时返回`RUN_TIMEOUT`。

## Docker与资源

- `app`、`etcd`、`milvus`均在Compose中运行，`app`健康检查为healthy；
- `app`限制900MB，三条真实Run后cgroup峰值约507.4MiB；
- Milvus当前约627.5MiB / 1.758GiB；
- etcd当前约47.6MiB / 256MiB；
- 最终Docker镜像内48/48项测试通过。

## 当前限制

- 尚未配置正式模型，所以本步骤只验收报告失败语义，正式报告质量留待模型接入后评测；
- 暂不包含持久化Run查询、SSE Token Streaming和Langfuse平台；
- 测试存在Starlette关于`httpx2`的弃用预警，不影响当前功能，依赖迁移可在后续维护中处理。
