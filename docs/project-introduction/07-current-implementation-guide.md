# 07 当前实现组件与运行方式

## 1. 当前完成态

截至第三阶段集中验收，系统已经是以LangChain/LangGraph为基础、带受控执行、
事务预算、隔离Memory和异步Worker的股票投研Agent：

- LangChain统一ChatModel/Runnable、Structured Output、StructuredTool、
  ToolMessage、BaseRetriever和Document接口；
- LangGraph执行显式状态图；
- DeepSeek OpenAI-compatible接口承担规划和报告生成；
- 模型只能选择受控Tool，不能直接访问数据库或执行代码；
- Iceberg提供日线与财务数据，Milvus提供研报检索；
- Evidence和报告Validator保证结论可追溯；
- PostgreSQL保存Checkpoint、调用审计、终态和Skill版本快照；
- Model/Tool Gateway统一执行Policy、预算、重试、Usage和版本审计；
- Completion Checker阻止Evidence、报告、Validator或预算不一致的成功终态；
- Docker Compose部署应用与基础设施；
- 七个版本化Skill已接入正式Run。
- Session/Preference Memory、Context Manifest和Evidence保护压缩已接入正式Run；
- Job API、SSE、Cancel/Resume、PostgreSQL Lease和双Worker已实现；
- 20题Regression、30题Holdout、10题×3稳定性和故障/安全评测已完成；
- Docker备份恢复、同步/异步烟雾Run和最终交付文档已完成。

## 2. 一次请求的实际链路

```text
POST /analyze
  → interpret
  → select_skill
  → initialize_governance
  → plan
  → validate_plan
  → execute_tools
  → build_evidence
  → generate_report
  → validate_report
  ├─ 通过 → completion_check → finalize
  └─ 失败且可修订 → revise_report → validate_revision
                                     → completion_check → finalize
```

LangChain负责标准接口，LangGraph负责节点、状态转移和Checkpoint。股票池、
工具白名单、Skill权限、Evidence与报告正确性均由项目金融增强层负责。

## 3. 组件与实现

### 3.1 API与配置

- FastAPI提供`/health`、`/tools`和`/analyze`；
- Pydantic校验请求和结构化响应；
- API返回`selected_skills`与`skill_selection_reason`；
- API同时返回Policy版本、Budget Snapshot和Completion结果；
- `Settings`从`.env`读取模型、数据库、资源上限和`SKILLS_ENABLED`；
- 日志会关联Request ID、Run ID、工具状态和耗时，不输出API Key。

主要代码：`api.py`、`api_models.py`、`config.py`。

### 3.2 LangChain基础接口

- `LangChainModelProvider`用`ChatPromptTemplate + ChatOpenAI + Structured Output`
  生成`AnalysisPlan`和`ResearchReport`；
- DeepSeek JSON模式显式携带Pydantic Schema，解析失败会进入受预算约束的重试；
- 每个Financial Tool可包装为`StructuredTool`，但执行仍委托`ToolGateway`；
- Tool结果以`ToolMessage artifact`携带，Evidence可从Artifact确定性重建；
- Milvus研报检索包装为`BaseRetriever`并输出带来源元数据的`Document`；
- Context Builder提供Runnable入口，Memory Manager提供LangGraph Store兼容入口。

主要代码：`integrations/langchain/`、`providers/model.py`。

### 3.3 LangGraph运行时

- `ResearchGraphState`只保存JSON安全数据；
- 节点由`StateGraph`显式连接，模型不能选择任意下一步；
- 失败边统一进入`completion_check`，终态只能写一次；
- PostgreSQL模式使用`AsyncPostgresSaver`；
- `run_id`同时作为`thread_id`，Resume读取同一Checkpoint历史；
- Checkpoint Serializer关闭Pickle fallback、限制大小，并支持可选AES。

主要代码：`orchestration/langgraph_runtime.py`、
`persistence/checkpoint.py`。

### 3.4 问题理解与规划

- `QueryInterpreter`确定性提取股票、日期、Intent和Dimension；
- Structured Planner调用DeepSeek输出符合`AnalysisPlan` Schema的JSON；
- Provider失败时允许明确的规则Planner降级；
- Plan Validator再次检查股票、日期、Tool、参数、依赖图和任务上限；
- Skill Validator随后检查Effective Tool与更严格的调用上限。

模型可以提出计划，但没有执行权限；只有通过两层校验的任务才会进入Tool执行。

主要代码：`interpreter.py`、`planner.py`、`validator.py`、
`providers/model.py`。

### 3.5 Skill Registry

Skill由Pydantic声明：

```text
身份与版本
+ ACTIVE状态
+ Intent/Dimension触发
+ Allowed Tools
+ Required Evidence
+ Workflow Constraints
+ Context/Validator/Budget Profile引用
+ 冲突关系
+ Content Checksum
```

当前七个内置Skill覆盖行情、财务增长、盈利能力、综合研究、研报审核、简版报告和
风险优先报告。选择是确定性的；多Skill的Tool取交集、上限取更严格值、Evidence
要求合并、冲突直接拒绝。

生命周期为`DRAFT → REVIEWED → ACTIVE → DEPRECATED`。发布只能通过显式CLI/
Store操作，模型运行路径没有激活权限。每次Run把Skill版本、Checksum和约束复制到
`run_skill_snapshots`，因此后续发布不会改变历史Run或恢复中的Run。

主要代码：`skills/models.py`、`skills/registry.py`、`skills/store.py`、
`skills/catalog.json`、`skills/cli.py`。

### 3.6 Tool与数据层

正式Tool Registry当前注册：

| Tool | 实现 |
|---|---|
| `market_query` | 读取Iceberg日线，返回实际日期、行数和Snapshot |
| `indicator_calculator` | 基于日线确定性计算收益、回撤、均线等指标 |
| `financial_query` | 读取Iceberg财务表和派生指标 |
| `report_search` | 在Milvus按股票过滤并检索研报Chunk |

Tool全部是只读的，有Pydantic输入、超时、股票池/日期/行数限制和结构化错误。
Repository负责Iceberg/Milvus访问，Agent节点不直接访问存储。

### 3.7 Gateway、Policy与Budget

正式LangGraph运行时将所有模型和Tool调用收口：

- Model Gateway只允许规划、报告生成和报告修订；
- Tool Gateway只允许Registry与当前Skill共同允许的只读Tool；
- Policy Engine在每次调用及每次重试前检查操作、数据域和参数范围；
- PostgreSQL Budget Ledger通过`Reserve → Commit/Release`防止并发超限；
- 逻辑调用与实际Attempt分别计数，失败重试仍占Attempt预算；
- DeepSeek Usage记录输入、输出、缓存Token和估算费用；
- Provider、Gateway、Policy、Skill和Tool版本均能关联到一次Run；
- 异常文本经过收敛，不持久化API Key、完整Prompt或隐藏推理。

Run结束前，Completion Checker检查Evidence、报告、Validator和未结算预算。受控失败
可以成为一致的终态，但不能伪装成成功。

主要代码：`governance/`、`providers/model.py`、
`orchestration/langgraph_runtime.py`。

### 3.8 Evidence与报告

Tool成功结果先进入`EvidenceBuilder`，得到带`evidence_id`、主体、结构化数据、
Source Locator和观察时间的事实单元。Skill的必需Evidence在报告生成前检查。

DeepSeek仅根据当前Evidence生成报告。Report Validator逐Claim验证：

- Evidence ID真实存在且属于当前Run；
- 股票和日期与Query一致；
- 关键数字能由引用Evidence支持；
- 研报观点有机构、页码和来源；
- 报告不能在校验失败时伪装成成功。

当前允许一次受控修订，第二次仍失败即`validation_failed`。

### 3.9 PostgreSQL业务持久化

LangGraph Checkpoint表由LangGraph自身管理；业务表由Alembic管理：

- Run、Event、Node Attempt；
- Model Call、Tool Call及租约/幂等键；
- Artifact Ref与唯一Terminal Result；
- Skill、Skill Version、Review、Activation；
- Run Skill Snapshot。
- Policy Decision、Run Budget、Budget Entry；
- Model/Tool Call上的Gateway、Policy、Budget和Attempt/Usage字段。

已完成调用结果可复用，租约过期后新Worker可接管，重复终态或输入Hash不一致会被
拒绝。

### 3.10 Docker部署

`docker-compose.yml`包含：

- `postgres`：Checkpoint与业务持久化；
- `etcd + milvus`：研报向量检索；
- `db-migrate`：应用启动前执行Alembic；
- `app`：正式LangChain/LangGraph同步API；
- `job-api + job-worker`：异步任务、SSE和Worker执行；
- 采集、Bootstrap和索引服务使用独立Profile按需运行。

主应用使用持久卷保存Iceberg、Milvus、PostgreSQL、模型缓存和Artifact。容器有
健康检查和内存限制；密钥仅通过`.env`注入，不写入镜像。

## 4. 当前验证结果

- 本地集中回归：122项通过，19项PostgreSQL可选项跳过；
- 最终镜像全量回归：141项通过，包含PostgreSQL集成项；
- PostgreSQL迁移版本：`20260726_0005`；
- 七个内置Skill：7 ACTIVE、7 Review、7 Activation；
- 真实DeepSeek + LangGraph + Tool + Evidence + Report链路：通过；
- Step05真实V4 Pro Run：2次Model、1次Tool、6177 Token、0个开放Reservation；
- Policy/Budget/Gateway/Completion正式路径：通过；
- Regression / V4 Pro：20/20；
- Holdout / V4 Pro：29/30，96.67%；
- Intent、Skill、Tool、参数、Evidence覆盖、引用和Budget闭合：100%；
- Harness 10题×3：Skill、Tool、Evidence、Evidence数字和报告结构稳定性均100%；
- Context Compression估算Token从13,523降至260，Evidence保护通过；
- PostgreSQL 14.7 MB备份成功恢复到临时库，Alembic与26张表验证通过；
- Step09真实异步Job：13节点、2次Model、1次Tool、34条Event、0开放Reservation。
- Step03真实异步Job：LangChain结构化规划与报告、两项Tool、Validator、
  Completion和35条SSE Event完整通过；
- Step03 Flash回归首次19/20（95%），指标窗口标签规则修复后失败题复测通过；
- Step03首次Flash整套运行P50 8.436秒、P95 14.143秒，Evidence与引用保护100%。

## 5. 面试时如何概括

> 我以LangChain统一ChatModel、StructuredTool、Retriever和结构化输出接口，
> 用LangGraph管理显式状态图和PostgreSQL Checkpoint，并在标准框架上扩展金融领域
> 的版本化Skill、Model/Tool Gateway、Policy Engine和事务预算账本。模型负责
> 结构化规划与报告，程序负责只读权限、幂等恢复、重试预算、Usage审计和逐Claim
> 数字/引用校验。

如果被问“是否自研Agent框架”，更准确的回答是：标准Agent接口使用LangChain，
编排与Checkpoint使用LangGraph；项目实现的是金融领域增强与治理层，没有重复实现
通用Agent框架，也没有把金融数据正确性完全交给框架。
