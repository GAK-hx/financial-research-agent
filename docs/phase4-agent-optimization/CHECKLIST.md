# 第四阶段总清单

> 本清单用于导航和 Gate 审核。细节以各 Step 的 `PLAN.md` 为准。

## Step 01：正确性、评测与 Git 基线

- [x] 生产时钟不再被固定评测日期覆盖；
- [x] 原问题与 QuerySpec 的实体、时间、周期、量纲和意图完成语义对齐；
- [x] 报告摘要、风险和限制可追溯到结构化 Evidence；
- [x] 综合分析 Skill 的财务证据要求与实际能力一致；
- [x] 建立冻结数据快照、开发回归和仓库外私有 Holdout 入口；
- [x] 建立 Git 仓库、忽略规则、脱敏扫描、离线 CI 和私有 GitHub 流程；
- [x] 默认模型与当前文档统一为 `deepseek-v4-flash`；
- [x] Step 01 技术 Gate 通过并记录证据；
- [ ] 用户完成 Key 轮换与私有 Holdout，关闭发布 Gate。

## Step 02：知识、RAG、记忆与上下文

- [x] 建立可恢复的来源游标和原始事件/文档落湖；
- [x] 事件候选经过来源、时间、实体、去重和证据校验后才能激活；
- [x] 建立结构化父子分块、混合检索和增量索引；
- [x] 分别实现工作、情节、程序和偏好记忆的写入/读取/更新/清理；
- [x] 知识与会话记忆在模型、存储和生命周期上分离；
- [x] Context Manifest 记录来源、裁剪、压缩和 Token 预算；
- [x] 原始 Evidence 不被摘要覆盖，跨用户记忆隔离；
- [x] Step 02 Gate 通过并记录证据。

## Step 03：分析工具、Skill 与受控循环

- [x] 建立版本化 20 只演示股票池，并明确真实数据只覆盖 2 只；
- [x] 建立 Factor Registry、确定性计算和结果表；
- [x] 完成技术、基本面、截面、因子、事件和综合分析 Tool；
- [x] 将 Skill 升级为包含流程、Tool、知识和校验的版本化能力包；
- [x] 把 `concise`、`risk` 从能力 Skill 调整为报告 Profile；
- [x] 增加证据充分性节点和最多一次的受控修正；
- [x] 增加进展检测、动作去重、预算和明确终止原因；
- [x] 输出风险向量、情景分析、数据置信度和限制，不生成买卖建议；
- [x] Step 03 Gate 通过并记录证据。

## Step 04：多租户并发、交付、互操作与演示

- [x] 现有 FastAPI、Job、Worker、SSE 和 PostgreSQL 恢复流程保持可用；
- [x] 身份由认证边界生成，Run、Memory 以及 Run 下的 Result/Event/Trace 按租户隔离；
- [x] 实现全局、租户、用户三级排队/运行上限、Provider 速率窗口和过载响应；
- [x] 交互任务与批任务具有优先级，同级租户公平调度；
- [x] Provider、数据库与 Worker 具有有界资源池；Tool 原有超时/并发边界保持不变；
- [x] 完成 1/10/30/50 虚拟用户冻结压测和小规模 Flash Planner 并发验证；
- [x] 实测给出约 30 个同时提交的容量边界，未在无证据时引入 Redis/Celery；
- [ ] 增加可选、只读、默认关闭的 MCP Adapter；当前只交付共享 Tool Schema 和决策文档；
- [x] 若未来实现 MCP，已经明确必须复用原有 Gateway、Policy、Budget 和 Evidence；
- [x] Trace、失败分类、回放和取消/恢复保持可演示；
- [x] 薄 UI 通过正式 API 展示问题、进度、事件和终态结果；
- [x] Docker 镜像可构建并通过 Compose/PostgreSQL 完整回归，不依赖相邻旧项目目录；
- [ ] 完成 Secret/版权/数据许可检查后再决定是否公开 GitHub；
- [ ] 最终私有 Holdout 仍由用户在仓库外关闭；Step 04 已完成小规模 Flash 并发与延迟验收；
- [x] Step 04 技术 Gate 通过并记录证据，容量边界和发布阻断项已明确。
