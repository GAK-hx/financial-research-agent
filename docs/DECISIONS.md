# Architecture Decisions

> 本文件用于记录审核后的决定。第一阶段基础接口规范已于 2026-07-14 获得确认。

| ID | 主题 | 决定 | 原因 | 影响阶段 | 状态 | 日期 |
|---|---|---|---|---|---|---|
| ADR-001 | 第一版股票池 | 首批覆盖600519、300750 | 与现有6份研报对应，先完成可验证闭环 | Step 1 | Accepted | 2026-07-14 |
| ADR-002 | 日线复权口径 | 默认只使用前复权日线 | 满足收益和技术指标连续性，避免第一版多口径混用 | Step 1 | Accepted | 2026-07-14 |
| ADR-003 | 财务域范围 | 接入三张报表；首批开放营收、归母净利润、同比增长、毛利率、资产负债率、经营现金流和ROE | 范围足以支持基础研究且可测试 | Step 1 | Accepted | 2026-07-14 |
| ADR-004 | Raw响应保留 | 开发阶段按采集批次保存原始Parquet；异常行隔离，正常行继续入库，批次标记Warning | 便于追踪AkShare字段变化和质量问题 | Step 1 | Accepted | 2026-07-14 |
| ADR-005 | Run调试存储 | 第一阶段按run_id保存本地JSON调试产物 | 避免过早引入运行数据库，保留排错能力 | Step 1 | Accepted | 2026-07-14 |
| ADR-006 | Replan策略 | 第一阶段不启用动态Replan | 先稳定标准轨迹，限制Agent自主性和复杂度 | Step 1 | Accepted | 2026-07-14 |
| ADR-007 | 模型失败降级 | Planner失败使用规则计划；正式报告失败明确报错；部分工具失败可返回带Warning的部分报告 | 不使用模板冒充模型报告，也不因单工具失败丢弃全部证据 | Step 1 | Accepted | 2026-07-14 |
| ADR-008 | RAG分块/Rerank | 使用500字符/50重叠和现有6份研报；第一阶段不加Reranker | 复用已跑通方案，先建立检索基线 | Step 1 | Accepted | 2026-07-14 |
| ADR-009 | 多轮Session记忆 | Session默认30天TTL；Preference仅显式确认后保存；不保存历史研究结论作为事实 | 控制过期与错误事实污染，同时支持多轮指代和用户偏好 | Step 2 | Accepted | 2026-07-24 |
| ADR-010 | Harness持久化存储 | LangGraph使用AsyncPostgresSaver；业务数据使用PostgreSQL + SQLAlchemy Async + asyncpg + Alembic | 复用PostgreSQL但分离Checkpoint与业务表责任 | Step 2 | Accepted | 2026-07-24 |
| ADR-011 | 部署原则 | Docker优先：常驻服务和一次性任务均尽量容器化，宿主机仅负责Compose、配置和管理命令 | 保证环境一致、可复现并便于交付 | Step 1 | Accepted | 2026-07-14 |
| ADR-012 | 财务公告日期 | 保留来源公告日期但标记为非时点可用；第一阶段不支持财务时点回测 | Sina历史公告日期可能反映后续更新，不能冒充首次披露日 | Step 1 | Accepted | 2026-07-15 |
| ADR-013 | 模型Provider适配 | 使用项目内部`openai_compatible`适配器调用DeepSeek官方OpenAI兼容API；第一阶段使用`deepseek-v4-flash` | 保持编排框架无关，同时复用官方兼容协议 | Step 1 | Accepted | 2026-07-15 |
| ADR-014 | 第一阶段评测集 | 使用20题确定性评分集，覆盖行情、指标、财务、研报、综合和非法输入；开发回归集与第二阶段Holdout分离 | 避免模型自评并明确100%回归结果的泛化边界 | Step 1/2 | Accepted | 2026-07-15 |
| ADR-015 | 第一阶段关闭 | 接受第一阶段测试、评测、资源和限制说明，后续能力扩展进入第二阶段Harness | 第一阶段已形成可复现单Run研究闭环 | Step 1 | Accepted | 2026-07-15 |
| ADR-016 | 第二阶段运行时 | 使用LangGraph StateGraph，不使用LangChain高层通用Agent | 复用成熟Checkpoint和恢复能力，同时保留受控金融流程 | Step 2 | Accepted | 2026-07-24 |
| ADR-017 | Skill管理 | 参考Hermes建立声明式Skill Registry；模型只能生成DRAFT，不能自动激活 | Skill可版本化和审计，且不能扩大工具权限 | Step 2 | Accepted | 2026-07-24 |
| ADR-018 | Gateway与权限 | 正式Model/Tool调用统一经过Gateway；研究工具继续只读 | 统一参数、预算、错误、权限和审计边界 | Step 2 | Accepted | 2026-07-24 |
| ADR-019 | API与Worker | FastAPI Job API + SSE，保留同步`/analyze`；API/Worker拆分并先用PostgreSQL领取Run | 提供异步运行与恢复，同时避免过早增加Redis/Celery | Step 2 | Accepted | 2026-07-24 |
| ADR-020 | Context压缩 | 按节点和Skill压缩模型视图；原始Evidence、数字和Source Locator不可被摘要覆盖 | 降低Token同时保持事实可追溯 | Step 2 | Accepted | 2026-07-24 |
| ADR-021 | 第二阶段Replan | Replan仍为0，仅在LangGraph中预留受控扩展边 | 先验证状态化运行与治理，不同时扩大Agent自主性 | Step 2 | Accepted | 2026-07-24 |
| ADR-022 | 第二阶段默认预算 | 候选值为180秒、模型5次、工具12次、并行4、Evidence 60条、报告修订1次；Token和费用待实测冻结 | 先给出确定性上限，再依据真实Usage校准成本 | Step 2 | Accepted | 2026-07-24 |
| ADR-023 | 第二阶段评测 | 20题Regression + 至少30题Holdout + 10题各运行3次 | 分离回归、泛化和稳定性证据 | Step 2 | Accepted | 2026-07-24 |
| ADR-024 | Hermes与Pi边界 | 只参考Skill、Memory、Session和Compaction设计，不引入完整运行时 | 避免Python金融栈与通用/Coding Agent运行时耦合 | Step 2 | Accepted | 2026-07-24 |
| ADR-025 | 评测参考日期 | 完整回归必须显式设置`EVALUATION_REFERENCE_DATE`并与数据集`as_of_date`一致；生产默认不设置 | 保证相对日期问题在不同运行日期仍可复现，且不改变生产的真实当天语义 | Step 1/2 | Accepted | 2026-07-24 |
| ADR-026 | LangGraph技术准入 | 接受Step 01技术Go结论，进入正式等价迁移；Provider网络和模型输出稳定性作为已记录风险进入后续Gateway与评测步骤 | Spike已证明现有Provider、异步Tool、Iceberg和Checkpoint可以协同运行，且不要求改写业务接口 | Step 2 | Accepted | 2026-07-24 |
| ADR-027 | Step 02 Tool并发边界 | LangGraph负责编排阶段状态，Tool DAG、并发和Tool级重试暂时复用`PlanExecutor`；待Step 05 Tool Gateway后再评估逐调用LangGraph Task | 等价迁移期避免同时维护两套调度器，保留已验证的依赖失败、并发和重试语义 | Step 2 | Accepted | 2026-07-24 |
| ADR-028 | 开发验证节奏 | 子任务只做最小冒烟；每个Step收尾集中执行专项、全量、评测和真实链路，问题修正后只做针对性确认 | 减少重复且无信息增量的测试，把时间用于实现和设计审核 | Step 2 | Accepted | 2026-07-24 |
| ADR-029 | Step 02关闭 | 接受StateGraph等价迁移技术Go结论；DeepSeek网络稳定性继续作为Step 05风险处理 | 最终镜像81/81通过，确定性指标18/18，双方成功用例16/16语义一致 | Step 2 | Accepted | 2026-07-24 |
| ADR-030 | 默认模型 | Planner、报告、修订、摘要、Reviewer和项目评测默认统一使用正式版`deepseek-v4-flash`；Pro只允许显式实验覆盖，不作为自动路由或失败降级 | 按当前模型版本的项目选型，Flash已成为质量、延迟和成本更合适的统一默认；统一模型也便于维护可比较的评测基线 | 全项目 | Accepted | 2026-08-08 |
| ADR-031 | V4.1 Flash升级 | 生产与公开Benchmark默认改用DeepSeek V4.1 Flash正式API名`deepseek-flash`；退役别名`deepseek-v4-flash`只保留在历史证据和兼容说明中，不作为独立模型对比 | DeepSeek官方已退役V4 Flash并将旧名临时路由到V4.1 Flash；使用正式名称避免临时别名失效及伪造模型差异 | 全项目 | Accepted | 2026-09-16 |
| ADR-031 | 生产与评测时钟 | 生产按`Asia/Shanghai`真实当前日期运行；只有冻结评测显式设置参考日期 | 避免Demo参考日期污染生产语义，同时保持相对时间评测可复现 | Phase 4 Step 01 | Accepted | 2026-08-08 |
| ADR-032 | 语义对齐边界 | 在Tool执行前独立复核原问题与QuerySpec的实体、时间、粒度、维度和分析域；不确定相对时间拒绝静默猜测 | 结构化Schema正确不等于用户语义正确，必须在真实数据访问前阻断漂移 | Phase 4 Step 01 | Accepted | 2026-08-08 |
| ADR-033 | 报告证据结构 | 摘要、结论、风险和含数字限制均使用当前Run Evidence ID；风险记录事实/计算/模型解释分类 | 把引用从“有ID”升级为可验证的数字、实体、日期和Source Locator支撑关系 | Phase 4 Step 01 | Accepted | 2026-08-08 |
| ADR-034 | 评测输入冻结 | 正式评测校验数据集哈希、Iceberg Snapshot、PDF哈希和检索配置；当前私有Holdout只从仓库外加载 | 防止数据漂移与题集泄露造成不可复现或虚高分数 | Phase 4 Step 01 | Accepted | 2026-08-08 |
| ADR-035 | Git发布边界 | 本地初始化Git并建立离线CI；Key轮换、私有Holdout和数据许可审核完成前不创建公开远程 | Git可用于工程管理，但不能把本地可运行误认为可安全公开 | Phase 4 Step 01/04 | Accepted | 2026-08-08 |
| ADR-036 | 数值表达变体 | Validator保持Evidence精确支撑，同时允许有上下文的涨跌方向、回撤幅度和显示舍入等价 | 金融报告存在合法表达变体，严格字符串符号一致会产生误杀，任意宽松又会放过伪造数字 | Phase 4 Step 01 | Accepted | 2026-08-08 |

状态取值：`Proposed`、`Accepted`、`Rejected`、`Superseded`。
