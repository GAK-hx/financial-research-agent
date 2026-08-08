# 02 架构与Run生命周期

## 1. 设计目标

目标不是让模型“自由地做研究”，而是让模型只在理解、受约束规划和报告表达三个位置发挥作用。所有会接触真实数据、消耗预算或改变运行状态的动作，都由程序控制。

系统要同时满足：

- 可恢复：进程或数据库短暂故障后可以从合法 Checkpoint 继续；
- 可约束：模型不能绕过工具、权限、预算和校验；
- 可审计：每个节点、调用、Evidence 和终态都能关联到 Run；
- 可解释：失败能区分数据缺口、Provider 网络、工具失败、策略拒绝和报告校验失败；
- 可替换：模型 Provider、工具实现和编排框架边界清晰。

## 2. 分层架构

### 接入层

FastAPI 对外提供同步兼容接口和异步 Job API。它只负责鉴权上下文、请求校验、幂等创建、状态查询和事件输出，不在 API 进程中持有运行状态。

### LangChain基础接口层

LangChain统一可被企业生态识别的Agent开发接口：

- ChatModel、Prompt与Runnable；
- Pydantic Structured Output；
- StructuredTool与ToolMessage artifact；
- BaseRetriever与Document；
- Context Runnable和LangGraph Store兼容入口。

这些接口只负责标准化对象与调用协议，不负责金融权限和数据正确性。

### Harness控制层

控制层是项目的核心差异化能力：

- Skill Registry 决定适用的版本化研究流程；
- Policy Engine 决定当前用户、Skill 和参数是否允许调用某个工具；
- Budget Ledger 在调用前 Reserve、调用后 Commit/Release；
- Memory Manager 负责隔离、TTL、删除和受控写入；
- Context Builder 决定每个模型节点能看到什么；
- Completion Checker 决定 Run 是否真的可以成功结束。

### LangGraph运行层

LangGraph 只承担通用状态运行：

- 执行显式 StateGraph；
- 保存 Checkpoint 和 Pending Writes；
- 支持 Interrupt、Resume 和流式状态；
- 从最近合法节点继续；
- 管理 Thread 和 Checkpoint 历史。

业务权限、费用、Evidence 正确性和 Memory 规则不交给 LangGraph。

### Gateway与领域层

所有模型和工具调用分别进入 Model Gateway 与 Tool Gateway。领域层继续使用 Pydantic 模型表达：

```text
ResearchRequest
QuerySpec
AnalysisPlan / AnalysisTask
ToolResult
Evidence / SourceReference
ResearchReport / ReportClaim
ValidationResult
ResearchRunResult
```

### 存储层

- PostgreSQL：Checkpoint、Run/Event/Attempt/Call、Skill、Budget、Memory 和终态；
- Iceberg：日线、财务指标和数据批次元数据；
- Milvus：研报 Chunk 向量索引与过滤检索；
- Artifact Volume：评测原始响应、报告、审计与导出文件。

## 3. 正式StateGraph

```text
START
  ↓
interpret
  ↓
select_skill
  ↓
build_planner_context
  ↓
plan
  ↓
validate_plan
  ↓
policy_and_budget_check
  ↓
execute_tools ── 并行但受依赖、白名单和预算限制
  ↓
build_evidence
  ↓
build_report_context
  ↓
generate_report
  ↓
validate_report
  ├── pass ───────────────────────┐
  └── fail且允许一次修订 → revise_report
                              ↓
                       validate_revision
                              │
  ┌───────────────────────────┘
  ▼
completion_check
  ↓
finalize
  ↓
END
```

条件边读取的是结构化状态、Policy、Budget 和 Validator 结果，模型不能指定任意下一节点。

## 4. 一次Run的完整生命周期

### 4.1 创建

客户端提交问题和 Idempotency Key。API 先创建业务 Run，再由 Worker 使用同一 `run_id/thread_id` 运行图。重复 Key 返回原 Run，不创建两个任务。

### 4.2 理解与Skill选择

Interpreter 把自然语言转换为 `QuerySpec`。当前首批七个Skill使用确定性
Intent/Dimension过滤，不增加模型调用；程序检查状态、版本、权限交集和冲突。
若目录规模扩大，可以在规则候选集内增加结构化模型排序，最终程序校验不变。

### 4.3 规划

Planner通过LangChain Structured Output生成`AnalysisPlan`，且只能从Tool Gateway
暴露的Schema中选择任务。规则Planner是网络故障时的显式降级路径。Plan Validator检查：

- 股票、日期和 Intent 不得被模型改写；
- Tool 必须在 Registry 与 Skill 白名单中；
- 依赖图无环；
- 任务数、时间范围和参数满足预算与策略；
- 综合研究必须包含规定的取数和 Evidence 路径。

### 4.4 执行与Evidence

每个Tool Call在执行前写幂等记录和预算Reserve。Financial Tool包装为LangChain
StructuredTool，但调用仍进入Tool Gateway；结果通过ToolMessage artifact携带，
Evidence Builder再把成功结果转换成带当前Run ID的Evidence。

Evidence 至少包含：

- `evidence_id`；
- 类型、主体和陈述；
- 结构化数字或文本；
- Source Locator；
- Snapshot/观察时间；
- 研报页码、机构等来源属性。

### 4.5 报告与校验

Report Context 只包含 Query、允许的 Evidence 和必要的格式约束。模型生成 ResearchReport 后，Validator 逐 Claim 检查主体、日期、数字和 Evidence ID。一次修订仍失败则进入 `validation_failed`，不能被 Completion Checker 视为成功。

### 4.6 完成

Completion Checker 统一检查：

- Graph 到达合法完成路径；
- 必需 Evidence 完整；
- Validator 通过；
- Budget 没有超限或未核销预留；
- Artifact 已写入；
- 没有冲突终态。

只有全部通过，才写唯一 `terminal_results`。

## 5. 故障与恢复

外部调用使用业务幂等键、输入 Hash 和租约。Worker 退出时：

```text
Worker退出
  → PostgreSQL保留Checkpoint与调用记录
  → Lease过期后新Worker领取
  → 从原thread_id恢复
  → 已完成节点和调用复用
  → 未完成节点继续
  → Completion Checker
  → 唯一终态
```

Cancel 只在节点安全边界生效，不强制终止正在进行的外部请求。Resume 只允许合法状态，完成态重复 Resume 直接返回已保存结果。

## 6. 为什么不使用通用ReAct循环

通用 ReAct 适合探索式工具调用，但本项目要求：

- 工具轨迹可预测；
- 金融数字和引用必须可校验；
- 调用预算有限；
- 错误不能通过无限 Replan 掩盖；
- 面试时能清楚说明每个节点的职责。

因此当前正式路径保持显式图和`Replan=0`，优先保证单次计划的正确性、恢复和治理。
