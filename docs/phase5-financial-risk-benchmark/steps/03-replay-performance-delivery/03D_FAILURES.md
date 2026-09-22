# 03-D 失败与处置记录

## 1. kubectl客户端Dry Run仍需要API Discovery

在尚未配置集群时执行：

```text
kubectl apply --dry-run=client --validate=false -f rendered.yaml
```

关键输出：

```text
couldn't get current server API group list
Get "http://localhost:8080/api?timeout=32s": connect: operation not permitted
unable to recognize rendered.yaml
```

`kubectl kustomize` 已能完整生成 Base 和 Kind Overlay；但 `kubectl apply --dry-run=client` 对资源类型仍会执行
API discovery，因此无集群时不能作为离线Schema验证器。

处置：增加项目内 Manifest Gate，离线检查资源类型、探针、requests/limits、安全上下文、NetworkPolicy和
Secret边界。集群建立后仍必须执行真实 `kubectl apply`，离线Gate不能替代运行验证。

## 2. Kind官方二进制下载停滞

已从官方 GitHub API 确认当前稳定版为 Kind v0.33.0，发布日期2026-08-26，默认Kubernetes 1.37.0。
随后从官方Release下载darwin-arm64二进制，连续约110秒保持0 B，手动终止。

处置：首次下载被中止后保留记录；网络恢复后重新下载并建立Kind三节点，随后完成滚动更新、回滚、Worker
驱逐、Redis降级、SSE重连和初始化Job验证。首次失败不再是当前阻塞。

## 3. Manifest Gate首次误报限流参数

首次离线Gate把 `GATEWAY_RATE_LIMIT_REQUESTED_TOKENS=1` 中的复数 `TOKENS` 当成了认证Token，导致
`configmap_contains_no_secret_values=false`。该字段表示单请求消耗的令牌桶额度，不是凭据。

修正：敏感字段继续匹配password、api_key、secret和credential；Token仅匹配明确的 `token`、
`access_token`、`refresh_token` 字段，不因普通计量字段包含tokens而失败。

## 4. 共享湖PVC检查被同名HPA覆盖

- 现象：新增共享PVC检查后，渲染清单中的 `job-api` 被报告为未挂载PVC；
- 原因：检查器先读取Deployment，随后又把同名HPA当成Pod工作负载，以空结果覆盖；
- 处置：只对Deployment和CronJob读取Pod Volume；没有修改Manifest来迎合检查；
- 复测：见 `artifacts/phase5_step03/k8s_manifest_v1/manifest-gate.json`。

## 5. API测试受本机.env身份配置污染

- 现象：收口测试中API用例2项返回401，风险与缓存用例其余20项通过；
- 关键输出：`AssertionError: 401 != 200`，发生于 `/tools` 和 `/analyze`；
- 原因：测试构造的Settings继续读取本机 `.env`，继承了 `IDENTITY_MODE=api_key`，而测试请求按本地模式未传认证头；
- 处置：测试Fixture显式设置 `identity_mode="local"`，保证结果不依赖开发者本机密钥配置；未降低生产认证要求。

## 6. Kind批量导入官方多平台镜像失败

- 现象：项目镜像逐个导入成功，导入 `postgres:17.10-alpine3.23` 时Containerd返回
  `content digest ... not found`；
- 证据：Containerd公开问题
  [#11344](https://github.com/containerd/containerd/issues/11344)记录了带Attestation的镜像在
  `ctr images import --all-platforms` 下出现相同错误；Kind公开问题
  [#2402](https://github.com/kubernetes-sigs/kind/issues/2402)也记录了相同导入症状；
- 处置：不修改通用Base的官方镜像；仅为Kind Overlay基于已下载镜像生成
  `--platform linux/arm64 --provenance=false` 的本地标签后导入；
- 边界：这是本地集群镜像传输兼容处理，不是生产镜像发布方案。

## 7. 当前API镜像首次重建遇到SSL中断

- 现象：核心依赖与RAG依赖安装完成后，安装 `requirements-persistence.txt` 时失败；
- 关键输出：`ssl.SSLError: [SSL] record layer failure (_ssl.c:2590)`；
- 处置：保留已完成的BuildKit缓存，只指定 `job-api` 重试；Compose可能为相同构建定义同时输出迁移镜像标签，
  但BuildKit层只执行一次；
- 结果：重试复用缓存后构建成功，新镜像已导入Kind，API和Worker滚动完成且健康检查通过。

## 8. 非root Pod解压湖数据不能修改PVC根目录元数据

- 现象：数据归档已复制进API Pod，但普通 `tar -xzf` 最后返回
  `Cannot utime`、`Cannot change mode`；
- 原因：业务Pod以UID 10001和只读根文件系统运行，不能把归档中的宿主机目录权限写到PVC根目录；
- 处置：保留非root策略，改用 `--no-same-owner --no-same-permissions -m` 只恢复文件内容；
- 边界：不使用root Pod、不增加Linux capability，也不放宽生产Manifest。

## 9. 轮询脚本使用了错误的终态名称

- 现象：首次真实任务已完成，但临时轮询脚本仍等待`succeeded`，继续轮询直到手动检查；
- 原因：本项目Job API的成功终态是`completed`，不是`succeeded`；
- 处置：后续演练按API模型使用`completed/failed/cancelled`判断终态；
- 影响：只影响临时观察脚本，没有导致任务重复提交或状态丢失。

## 10. Gateway滚动更新后旧端口转发失效

- 现象：Gateway Pod滚动替换后，绑定旧Pod的`kubectl port-forward`出现`Empty reply from server`；
- 原因：端口转发进程跟随被终止的旧Pod，不是Gateway Service或SSE事件丢失；
- 处置：重新建立Service级端口转发，以`Last-Event-ID=52`重连后只收到53～55号事件，终态事件1次；
- 边界：端口转发是本地调试通道，生产入口应由Ingress或LoadBalancer维持连接。

## 11. 湖初始化CronJob首次使用了不匹配的镜像

- 现象：手动实例化`lake-bootstrap`后Job达到`BackoffLimitExceeded`，Pod按策略删除；
- 原因：CronJob复用了仅含采集依赖的`financial-ingest`镜像，而当前Iceberg Catalog使用PostgreSQL；
- 处置：初始化任务改用已验证包含PyIceberg与PostgreSQL驱动的`job-api`镜像，重新运行4秒完成，日志为
  `all namespaces already exist`；
- 边界：该CronJob只负责幂等创建湖命名空间，不等同于已实现K8s定时增量采集。
