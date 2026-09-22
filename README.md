# Morshan：企业财务风险分析 Agent

Morshan 是一个面向企业财务风险监测与证据复核的只读 Agent 系统。系统以公司、报告期和分析截止日为
基本单元，从财务事实中生成风险候选，再由 Supervisor 按任务复杂度组织专业子 Agent，完成检索、计算、
反证、引用和报告校验。

项目以 **LangChain** 统一模型、结构化输出和 Tool 接口，以 **LangGraph** 保存运行状态并执行动态编排；
在框架之上增加金融数据湖、Point-in-Time 数据边界、版本化 Skill、Evidence、上下文与记忆、确定性校验、
异步任务和多用户共享分析。模型不能直接访问数据库，也不能执行任意 SQL、Shell 或 Python。

当前默认模型为 DeepSeek V4.1 Flash，API 模型名为 `deepseek-flash`。

## 任务边界

系统集中处理四类紧密关联的风险：

1. 偿债与流动性；
2. 盈利质量与现金流；
3. 资产质量与减值；
4. 财务披露与审计异常。

行情、因子、公告、新闻和研报只作为辅助证据。系统不执行交易、不生成下单指令、不支持分钟级实时行情，
也不把模型生成文本直接写成可信长期事实。

输出的 `RiskAssessmentArtifact` 绑定主体、报告期、分析截止日、数据快照、风险状态、支持与反向证据、
计算口径、缺失数据和替代解释。证据不足时返回 `INSUFFICIENT_DATA`，不会把缺失值填成零或强行生成结论。

## 系统架构

```text
Client
  │
  ▼
Spring Gateway（可选外部入口）
  ├─ API key / JWT → tenant-user 身份
  ├─ Redis token bucket / fail-closed
  └─ WebFlux API 与 SSE 转发
  │
  ▼
FastAPI Job API ── 创建 / 查询 / 取消 / 恢复 / Trace / SSE
  │
  ▼
PostgreSQL Queue ── 幂等键 / 公平领取 / 租约 / 心跳 / 终态
  │
  ▼
Python Worker
  └─ LangGraph StateGraph
      ├─ 构建 QuerySpec 与 Point-in-Time 边界
      ├─ Supervisor 选择单 Agent、固定团队或动态团队
      ├─ Skill 选择与受控 Tool 执行
      ├─ Evidence、反证与上下文构建
      ├─ Evaluator 与最多一次定向修复
      └─ 写入报告、Scorecard、事件和公共分析产物
  │
  ├─ Iceberg / Spark：财务事实、特征、风险候选与批处理
  ├─ Milvus：本地研报向量检索
  ├─ Elasticsearch：网络文档检索与版本管理
  ├─ PostgreSQL：Job、Checkpoint、审计、Memory 和最终事实
  └─ Redis：限流、single-flight 和可重建热状态
```

Spring与Redis不是Agent逻辑的必要运行前提。开发环境可以直接调用FastAPI；对外部署时，Spring负责认证、
限流和身份头清洗，Python负责Agent、Tool和报告逻辑。PostgreSQL始终是任务、租约和终态的事实来源，
Redis故障不会删除已经完成的任务或报告。

## 核心组件

### 数据湖与 Point-in-Time 数据

- AkShare负责日线与财务数据采集，Raw层保留来源、批次、观察时间和质量状态；
- PyArrow完成字段和类型标准化，PyIceberg管理表、Snapshot和批量提交；
- Spark执行股票池批处理、窗口计算和增量聚合；
- 财务事实同时保留来源发布时间和系统观察时间，避免使用分析截止日之后的信息；
- 确定性规则先生成偿债、盈利质量、资产质量和披露审计候选，再交给Agent复核。

### LangChain、LangGraph 与受控执行

- LangChain ChatModel、Structured Output、StructuredTool和Retriever统一主流Agent接口；
- LangGraph负责状态图、条件路由、动态fan-out、Checkpoint和可恢复执行；
- Harness限制Tool白名单、参数、预算、超时、重试、取消和终态写入；
- Policy Engine与Budget Ledger限制模型调用、Tool尝试、Evidence数量和报告修订次数；
- 动态多Agent不是全局默认，只在公开Benchmark证明有增量的题型启用。

### Skill、Tool 与 Evidence

- Skill声明适用意图、允许工具、预算和工作流版本，不能绕过Tool Gateway；
- 行情、财务、因子、事件、研报、网络检索和确定性计算均封装为Pydantic类型化Tool；
- Evidence统一保存主体、声明、来源、数据日期、快照和原文定位；
- Evaluator检查证据支持、数值、单位、时间口径和冲突；
- 模型格式或引用错误最多执行一次定向修复，确定性事实不会交给模型随意改写。

### 检索、上下文与记忆

- PyMuPDF解析研报并保留文档、页码、机构和版本元数据；
- BGE中文Embedding与Milvus提供向量召回，关键词检索补充精确实体匹配；
- Elasticsearch保存可选网络文档，支持内容版本、时间和主体过滤；
- Context Builder按节点预算选择问题、计划、Tool结果、记忆和Evidence，并记录上下文清单；
- 长上下文使用确定性裁剪与摘要；这减少输入Token，但不等同于直接管理模型服务端KV Cache；
- 会话记忆和用户偏好按tenant/user/session隔离，原始Evidence不因压缩而被覆盖。

### 查询、分析与输出分离

- `RetrievalSnapshot`保存取数结果和数据水位；
- `RiskAssessmentArtifact`保存无用户身份的公共分析及依赖版本；
- `UserReport`绑定tenant/user，不进入跨用户公共缓存；
- 相同公司、报告期和数据版本使用single-flight合并并发工作；
- 数据更新只使受影响的公共分析失效，不做全量缓存清空；
- Redis保存短TTL热索引，PostgreSQL保存最终版本和single-flight事实。

### 多用户与故障恢复

- PostgreSQL队列支持全局、租户和用户配额，以及交互任务优先和租户公平领取；
- Worker通过租约、心跳和幂等终态写入实现进程退出后的任务接管；
- Spring Security从API key或JWT建立可信身份，并删除外部伪造的tenant/user头；
- Redis限流异常时，昂贵的新分析请求明确失败关闭；状态查询和SSE仍可回源PostgreSQL；
- SSE支持`Last-Event-ID`断点续传，完成事件只写入一次。

## 评测设计与实测结果

Agent效果只在公开标注数据上评价，自有公司数据只用于业务流程、并发、缓存、增量计算和部署演示。

### 公开 Benchmark

- **FinanceBench**：复杂子集上动态团队没有改善45%的数值准确率和62.5%的Evidence Recall，且成本更高，
  因此保留单Agent；
- **FinQA**：20道复杂题中，单Agent、固定团队和动态团队的官方Execution Accuracy分别为30%、50%、55%，
  Program Accuracy分别为20%、35%、40%；综合质量和成本后固定团队作为默认；
- **TAT-QA**：20道复杂题中，动态团队相对单Agent将EM从30%提升至60%、F1从37.90提升至63.35，
  只在复杂算术和table-text类型启用；
- **V4FinBench**：官方公司分组五折中，固定参数LightGBM相对逻辑回归的PR-AUC、F1和
  Recall@Precision 5%分别提升66.7%、42.9%和81.7%，同时保留校准退化结论。

这些结果来自冻结题集或官方split。失败按0计入，不通过删题、无限重试或自建标签美化结果。

### 工程 Gate

- 5个历史截止日生成126,880条PIT特征和39,040条风险候选，未来数据泄漏和业务主键重复均为0；
- 50用户、250次交叉查询只执行20次唯一公司分析，热态新增分析0次；两家公司更新只重算两家；
- Spark 4.2处理500万行合成数据，5%公司增量使扫描行和Iceberg计划文件均减少95%；
- Kind三逻辑节点完成真实部署；Worker退出后任务接管、Redis降级、Gateway滚动更新/回滚、SSE续传和
  多租户隔离均通过；
- Gateway滚动更新期间80/80请求返回200，跨租户读取、任务丢失和重复终态均为0。

本地延迟只用于诊断，不作为生产SLA或简历性能数字。详细结论见
[第五阶段最终Gate](docs/phase5-financial-risk-benchmark/steps/03-replay-performance-delivery/FINAL_GATE.md)。

## 快速启动

### 配置

```bash
cp .env.example .env
```

至少配置：

```dotenv
MODEL_PROVIDER=openai_compatible
MODEL_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-flash
MODEL_API_KEY=<private-key>
IDENTITY_MODE=api_key
AGENT_API_KEY=<internal-api-key>
```

不要提交`.env`、模型Key、SSH私钥或本机绝对路径。历史对话中出现过的Key应在Provider控制台轮换。

### Docker Compose

启动Agent API、Worker、PostgreSQL和研报检索依赖：

```bash
docker compose --profile harness up -d \
  postgres etcd milvus db-migrate job-api job-worker
```

启动可选Spring Gateway与Redis接入层：

```bash
docker compose --profile harness --profile concurrency --profile gateway \
  up -d redis backend-gateway
```

FastAPI开发入口为`http://localhost:8002`，Gateway入口为`http://localhost:8080/api/v1`。

仅暴露Gateway的端口边界：

```bash
docker compose -f docker-compose.yml -f docker-compose.gateway.yml \
  --profile harness --profile concurrency --profile gateway up -d
```

### API 示例

```bash
curl -X POST http://localhost:8080/api/v1/runs \
  -H "Authorization: Bearer $GATEWAY_EXTERNAL_API_KEY" \
  -H "Idempotency-Key: risk-600519-001" \
  -H "Content-Type: application/json" \
  --data '{"question":"分析600519最近报告期的盈利质量和偿债风险"}'
```

```bash
curl -H "Authorization: Bearer $GATEWAY_EXTERNAL_API_KEY" \
  http://localhost:8080/api/v1/runs/<run_id>
```

```bash
curl -N -H "Authorization: Bearer $GATEWAY_EXTERNAL_API_KEY" \
  -H "Last-Event-ID: 0" \
  http://localhost:8080/api/v1/runs/<run_id>/events
```

### 数据任务

```bash
docker compose --profile ingestion run --rm data-bootstrap
docker compose --profile ingestion run --rm market-ingest
docker compose --profile ingestion run --rm financial-ingest
docker compose --profile analysis run --rm factor-batch
```

```bash
docker compose --profile rag run --rm rag-index \
  python -m financial_research_agent.rag.indexer --mode incremental
```

默认研报目录`./data/reports`以只读方式挂载；其他本机资料路径只能写在未提交的`.env`中。

## Kubernetes

`deploy/k8s/base`提供通用Kustomize Base，`deploy/k8s/kind`提供本地三逻辑节点Overlay。包含：

- API、Worker和Gateway Deployment；
- 数据库迁移Job和湖命名空间初始化CronJob；
- requests/limits、readiness/liveness、HPA、PDB和NetworkPolicy；
- 非root、只读根文件系统、最小Linux capability与独立ServiceAccount；
- Secret与ConfigMap边界，以及共享湖PVC。

本地运行步骤见[Kubernetes运行手册](docs/phase5-financial-risk-benchmark/steps/03-replay-performance-delivery/K8S_RUNBOOK.md)，
实测故障恢复见[Kubernetes运行报告](docs/phase5-financial-risk-benchmark/steps/03-replay-performance-delivery/K8S_RUNTIME_REPORT.md)。

## 项目结构

```text
financial-research-agent/
├── backend-gateway/                 # Java / Spring外部接入层
├── deploy/k8s/                      # Kubernetes Base与Kind Overlay
├── migrations/                      # PostgreSQL / Alembic迁移
├── scripts/                         # 可复现Gate与运维脚本
├── src/financial_research_agent/
│   ├── financial/                   # 财务采集、标准化与质量审计
│   ├── risk/                        # PIT特征、风险Agent与公开Benchmark
│   ├── orchestration/               # LangGraph、Planner、Executor
│   ├── governance/                  # Policy、预算与完成条件
│   ├── skills/                      # 版本化Skill
│   ├── tools/                       # 类型化只读Tool
│   ├── rag/                         # 研报解析与混合检索
│   ├── retrieval/                   # Snapshot、Artifact与single-flight
│   ├── memory/                      # 记忆、上下文与压缩
│   ├── reporting/                   # 报告、事实抽取与校验
│   ├── jobs/                        # Job Queue、租约与Worker
│   └── shared_state/                # Redis热状态适配
├── tests/
├── docker-compose.yml
└── docker-compose.gateway.yml
```

## 文档入口

- [第五阶段：企业财务风险与公开Benchmark](docs/phase5-financial-risk-benchmark/README.md)
- [Agent岗位交付说明](docs/phase5-financial-risk-benchmark/steps/03-replay-performance-delivery/DELIVERY_AGENT.md)
- [数据分析岗位交付说明](docs/phase5-financial-risk-benchmark/steps/03-replay-performance-delivery/DELIVERY_DATA_ANALYSIS.md)
- [数据开发岗位交付说明](docs/phase5-financial-risk-benchmark/steps/03-replay-performance-delivery/DELIVERY_DATA_ENGINEERING.md)
- [项目完整设计文档](docs/project-introduction/README.md)
- [Spring Gateway运行手册](docs/phase4-agent-optimization/steps/08-spring-redis-concurrency/RUNBOOK_08_2.md)
- [私有仓库发布前审计](docs/RELEASE_AUDIT_20260922.md)

## 已知限制

- 财务数据源仍需持续改善首次披露时间、修订版本和事件覆盖；
- 网络检索只有配置合法Provider后才启用，未配置时明确返回不可用；
- Context Builder管理输入内容和Token预算，但不直接控制第三方模型服务端KV Cache；
- MCP目前只保留Tool Schema兼容边界，没有实现独立MCP Server；
- 本地Kind三节点共享一台Mac；HPA未在metrics-server下做动态扩缩容验证；
- 本地RWO湖PVC、PostgreSQL和Redis不能直接作为云上生产存储方案；
- Kubernetes CronJob目前只验证湖命名空间初始化，尚未接入完整定时增量采集；
- 镜像漏洞/SBOM Gate、云上容量测试和多可用区部署仍属于生产化工作。

仓库保持私有，除非所有者明确决定改变可见性。
