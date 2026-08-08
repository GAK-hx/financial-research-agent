# 第一步精细实施计划：受约束的 Agent 编排

## 0. 计划依据

本计划基于旧项目 `financial-agent` 中已经实际跑通的部分制定：

- Docker Compose 能稳定运行 Milvus 2.4 + Etcd；
- 6 份贵州茅台/宁德时代研报已完成 PDF 下载；
- PyMuPDF + SentenceTransformers + Milvus 已完成 96 个 chunk 的索引和检索验证；
- PyIceberg 使用 SQLite Catalog + `file://` Warehouse 已成功建表和追加写入；
- Kafka → Flink → Kafka → PyIceberg 的 Mock 链路已打通，但其数据为模拟数据；
- Flink 与 Iceberg 通过 Kafka/Python 解耦可避免 Connector/JAR 冲突。

新项目不会照搬以下已知问题：

- 不用 `MIN(price)`/`MAX(price)` 伪装真实 Open/Close；
- 不对累计成交量、成交额直接求和；
- 不将 Mock 分钟线作为正式研究证据；
- 不硬编码 BGE 向量维度，启动索引时通过模型输出探测维度；
- 不使用即将弱化的旧 PyMilvus ORM 作为新代码主接口，优先采用 `MilvusClient`；
- 不让模型直接执行任意 SQL；
- 第一步不引入 ClickHouse、HDFS、MinIO、LangGraph、Kafka/Flink运行时和完整 Harness。

## 1. 第一步交付目标

交付一个能在单机 Docker 环境运行的金融研究 Agent 编排闭环：

```text
用户问题
→ Query Interpreter
→ 结构化 AnalysisPlan
→ Plan Validator
→ 类型化金融工具
→ Evidence Builder
→ ResearchReport
→ Numeric/Citation Validator
→ API 返回报告和证据
```

支持三类正式问题：

1. 行情/技术指标问题；
2. 研报观点问题；
3. 行情 + 研报综合问题。

财务工具保留接口和模型，但只有在真实财务表完成后才加入默认工具白名单，避免空实现冒充可用能力。

## 2. 第一步明确边界

### 必须完成

- AkShare 日线批量采集并增量写入 Iceberg；
- 日线数据质量检查；
- Market、Indicator、Report Search 三个可用工具；
- Financial Tool 的接口规范，可选择在日线闭环后实现；
- Pydantic 领域模型；
- 规则版 Query Interpreter 兜底；
- 模型版结构化 Planner；
- 工具白名单和参数校验；
- 有限并行 Executor；
- Evidence Schema；
- 结构化报告生成；
- 数字和引用校验；
- FastAPI `/analyze` 与 `/health`；
- 单元测试、集成测试和最小评测集。

### 本步不完成

- 长期记忆与多轮会话；
- 工作空间和运行回放；
- 进程级任务恢复；
- 动态工具发现/MCP；
- 多 Agent 协作；
- 人工审批；
- 交易、写库、告警等副作用工具；
- 完整在线评测与生产部署。

## 3. 目标运行环境与资源

第一步默认只常驻三项：

| 服务 | 作用 | 内存上限 |
|---|---|---:|
| Etcd | Milvus 元数据 | 256MB |
| Milvus Standalone | 研报向量检索 | 1800MB |
| App | API、模型编排、Iceberg/DuckDB查询 | 900MB |
| 合计 |  | 约 2.9GB |

相比旧项目，Milvus 从 1500MB 小幅提高到 1800MB，Etcd 从 200MB 提高到 256MB，App 预留 900MB 以容纳 PyArrow、PyIceberg 和 API。Kafka/Flink 不在第一步 Compose 中常驻，因此总资源显著低于旧项目约 5.9GB。

SentenceTransformer 构建索引时可能超过 App 常驻内存。正式实现时优先采用一次性 `rag-index` profile，允许该任务临时使用约 1.5GB；索引完成后停止容器，API查询侧可根据实际内存决定常驻本地模型或调用独立Embedding接口。

## 4. 目录与模块职责

```text
src/financial_research_agent/
├── api.py                       FastAPI入口
├── config.py                    环境变量和执行上限
├── domain/models.py             全部Pydantic领域模型
├── ingestion/
│   ├── market_daily.py          AkShare日线采集
│   ├── financial.py             财务采集（后置）
│   └── report_index.py          研报索引
├── repositories/
│   ├── iceberg.py               Catalog/Table访问
│   └── milvus.py                向量索引和检索
├── tools/
│   ├── base.py                  工具协议
│   ├── market.py                日线查询
│   ├── indicators.py            确定性指标计算
│   ├── reports.py               研报检索
│   └── financial.py             财务工具（后置）
├── orchestration/
│   ├── interpreter.py           问题标准化
│   ├── planner.py               模型/规则计划
│   ├── plan_validator.py        白名单和依赖检查
│   ├── registry.py              工具注册
│   ├── executor.py              并发和超时
│   ├── evidence_builder.py      结果标准化
│   └── service.py               完整编排入口
├── reporting/
│   ├── generator.py             结构化报告
│   └── validators.py            数字/引用校验
└── providers/
    └── model.py                 模型供应商适配器
```

## 5. 任务分解

### P0：确认接口规范与可运行脚手架

任务：

- 完成项目包、依赖、配置和健康检查；
- 定义领域模型和 Tool Registry；
- Executor 支持依赖任务和最大并行数；
- 所有工具默认只读；
- 添加基础模型校验测试；
- `docker compose config` 可通过；
- Python模块可编译。

验收：

- `/health` 返回 `status=ok`；
- 非白名单工具无法从 Registry 获取；
- 非六位股票代码和反向日期被 Pydantic 拒绝；
- 循环依赖在执行前被拒绝。

当前状态：脚手架已创建，需在安装依赖后运行测试。

### P1：真实日线采集与Iceberg表

任务：

1. 定义股票池配置，第一版至少包括 `600519`、`300750`；
2. 调用 `stock_zh_a_hist(period="daily", adjust="qfq")`；
3. 映射字段：日期、股票代码、开盘、收盘、最高、最低、成交量、成交额、振幅、涨跌幅、涨跌额、换手率；
4. 增加 `stock_name`、`adjust_type`、`source`、`ingested_at`、`batch_id`；
5. 校验OHLC关系、价格/成交量非负、日期合法；
6. 以 `stock_code + trade_date + adjust_type` 去重；
7. 建立 `market.kline_daily` Iceberg表；
8. 首次回填指定日期范围；
9. 增量任务读取每只股票最大交易日，从下一交易日开始获取；
10. 写入前计算新增/重复/异常行统计；
11. 同批次重跑应保持业务记录不重复；
12. 生成 `ingestion_report.json`。

表字段建议：

```text
stock_code string
stock_name string
trade_date date
open double
high double
low double
close double
volume long
amount double
amplitude double
change_pct double
change_amount double
turnover_rate double
adjust_type string
source string
batch_id string
ingested_at timestamp
```

分区：数据规模较小时先按 `trade_year` identity partition；不要过度按股票分区造成小文件。第一版批量写入单次建议至少按股票汇总后写入，避免逐行append。

验收：

- 两只股票至少三年真实日线成功写入；
- 抽样10行与AkShare原始响应一致；
- 同一批次重跑无业务重复；
- 异常行不会进入正式表；
- Repository可以按股票和日期范围返回数据。

### P2：Market Tool与Indicator Tool

Market Tool输入：

```text
stock_code
start_date
end_date
adjust_type=qfq
limit<=1000
```

输出不直接返回任意PyArrow对象，而是返回Pydantic结果，包含数据日期、行数、摘要和来源locator。

Indicator Tool第一版只实现：

- 区间收益率；
- 年化波动率；
- MA5/MA20；
- 最大回撤；
- 最近成交量相对20日均量；
- 区间最高/最低价。

所有指标使用Python/NumPy/Pandas确定性计算；模型只解释，不参与计算。

验收：

- 固定小样本手算与工具结果一致；
- 日期不足时返回明确错误或低置信警告；
- 非交易日区间能返回实际首末交易日；
- 每个结果生成至少一条可追溯Evidence。

### P3：研报索引重构

任务：

1. 复用已验证的6份PDF；
2. 使用PyMuPDF逐页解析，保留页码；
3. 清除明显页眉页脚、空白和重复行；
4. 第一版继续使用500字符、50重叠的递归分块，减少一次性改动；
5. 从文件名和配置补全股票代码、机构、报告标题；
6. 记录 `page_number`、`chunk_id`、`source_path`；
7. 加载BGE后通过 `get_sentence_embedding_dimension()` 获取实际维度；
8. Collection不存在时按实际维度创建，存在但Schema不匹配时明确失败，不静默drop；
9. 使用新Collection名 `research_reports_v1`，避免覆盖旧索引；
10. 使用IP + normalized embeddings；
11. 建立索引后验证实体数、随机chunk和两条固定查询。

Milvus字段建议：

```text
id(auto)
embedding(dynamic dimension)
text
stock_code
stock_name
institution
report_title
report_date(optional)
page_number
chunk_id
source_path
```

验收：

- 6份PDF全部被识别；
- chunk数量合理且非空；
- 每条命中包含股票、机构、标题、页码；
- “贵州茅台盈利能力”“宁德时代技术创新”固定查询能召回对应标的；
- 索引脚本重复运行可选择重建或跳过，不意外删除其他Collection。

### P4：Report Search Tool

输入：股票代码、查询文本、可选机构、Top K（1～10）。

流程：先用股票代码进行Metadata Filter，再向量搜索；如果过滤后无结果，返回`NO_REPORT_EVIDENCE`，不跨股票拼接无关证据。

输出：相似度、原文、股票、机构、报告、页码、chunk ID和source locator。

验收：

- Top K边界有效；
- 不会返回其他股票的chunk；
- 每个命中转换为一条Research Report Evidence；
- Milvus不可用时返回结构化工具错误。

### P5：Query Interpreter与Planner

先实现规则兜底，再接模型：

- 股票名称映射到代码；
- “最近一个月/三个月/一年”转换为明确日期；
- 根据关键词识别market/report/comprehensive；
- 规则Planner可稳定生成三类标准计划；
- 模型Planner输出同一个`AnalysisPlan` Schema；
- 模型输出失败时回退规则Planner；
- Planner只获得工具Schema，不获得数据库连接信息；
- 最多6个任务，最多一次补充计划。

标准计划示例：

- 行情问题：Market → Indicator；
- 研报问题：Report Search；
- 综合问题：Market与Report Search并行，Indicator依赖Market。

验收：

- 15个固定问题的股票、日期、意图解析正确；
- 计划只包含注册工具；
- 参数通过对应工具Pydantic模型；
- 不允许循环依赖和未知依赖；
- 模型不可用时标准问题仍可通过规则模式运行。

### P6：Evidence Builder与报告生成

Evidence必须包含：

- 唯一evidence_id；
- 类型和研究对象；
- 可直接引用的statement；
- 结构化data；
- source_type、locator、observed_at；
- 数据日期或研报页码。

报告Schema：summary、claims、risks、data_as_of。每个claim至少有一个evidence_id。

报告Prompt只接收QuerySpec和Evidence，不接收原始数据库连接或未校验工具输出。模型不可用时返回明确的`generation_failed`并保留已生成Evidence；规则模板只能用于显式的校验器开发样例，不得冒充正式报告。

验收：

- 每个claim引用当前Run存在的Evidence；
- 不使用失败工具的结果；
- 报告明确数据截止日；
- 机构观点保留机构名称和页码；
- 无研报时不会伪造机构观点。

### P7：Numeric/Citation Validator

Citation校验：

- evidence_id存在；
- evidence属于当前Run；
- claim至少有一个证据；
- 研报Evidence有报告和页码；
- 股票实体一致。

Numeric校验第一版采用结构化字段，不尝试从任意长文本中完美抽取所有数字：ReportClaim增加可选`metrics`字段或要求关键数字在结构化section中返回，再与Evidence比较。

失败处理：允许带Validator反馈重写一次；第二次仍失败则返回`validation_status=failed`和草稿，不将其标记为完成报告。

验收：构造缺失引用、伪造ID、错误股票和错误数字样例，均能被拦截。

### P8：FastAPI闭环

第一版接口：

- `GET /health`；
- `POST /ingestion/market-daily`（开发环境或CLI替代）；
- `POST /indexes/reports`（建议CLI/Profile执行）；
- `POST /analyze`；
- `GET /tools`；
- `GET /evidence/{evidence_id}`（第一步可仅在内存Run范围提供）。

`/analyze`返回：request、query_spec、plan、tool_status、evidence、report、validation和timings。生产展示可隐藏内部Prompt与敏感配置。

验收：三个标准问题端到端通过；API超时受总预算控制；错误使用统一JSON格式。

### P9：测试与最小评测

单元测试：

- Pydantic模型；
- Plan依赖环；
- Tool Registry白名单；
- 日线质量规则；
- 指标计算；
- Citation/Numeric Validator。

集成测试：

- AkShare小范围采集（标记为network）；
- Iceberg写入和扫描；
- Milvus索引与检索；
- API三条标准路径。

第一步最小评测集至少20题：

- 行情5题；
- 指标5题；
- 研报5题；
- 综合3题；
- 非法/缺失2题。

记录：Intent Accuracy、Tool Selection Accuracy、参数正确率、引用正确率、数字一致率、任务成功率和P95耗时。

## 6. 推荐实施顺序与提交粒度

| 顺序 | 工作包 | 建议独立提交 |
|---:|---|---|
| 1 | P0脚手架与接口规范 | scaffold typed domain and executor |
| 2 | P1日线采集与Iceberg | add daily market ingestion |
| 3 | P2市场与指标工具 | add deterministic market tools |
| 4 | P3研报索引 | add metadata-aware report index |
| 5 | P4研报工具 | add filtered report search tool |
| 6 | P5解释器与Planner | add constrained planning |
| 7 | P6 Evidence与报告 | add evidence-grounded reporting |
| 8 | P7 Validators | enforce citations and metrics |
| 9 | P8 API闭环 | expose analyze endpoint |
| 10 | P9测试评测 | add regression evaluation set |

每个工作包必须先通过自己的测试和验收，再进入下一项。不要在日线表、研报Metadata和Tool Schema尚未稳定时编写最终Prompt。

## 7. 风险与应对

| 风险 | 应对 |
|---|---|
| AkShare接口临时失败或限流 | Tenacity重试、股票级失败记录、允许次日补数 |
| 复权数据口径混用 | adjust_type进入业务键和Evidence，工具必须显式指定 |
| Iceberg小文件 | 按股票/批次聚合写入，不逐行append |
| SQLite Catalog并发写 | 第一步单写者；API只读，采集任务串行化 |
| BGE维度不一致 | 运行时探测，Collection Schema严格比对 |
| Milvus内存不足 | 索引使用一次性profile，API限制Top K |
| 模型输出非法JSON | Pydantic校验，修复一次，随后规则Planner降级 |
| 模型选错工具 | 工具白名单、Plan Validator、固定轨迹测试 |
| 数字幻觉 | 指标由代码计算，报告关键指标结构化并校验 |
| 无证据结论 | claim强制evidence_ids，Citation Validator拦截 |

## 8. 第一步完成定义

同时满足以下条件才算完成：

- 两只真实股票的日线数据可增量写入和查询；
- Market、Indicator、Report Search工具均通过集成测试；
- 至少6份研报可按股票过滤并返回页码；
- 三类标准问题可生成合法计划；
- 模型只能调用注册的只读工具；
- 综合问题能并行查询行情和研报；
- 报告关键结论全部绑定Evidence；
- 错误数字和伪造引用能被Validator拦截；
- `/analyze`端到端返回报告、证据和校验状态；
- 20题最小评测集有可复现结果；
- README记录一键启动、示例请求、已知限制和真实指标。
