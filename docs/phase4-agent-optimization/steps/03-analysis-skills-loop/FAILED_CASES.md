# Step 03 失败与修复记录

> 本文件保存 Step 03 开发和 Gate 中有诊断价值的失败输出。密钥、完整本地文档和大段模型输入均不写入。

## F-01：Debian Trixie 不提供指定的 OpenJDK 17 包

- 场景：首次构建 `factor-batch` 分析镜像；
- 结果：失败；
- 原始错误摘要：

```text
Package openjdk-17-jre-headless is not available
```

- 原因：当前 `python:3.11-slim` 基于 Debian Trixie，仓库包名和预期不一致；
- 修复：分析 Profile 改装 `default-jre-headless`，并按 Spark 4.2 的运行边界固定
  `pyspark==4.2.0`；
- 复测：镜像成功构建，实际运行报告 `pyspark-4.2.0+pyiceberg`。

## F-02：Debian 包下载暂时超时

- 场景：第二次构建分析镜像；
- 结果：失败；
- 原始错误摘要：

```text
temporary network timeout while fetching Debian package metadata
```

- 原因：外部网络不稳定，不是项目代码或数据错误；
- 修复：APT 增加 10 次重试和 60 秒 HTTP 超时；模型侧同步提高超时、重试和退避上限；
- 复测：镜像、Java、PySpark 依赖均成功安装。

## F-03：本机 Compose 版本不支持 `run --no-build`

- 场景：运行已构建的因子批任务；
- 结果：命令行参数失败，容器未启动；
- 原始输出：

```text
unknown flag: --no-build
```

- 修复：移除不兼容参数，使用 `docker compose --profile analysis run --rm factor-batch`；
- 复测：批任务成功产生 240 条因子记录。

## F-04：宿主机 Python 不包含项目依赖

- 场景：尝试在宿主机直接执行解释器冒烟；
- 结果：失败；
- 原始输出：

```text
ModuleNotFoundError: No module named 'pydantic'
```

- 结论：符合 Docker-first 约束，不向宿主机安装依赖；相关验证全部改在项目镜像内执行。

## F-05：首轮 Flash 把问题截止日写成证据截止日

- Run ID：`88843fc904b84ff3a5feaa8d000edc80`；
- 场景：真实 `deepseek-v4-flash` 事件分析 Gate；
- Agent 执行：首次事件检索为空，一次受控补充成功，6 条 Event/Report Evidence 均可追溯；
- 结果：报告初稿和一次模型修订均未通过；
- 原始校验错误：

```text
DATE_AS_OF_MISMATCH:expected=2026-05-20:actual=2026-08-08
COMPLETION_REPORT_NOT_COMPLETED
```

- 原因：模型使用了问题时间范围的结束日，而不是 Evidence 中最新可用数据日；此外“渠道改革”被
  过宽地识别为研报域；
- 修复：
  - `data_as_of` 改由 Harness 从 Evidence 确定性绑定，模型不再决定该元数据；
  - 事件意图只在明确出现“研报/机构/券商/观点”等词时才叠加研报域；
  - API 为补充任务恢复真实 `event_search` Tool 名称，不再显示 `unknown`；
- 复测 Run：`b454673bbac540c99ec14d1639d417cc`；
- 复测结果：`success=true`、Validation 通过、无报告修订、一次补充后正常终止。

## F-06：沙箱不能直接访问宿主机 8000 端口

- 场景：首次从受限命令环境调用本地 Docker API；
- 原始输出：

```text
curl: (7) Failed to connect to localhost port 8000 after 0 ms
```

- 结论：这是执行沙箱的网络隔离，不是 App 健康故障；经受控本机访问后 API 正常。

## 当前结论

- 所有可复现产品缺陷均已修复并复测；
- FastAPI `on_event` 和 TestClient 的上游弃用警告不影响本 Step，列为后续依赖升级事项；
- App 冷启动首次请求仍包含模型/Embedding 初始化耗时，留给 Step 04 并发与容量治理。
