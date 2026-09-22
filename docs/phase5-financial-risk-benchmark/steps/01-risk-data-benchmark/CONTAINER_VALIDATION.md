# Step 01 容器独立运行记录

## 2026-09-16 已验证

- `risk-step01` 第一次完整构建成功；无需挂载本地 `src/` 或 `tests/`，12/12 基础检查通过。
- `risk-step01-cached-ingest` 与 `risk-step01-cached-eval` 在只读源码挂载下完成 100 家三表、特征、质量、Benchmark、基线及统一 Gate。缓存模式是真正的 Docker 执行，但不是最终可移植镜像。
- 正式镜像根文件系统只读，仅挂载 `/artifacts` 可写；移除 Linux capabilities，启用 `no-new-privileges`，资源上限 2 CPU/1400 MiB/256 pids。不读取模型 `.env`。

## 镜像职责

- `risk-step01` 是取数、PIT 特征、Benchmark 与基线的主镜像，当前版本已能独立运行；
- PDF 下载和内容解析继续复用已经跑通的 `risk-step01-cached-eval` 评测容器，Step 01 不再为了合并这两个镜像反复重建；
- Step 03 再按 API、Worker、采集、评测四类职责拆分并固化镜像，不把当前 Demo 的镜像整理当成业务 Gate。

## 完成判据

主镜像已经完成不挂载源码的基础检查；数据流水线和 PDF 工作表检查器已在对应 Docker 容器运行。当前自动 Gate 8/8、人工作业 0/2，人工任务未完成不属于容器故障。Kubernetes 清单和弹性部署属于 Step 03，不纳入本轮 Step 01 判定。
