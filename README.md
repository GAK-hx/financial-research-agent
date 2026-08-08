# Financial Research Agent

这是 `financial-agent` 的独立后继项目。项目以LangChain统一模型、结构化输出、
Tool、Message和Retriever接口，以LangGraph承载状态化编排与PostgreSQL Checkpoint；
在标准框架之上保留金融领域的Gateway、Policy/Budget、Evidence、Memory/Context、
版本化Skill和分档报告校验。第四阶段已补齐多租户身份边界、公平队列、背压、资源治理和演示交付。

第一阶段完整技术总结见[docs/phase1/TECHNICAL_SUMMARY.md](docs/phase1/TECHNICAL_SUMMARY.md)，第二阶段入口见[docs/phase2/README.md](docs/phase2/README.md)和[docs/phase2/ARCHITECTURE.md](docs/phase2/ARCHITECTURE.md)。
面向新读者整理的独立项目介绍见
[docs/project-introduction/README.md](docs/project-introduction/README.md)。
教程复盘、目标架构、四步优化实现与最终 Gate 见
[docs/phase4-agent-optimization/README.md](docs/phase4-agent-optimization/README.md)。

核心链路：

```text
AkShare 日线 → 校验/标准化 → PyIceberg → Market/Indicator Tools ─┐
研报 PDF → PyMuPDF → BGE → Milvus → Report Search Tool ──────────┤
用户问题 → LangChain Structured Output → LangGraph → Tool Gateway ─┤
                              → Evidence → Validated Report ──────────┘
```

设计边界：

- 正式证据只使用真实日线、财务数据和研报；
- Kafka/Flink Mock 链路不进入本项目第一步运行时；
- 模型不能访问数据库、执行任意 SQL 或运行任意 Python；
- 模型只能通过受控Tool读取真实数据；
- 当前只读，不执行交易，不支持分钟或实时行情。

## 目录

```text
financial-research-agent/
├── STEP1_PLAN.md
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── .env.example
├── data/reports/.gitkeep
├── lake/.gitkeep
├── tests/
└── src/financial_research_agent/
    ├── api.py
    ├── config.py
    ├── domain/models.py
    ├── orchestration/registry.py
    ├── orchestration/executor.py
    ├── repositories/iceberg.py
    └── tools/
```

## 启动基础服务

```bash
cp .env.example .env
docker compose up -d etcd milvus
```

默认只读挂载本项目的研报目录：

```text
./data/reports → /data/reports:ro
```

如需临时复用旧项目资料，可仅在本地`.env`设置
`REPORTS_HOST_DIR=../financial-agent/data/reports`；该机器路径不会进入仓库。

## 当前实现状态

- 已建立强类型领域模型；
- 已建立只读 Tool Registry；
- 已建立带依赖检查和并发上限的 Executor；
- 已建立 Iceberg Repository 配置；
- 已提供健康检查 API；
- 日线与财务采集、RAG、模型Planner、报告生成、确定性校验和API闭环均已实现；
- 已使用DeepSeek Flash完成四类真实端到端补验；
- 默认模型接口为LangChain ChatModel/Runnable，正式状态运行时为LangGraph；
- 已实现PostgreSQL Checkpoint、版本化Skill Registry和LangGraph Store兼容Memory；
- 第二阶段九步工程实现和Gate 08评测已完成；
- 第三阶段LangChain基础框架调整和集中验收已完成；
- 第四阶段已实现可信身份、三级准入/运行配额、租户公平调度、有界Worker和Provider限流；
- 冻结并发基准完成91个Run且关键不变量均为0，Flash Planner并发2/2；
- 5个并发用户对15支去重股票完成真实Flash查询，允许热点股票重复请求，5/5通过；
- 完整Docker/PostgreSQL回归177/177通过，当前容量结论约为单实例30个同时提交的研究请求；
- 已提供`/demo`薄界面；MCP仅保留Tool Schema兼容边界，尚未实现协议服务器；
- 仍可通过`AGENT_FRAMEWORK=native`和`ORCHESTRATION_RUNTIME=legacy`显式回退，
  但不再维护第二套默认生产入口；
- 最新验收、失败记录和演示见
  `docs/phase4-agent-optimization/steps/05-private-publish-readiness/GATE_REPORT.md`。

## LangChain/LangGraph正式运行

默认`app`服务使用LangChain接口和LangGraph运行时，端口为8000：

```bash
docker compose --profile harness up --build -d app job-api job-worker
curl http://localhost:8000/health
curl http://localhost:8002/health
```

该服务通过LangChain Structured Output生成计划和报告，通过StructuredTool、
ToolMessage artifact与BaseRetriever接入现有能力；所有实际调用仍经过Gateway。
响应包含`selected_skills`和`skill_selection_reason`审计字段。PostgreSQL保存
LangGraph Checkpoint，
并由Alembic管理独立的Run、Event、
Node Attempt、Model/Tool Call和Terminal Result业务表：

```bash
docker compose --profile harness up --build -d app
docker compose exec app \
  python -m financial_research_agent.persistence.audit inspect
```

Checkpoint加密默认关闭；启用时需在`.env`配置
`CHECKPOINT_ENCRYPTION_ENABLED=true`以及16、24或32字节的
`CHECKPOINT_AES_KEY`。完整恢复流程和故障边界见
`docs/phase2/steps/03-postgres-checkpoint/RUNBOOK.md`。

Skill目录、发布流程和选择规则见
`docs/phase2/steps/04-skill-registry/SKILL_CATALOG.md`、
`PUBLISHING.md`和`SELECTION_DESIGN.md`。

异步Job API与Worker：

```bash
docker compose --profile harness up -d job-api job-worker
curl http://localhost:8002/health
```

完整部署、备份恢复、Memory清理和演示流程见
`docs/phase2/steps/09-acceptance/OPERATIONS_RUNBOOK.md`与
`DEMO_SCRIPT.md`。

## 初始化与日线采集

```bash
docker compose --profile ingestion run --rm data-bootstrap
docker compose --profile ingestion run --rm market-ingest
docker compose --profile ingestion run --rm market-ingest \
  python -m financial_research_agent.market.audit
docker compose --profile ingestion run --rm data-bootstrap \
  python -m financial_research_agent.tools.demo
docker compose --profile ingestion run --rm financial-ingest
docker compose --profile ingestion run --rm financial-ingest \
  python -m financial_research_agent.financial.audit
docker compose --profile ingestion run --rm data-bootstrap \
  python -m financial_research_agent.tools.financial_demo
```

日线任务优先使用AkShare `stock_zh_a_hist`，受限时回退到`stock_zh_a_hist_tx`；默认示例
股票池为600519、300750，可通过环境变量扩展，本次验收已覆盖20支股票，口径为前复权。
Raw响应、质量报告、批次元数据和Iceberg数据均保存在`lake_data` Docker卷中。

财务任务保存三张完整Raw报表，并写入三张最小Curated表和`financial.metrics`。
来源返回的历史公告日期不能视为可靠首次披露日，因此Financial Tool不支持时点回测。

## 研报索引与检索审计

RAG依赖只安装在`rag-index`镜像中，BGE模型缓存使用独立Docker卷，避免每次运行重复下载：

```bash
docker compose up -d etcd milvus
docker compose --profile rag build rag-index
docker compose --profile rag run --rm rag-index \
  python -m financial_research_agent.rag.indexer --mode rebuild
docker compose --profile rag run --rm rag-index \
  python -m financial_research_agent.rag.audit
```

`--mode skip`保留已有Collection且不重复写入；`--mode rebuild`才会显式删除并重建
`research_reports_v1`。Report Search强制按股票代码过滤，单次Top K范围为1～10。

生产请求使用`Asia/Shanghai`真实当前日期。`EVALUATION_REFERENCE_DATE`只允许在冻结评测命令
中显式设置；API响应中的`execution_metadata`会记录执行时间、业务参考日期、时区和Evidence
可确定的数据截止日。`semantic_alignment`记录原问题到QuerySpec的实体、分析域和时间粒度检查。

## Agent编排演示

未配置模型时，编排服务会明确使用规则Planner；模型配置完成后仍必须通过同一Plan Validator和工具白名单：

```bash
docker compose --profile rag run --rm rag-index \
  python -m financial_research_agent.orchestration.demo

docker compose --profile rag run --rm rag-index \
  python -m financial_research_agent.orchestration.demo \
  '分析宁德时代最近三年的营收、利润和盈利能力'
```

编排结果包含`run_id`、`QuerySpec`、任务DAG、逐工具状态、阶段耗时和当前Run的Evidence，不在此步骤生成最终研究报告。

## 报告边界与校验审计

```bash
docker compose --profile rag run --rm rag-index \
  python -m financial_research_agent.reporting.validator_audit

docker compose --profile rag run --rm rag-index \
  python -m financial_research_agent.reporting.audit
```

第一个命令以`validation_only=true`验证真实Evidence的实体、日期、结构化事实和引用链，不作为
正式报告。来源、实体、日期和明确事实属于硬边界；未请求分析域由Harness归一化为未知，风险向量
与情景格式缺失只记警告。第二个命令运行正式Research Pipeline；未配置模型时应返回
`generation_failed`，不会使用模板报告冒充模型输出。

## API与可观测性

启动完整服务：

```bash
docker compose up -d etcd milvus app
curl http://localhost:8000/health
curl http://localhost:8000/tools
curl -X POST http://localhost:8000/analyze \
  -H 'Content-Type: application/json' \
  -d '{"question":"分析贵州茅台最近一年的行情和趋势"}'
```

`/analyze`返回Plan、逐工具状态、当前Run Evidence、报告状态、阶段耗时以及模型和Prompt版本。未配置模型时，真实数据工具仍可运行并返回Evidence，报告阶段会明确返回`REPORT_GENERATION_FAILED`。

三条真实HTTP演示结果保存在`artifacts/demo_runs/`。应用日志为结构化JSON，并对密钥类字段递归脱敏；详细验收结果见`docs/phase1/steps/09-api-observability/EVIDENCE.md`。

## DeepSeek模型配置与真实验收

DeepSeek官方API支持OpenAI请求格式。本项目把这类HTTP适配器内部命名为`openai_compatible`；它不是DeepSeek官方Provider名称，也不表示请求会经过OpenAI服务。

当前项目所有模型角色默认统一使用正式版`deepseek-v4-flash`，包括Planner、报告生成、
报告修订、上下文摘要、辅助Reviewer和真实模型评测。Pro仅可通过显式配置用于对照实验，
不作为生产默认、自动路由或失败回退。

在项目根目录的`.env`中配置以下字段，不要把真实Key写入`.env.example`、代码或文档：

```env
MODEL_PROVIDER=openai_compatible
MODEL_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-v4-flash
MODEL_API_KEY=<your-key>
MODEL_CONTEXT_WINDOW_TOKENS=1000000
MODEL_MAX_OUTPUT_TOKENS=384000
MODEL_THINKING_MODE=disabled
PLANNER_PROMPT_VERSION=planner_v3
REPORT_PROMPT_VERSION=report_v3
```

重新创建App并执行显式模型验收：

```bash
docker compose up -d --force-recreate app
docker compose run --rm --no-deps \
  -e API_BASE_URL=http://app:8000 app \
  python -m financial_research_agent.api_model_audit
docker compose run --rm --no-deps app \
  python -m financial_research_agent.reporting.model_revision_audit
```

最新验收中Market、Financial、Report、Comprehensive均为HTTP 200、`success=true`、`planner_source=model`和`validation_passed=true`。脱敏结果位于`artifacts/model_runs/`，详细证据见`docs/phase1/steps/09-1-model-integration/EVIDENCE.md`。

当前正式入口为`app`，默认`AGENT_FRAMEWORK=langchain`、
`ORCHESTRATION_RUNTIME=langgraph`。LangChain负责标准开发接口，Model/Tool
Gateway、Policy Engine、事务Budget Ledger和Completion Checker继续构成金融增强层。
迁移设计和实测证据见`docs/phase3-langchain-foundation/`。

## 测试与评测

完整回归：

```bash
docker compose run --rm --no-deps app \
  python -m unittest discover -s tests -q
```

显式运行20题真实模型评测：

```bash
docker compose run --rm --no-deps app \
  python -m financial_research_agent.evaluation.snapshot \
  --dataset regression \
  --output /artifacts/evaluation/snapshot_manifest.json

docker compose run --rm --no-deps \
  -e EVALUATION_REFERENCE_DATE=2026-07-15 \
  -e EVAL_SNAPSHOT_MANIFEST=/artifacts/evaluation/snapshot_manifest.json \
  -e API_BASE_URL=http://app:8000 app \
  python -m financial_research_agent.evaluation.run
```

当前仓库中的`holdout`是已使用过的历史验证集，不再视为私有。最终泛化验收通过仓库外
`EVAL_PRIVATE_HOLDOUT_PATH`加载，题目不会进入Prompt、失败修复文档或Git历史。

第三阶段集中验收结果：

- 本地回归122项通过，19项PostgreSQL可选项跳过；
- 最终Docker镜像中141项测试全部通过，包含PostgreSQL集成项；
- Flash 20题首次回归19/20（95%），定位指标窗口标签规则后定向复测通过；
- Intent、Skill、Tool、参数、Evidence覆盖、引用和Budget闭合保持100%；
- Flash首次整套运行P50为8.436秒，P95为14.143秒；
- 真实Pro异步任务完成规划、两项Tool、Evidence、报告、Validator、Completion和SSE全链路。

以上Pro结果是模型默认值变更前保留的历史基线，不代表当前运行策略。

机器可读结果位于
`artifacts/phase2_step08/regression/step03-langchain-flash/`和
`step03-langchain-flash-repair/`。完整对比见
`docs/phase3-langchain-foundation/steps/03-cutover-acceptance/METRICS_COMPARISON.md`。

第二阶段最终结果：Regression 20/20；V4 Pro Holdout 29/30（96.67%）；Intent、
Skill、Tool、参数、Evidence覆盖、引用和Budget闭合均为100%；Harness稳定性五项均为
100%。当前仍只覆盖600519和300750的日线、中长期财务与有限研报，不支持分钟行情、
财务时点回测或自动交易。完整结果见
`docs/phase2/steps/08-reliability-evaluation/FINAL_EVALUATION_REPORT.md`。
