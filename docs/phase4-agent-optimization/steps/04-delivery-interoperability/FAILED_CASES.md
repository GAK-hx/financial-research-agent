# Step 04 失败与修正记录

## F-04-01：正式 Worker 领取了集成测试 Run

- 现象：Lease 恢复测试中，恢复后的 Job 在取消前变成 `running`；
- 原因：测试与常驻 Worker 共用同一 PostgreSQL Queue，正式 Worker 合法领取了测试任务；
- 风险：使测试非确定，并可能误触发模型调用；
- 修正：冻结并发和 PostgreSQL Gate 期间先排空并暂停正式 Worker，Gate 后用新镜像恢复；
- 复验：PostgreSQL JobStore 5/5 通过。

这不是业务竞态缺陷，而是测试隔离缺陷。后续 CI 应使用独立数据库或独立 Schema。

## F-04-02：Flash Planner Gate 错误实例化数据 Tool

- 现象：第一次 Flash Gate 在发出模型请求前因 `/lake/iceberg_catalog.db` 不可写失败；
- 原因：脚本为获取 Tool Schema 调用了 `build_formal_registry`，连带实例化 Iceberg Repository；
- 修正：直接从 Tool 类的 `definition` 和 Pydantic `input_model` 生成 Schema，不建立数据连接；
- 数据边界：失败发生在本地初始化，未向 DeepSeek 发送请求；
- 复验：Flash Planner 并发 2/2 通过。

## F-04-03：50 VU 准入延迟上升

- 现象：冻结负载 50 VU 的 API 接收 P95 为约 1.79 秒，吞吐低于 30 VU；
- 原因：为保证全局排队上限不被竞态突破，当前入队临界区使用 PostgreSQL 事务锁；
- 处理：将三次计数查询合并为一次条件聚合，并把容量结论限定为中等并发；
- 未做：没有为了表面吞吐绕过全局上限，也没有在无证据时引入 Redis/Celery；
- 后续：若目标要求更高 QPS，先实现原子 Counter/Lease 表并重新冻结基准。

## F-04-04：宿主机静态检查触发 PyArrow 源码构建

- 现象：`uv run --extra dev` 在宿主机 Python 3.14 环境尝试源码构建 PyArrow，并因缺少 CMake 失败；
- 原因：项目正式运行版本是 Python 3.11，宿主机解析到了尚无对应 Wheel 的组合；
- 修正：运行时和完整回归以 Docker Python 3.11 为准；纯静态检查使用 `uvx ruff`；
- 复验：Ruff 全部通过，Docker 镜像成功构建。

该问题属于开发机依赖解析，不是业务代码失败；没有为了通过而移除 PyArrow/Iceberg 依赖。

## F-04-05：完整回归受到执行环境与历史记忆污染

- 现象：第一次手工 `docker run` 遗漏 Compose 数据库变量；改正后记忆 API 测试仍读到历史
  `local/local` 记录；
- 原因：手工容器没有继承正式 Compose 环境，且 Step 04 后服务会覆盖请求体身份，旧测试仍按
  请求体中的随机租户执行清理；
- 修正：统一使用 Compose 回归；记忆 API 测试切换到 `api_key` 模式并通过可信身份头使用随机
  租户/用户；
- 复验：同一持久 PostgreSQL 环境完整回归 168/168 通过。

修正验证的是新身份边界的真实行为，也使测试可重复执行；没有清空整个数据库绕过问题。
