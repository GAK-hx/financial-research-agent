# Step 06：研报两级检索与分层校验

> 状态：`COMPLETE`
> 已完成实现、全量离线回归与一次 DeepSeek V4 Flash 在线可行性 Gate
> 默认模型：`deepseek-v4-flash`
> 数据边界：当前已登记并建立索引的 PDF 研报，不假设已经接入实时研报供应商

本计划细化并替代 Step 05 中的初版 `RESEARCH_REPORT_WORKFLOW.md`；旧文件保留为设计来源记录。

为兼容后续网络检索、跨用户缓存与分析复用，本 Step 的 `ReportCandidateSet`、
`research_report` Evidence 和 `ReportFact` 必须分别保持为可序列化的检索结果、分析输入和
分析产物，不能只存在于最终提示词中。持久化和跨用户复用由 Step 07 实现。

## 1. 为什么要改

当前 `report_search` 会直接执行混合检索，并把命中的研报正文父块作为
`research_report` Evidence 送入报告上下文。这条链路能运行，但存在四个问题：

1. 用户只想查看近期研报清单时，也会读取和传入正文，成本与上下文占用偏高；
2. 证据不足时仅把 `top_k` 从 5 扩大到 10，没有区分“扩大候选时间窗”和“增加正文块”；
3. 所有自然语言数字受到统一正则校验，对研报叙述、年份和格式变体过于敏感；
4. LangGraph 状态中没有候选集、深析决策和选中文档，无法完整解释为什么读取某份研报。

本 Step 在现有 LangChain Tool/Retriever、LangGraph、Milvus + SQLite 混合检索、
Evidence、ContextBuilder 和报告校验器之上改造，不新增 Agent 框架，也不引入新的基础设施。

## 2. 完成后的用户体验

| 用户问题 | 目标行为 |
|---|---|
| “分析贵州茅台近期股价” | 不访问研报索引 |
| “贵州茅台最近有哪些研报” | 返回最近 90 天候选清单；不足时扩大到 180 天并说明 |
| “总结贵州茅台最新研报观点” | 先筛候选，再对受控选择的最多 3 份研报检索正文 |
| “比较不同机构对贵州茅台目标价和盈利预测” | 候选初筛后，最多选择 5 份相关研报，提取并核验类型化事实 |
| “详细分析华鑫证券那份研报” | 只允许选择当前或同会话候选集中匹配的文档 |
| “分析第 2 份研报” | 从同租户、同用户、同会话的最近候选集解析序号后深析 |

如果 180 天内仍无已索引研报，系统返回“当前索引覆盖不足”，不得静默搜索互联网，
也不得让模型补写机构观点。

## 3. 目标流程

```text
问题理解
  -> 解析 ReportAnalysisRequest
  -> 需要 report 域？
       否：沿用现有行情/财务/事件/因子流程
       是：report_candidate_search（90 天，Top 5，按文档去重）
              -> 候选不足时扩大到 180 天
              -> 候选清单校验
              -> candidate_only：生成清单型回答
              -> deep：Harness 选择候选文档
                         -> report_content_search
                         -> 必要时提取 ReportFact
                         -> 合并 Evidence 并检查充分性
                         -> 深度报告校验与一次受控修正
```

核心原则：模型可以理解意图、解释证据和生成报告，但不能绕过候选集直接访问任意文档。

## 4. 分步实现

### 06.1 数据模型与请求解析

新增结构化模型：

- `ReportAnalysisRequest`：模式、用户筛选条件、显式日期、候选数量和深析意图；
- `ReportCandidate` / `ReportCandidateSet`：文档级候选及实际使用的时间窗；
- `ReportSelection`：选中的候选 ID、选择来源和原因；
- `ReportFact`：目标价、评级、盈利预测、财务指标、催化剂和风险等派生事实；
- `ReportValidationProfile`：`candidate_listing_v1` 或 `report_analysis_v2`。

请求模式由确定性解析器先判定：

- `candidate_only`：研报列表、有哪些、查找、筛选；
- `deep`：总结观点、全文/详细分析、目标价、评级、盈利预测、机构分歧、催化剂、风险，
  或显式选择某份研报；
- 非 report 域不生成研报请求。

模型可以输出建议模式，但 Harness 只接受枚举值，并再次依据原问题、候选范围和预算校验。
日期范围作为研报专属字段保存，不覆盖综合分析中的行情或财务时间范围。

最小可行性测试：数据模型边界、典型问句模式识别、研报日期不污染其他数据域。

### 06.2 候选检索工具

新增 LangChain 兼容的 `report_candidate_search` StructuredTool，复用现有
Milvus + SQLite 混合索引，不向模型提供整段父块正文。

默认策略：

- 用户显式提供研报日期：严格使用该范围，不自动扩大；
- 未提供：以业务参考日为结束日，先查最近 90 天、Top 5；
- 文档去重后少于 3 份：扩大到最近 180 天，再取 Top 5；
- 180 天后不足 3 份不算系统错误，返回实际数量并标记覆盖不足；
- `date_unknown=true` 默认排除，只有用户明确允许时才纳入并产生警告；
- 同一文档多个命中块合并为一个候选，以最高融合分和紧凑摘要展示。

候选输出只包含稳定候选 ID、文档 ID、股票、机构、标题、日期、相关度、160 字以内摘要、
版本/内容哈希和时间窗信息；不暴露宿主机 `source_path`。

实现初期不迁移 Milvus schema：从已有命中块超额召回并按 `document_id` 去重，减少改造风险。
如果后续语料达到需要单独文档索引的规模，再新增文档级 metadata collection，不放入本 Step。

最小可行性测试：90/180 天策略、严格日期、文档去重、未知日期、空结果和路径隐藏。

### 06.3 LangGraph 分支与受控正文检索

将旧 `report_search` 的正文能力整理为 `report_content_search`。该 Tool 只接受 Harness
生成的 `ReportSelection`，并且每个 `candidate_id` 必须存在于本次或同会话最近候选集中。

在现有单一 LangGraph 中加入四个明确节点：

1. `resolve_report_request`：解释研报模式和专属时间窗；
2. `validate_report_candidates`：校验候选范围和覆盖情况；
3. `decide_report_depth`：候选回答或深析的条件路由；
4. `retrieve_report_content`：只检索获准候选的正文块。

候选选择规则：

- 用户指定候选 ID、序号、机构或标题时优先匹配；
- 普通“总结最新观点”按日期、相关度和机构多样性最多选择 3 份；
- 机构分歧、目标价/盈利预测对比最多选择 5 份；
- 选择结果为空或出现伪造 ID 时受控终止，不回退到任意全文搜索；
- 候选集写入同租户、同用户、同会话的短期记忆，供“第 2 份”一类后续问题使用；
- 记忆只保存候选元数据和运行引用，不保存重复正文。

现有 Planner 对 report 域只规划 `report_candidate_search`；正文检索由 Harness 分支触发，
不允许模型在初始计划中同时安排候选和全文工具。

最小可行性测试：无研报域旁路、候选清单不进入正文、深析分支、伪造候选拒绝、会话序号解析。

### 06.4 上下文构建与分层校验

候选回答和深度分析使用不同上下文与校验规则。

候选上下文：

- 最多 5 个 `report_candidate` Evidence；
- 只允许支持“标题、机构、日期、是否命中筛选条件”等清单型陈述；
- Context Manifest 记录请求时间窗、实际时间窗、是否扩大、候选 ID 和裁剪情况。

深析上下文：

- 只包含选中文档的 `research_report` Evidence；
- 按 `document_id + parent_chunk_id` 去重，并保留机构、页码、内容哈希和版本；
- Context Manifest 记录候选集、最终选中文档、正文块和压缩结果；
- Evidence 正文、来源、页码和受保护数字不进入模型摘要压缩。

校验分两档：

- `candidate_listing_v1` 硬校验股票、日期、租户/会话范围、来源、去重和候选数量；
  相关度、摘要完整性和覆盖不足作为软提示；
- `report_analysis_v2` 硬校验引用属于当前运行和选中文档、机构/页码归属、类型化关键事实；
  风险向量、情景完整性和表达格式作为软提示。

`ReportFact` 只用于高风险、可结构化的研报内容：目标价、评级、预测值、财务指标等。
每个事实必须带值/单位/期间（适用时）、原始文本片段、文档 ID、页码和 Evidence ID。
报告 Claim 可选引用 `fact_ids`。现有自然语言数字正则保留为过渡兜底，但不再扫描所有研报叙述；
它只处理没有类型化事实的明确数值结论。行情、指标和财务 Evidence 的原有数值校验保持不变。

修正策略最多一次：先做确定性的引用绑定和格式修正，再允许模型重写可修问题；
股票错误、错误文档、越权、缺失来源和事实值不一致不能靠改写绕过。

最小可行性测试：候选不能支持目标价结论、选中文档边界、类型化事实单位/期间、软硬错误分流。

### 06.5 收尾、迁移与集中 Gate

迁移策略：

- `report_search` 保留一个发布周期作为内部兼容别名，不再出现在默认 Tool schema 和 Skill 清单中；
- 评测用例和 Skill 要求按 `candidate_only/deep` 改为动态 Evidence 要求；
- API/SSE 响应补充候选范围、深析模式和选中文档的可解释状态；
- 旧的已完成运行和 PostgreSQL checkpoint 不做破坏性迁移；新增 state 字段均提供默认值。

集中 Gate 只在本 Step 末执行一次完整回归：

1. 普通股票分析不调用研报工具；
2. 最近研报清单只调用候选工具；
3. 最新研报观点先候选后正文；
4. 指定机构/候选及会话序号能正确选文档；
5. 目标价、盈利预测和机构分歧使用类型化事实；
6. 综合行情/财务/研报查询保持原有并行工具能力；
7. 候选空、正文空、Milvus 不可用、模型不可用均受控终止；
8. 全量离线回归通过；只做一次小规模 DeepSeek Flash 在线可行性测试，原始输出保存为 Markdown。

## 5. 预计修改范围

主要代码位置：

- `domain/models.py`：Tool 名称、Evidence 类型、ReportRequest/Selection/Fact；
- `rag/models.py`、`rag/store.py`：候选模型、超额召回和按文档去重；
- `tools/report_search.py`：拆分候选工具与正文工具，之后可按职责拆文件；
- `integrations/langchain/retrieval.py`、`tools.py`：Document/Evidence/Tool artifact 兼容；
- `orchestration/interpreter.py`、`planner.py`、`validator.py`：模式解析和计划限制；
- `orchestration/langgraph_runtime.py`：候选、路由、选文档、正文检索状态；
- `analysis/sufficiency.py`：按模式决定所需 Evidence 和安全补充动作；
- `memory/context.py`：候选/选中文档的 Context Manifest；
- `reporting/validators.py`：分层校验和 ReportFact；
- `skills/catalog.json` 及研报相关 Skill：新工具和动态证据要求；
- `tests/`、`evals/`：更新旧 `report_search` 预期并增加端到端路径。

## 6. 明确不做

- 不新增通用多 Agent 或让多个模型角色互相讨论；
- 不接自动交易、实时研报爬虫或未获授权的外部数据源；
- 不让模型访问任意 PDF 路径、SQL、Milvus collection 或文档 ID；
- 不在本 Step 重写最终 README；组件边界稳定后再按架构重写；
- 不为候选初筛额外部署 Elasticsearch、消息队列或新数据库；
- 不把模型抽取的事实当成原始 Evidence，类型化事实始终保留正文来源链路。

## 7. 完成标准

- 六类典型问题都走到预期分支，工具调用次数与范围可解释；
- 候选清单不会意外把正文父块送入模型；
- 深析只能读取获准候选，伪造或跨会话候选被拒绝；
- 90/180 天行为、数据覆盖不足和索引来源在输出中可见；
- 研报关键数值走类型化事实校验，普通叙述不再被过度正则限制；
- LangChain StructuredTool、LangGraph checkpoint、Evidence 和 Context Manifest 保持兼容；
- 全量离线测试通过，失败样例和在线 Flash 输出均有 Markdown 记录。
