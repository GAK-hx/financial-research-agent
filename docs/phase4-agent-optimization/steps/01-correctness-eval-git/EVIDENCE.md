# Step 01 实现与验证证据

## 1. 正确性实现

- `QuerySpec` 新增 `analysis_domains` 与结构化 `time_scope`；
- 新增 `SemanticAlignmentValidator`，在 Tool 执行前检查实体、意图、分析域、维度、日期范围、
  周期粒度和完整周期边界；
- 生产默认使用 `Asia/Shanghai` 当前日期，冻结评测才显式覆盖参考日期；
- API 输出 `semantic_alignment` 与 `execution_metadata`；
- LangGraph 增加 `align_semantics` 节点，语义错误进入受控失败终态；
- 综合 Skill 的 Evidence 要求按问题中明确出现的行情、财务、研报域动态收敛，不扩大权限。

真实综合请求在 2026-08-08 解析为 `2025-08-08..2026-08-08`，分析域为
`market + report`，`semantic_alignment.passed=true`；实际数据最大日期独立记录为
`2026-07-14`。

## 2. 报告与 Evidence

- 报告升级为 `summary_evidence_ids`、结构化 `risks` 与结构化 `limitations`；
- 摘要、结论、风险和含数字限制均检查当前 Run Evidence；
- 校验 Evidence ID、实体、Source Locator、研报页码/机构、日期与数字；
- 计算风险必须引用 calculation Evidence；
- 支持“下跌 11.2572%”与 `-11.2572%`、回撤正幅度与负值存储、显示舍入等合法金融表达；
- Planner/Reporter 运行提示词升级为 `planner_v3/report_v3`。

## 3. 评测与快照

- 新指标：语义对齐、Evidence 支撑准确率、轨迹重复率；
- 当前公开 `holdout` 明确降级为历史基线；新的 `private_holdout` 只允许从仓库外加载；
- 正式评测必须同时匹配数据集日期、数据集哈希、Manifest 指纹和当前数据输入；
- 当前回归 Manifest：
  `fad917367c74236268adad952198d0c4fbdd32230488df9e7a6bf9ef307811a4`；
- Manifest 当前输入漂移复核：通过。

## 4. Docker、Git 与 CI

- Docker Python 3.11 应用镜像构建成功；
- Compose 生产/Job 服务不再注入固定评测日期；
- 默认研报挂载为本仓库 `./data/reports`；
- 本地 Git 已初始化为 `main`，尚未提交、尚未创建远程；
- `.env`、Lake、研报 PDF、模型缓存、数据库与运行产物均被忽略；
- 候选文件 Secret 扫描通过；
- Ruff CI 正确性基线通过；
- GitHub Actions 离线任务不调用真实模型 API。

## 5. 集中测试结果

| 验证 | 结果 |
|---|---:|
| Python 静态编译 | 通过 |
| Docker Compose 配置解析 | 通过 |
| Ruff 关键错误规则 | 通过 |
| Docker 全量测试（无外部集成开关） | 150 通过，19 跳过 |
| Docker + PostgreSQL 集成测试 | 150/150 通过，0 跳过 |
| Secret 扫描 | 通过 |
| 冻结 Manifest 生成及漂移复核 | 通过 |
| Flash 财务真实链路 | 通过，34.223 秒，1 条 Evidence，无修订 |
| Flash 综合真实链路（修复后） | 通过，47.603 秒，7 条 Evidence，无修订 |

测试中存在 FastAPI `on_event` 和 TestClient 的上游弃用警告，不影响本步正确性；迁移到 Lifespan
可放入后续交付优化。

## 6. 已知但未隐藏的限制

- `complete trading day` 当前使用周一至周五边界，尚未接入上交所/深交所官方节假日日历；
  节假日附近必须以 Evidence 的 `actual_end/data_as_of` 为准，不能把请求日期当作已有数据日期；
- 内置 Skill `1.0.0` 的 `prompt_refs` 是第二阶段不可变历史快照，仍显示 `v2`；实际模型调用由
  Gateway 记录 `planner_v3/report_v3`。Step 03 发布 Skill 后继版本时再迁移目录引用，避免原地篡改
  已持久化 Skill checksum；
- FastAPI Lifespan 和更广泛 Ruff 风格规则不属于本步正确性 Gate。
