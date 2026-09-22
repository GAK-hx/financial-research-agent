# Step 07 实现清单

## 07.1 查询、分析、输出分离

- [x] 新增 `AtomicQueryKey`、`RetrievalSnapshot`、`AnalysisArtifact`、`PresentationEnvelope`
- [x] 新增 `CacheDecision`：fresh/partial/stale/inflight/miss
- [x] 将多股票、多数据域计划拆成原子工作单元
- [x] 建立 PostgreSQL 工作单元、Job 依赖、快照、分析产物和依赖关系表
- [x] 实现工作租约、心跳、接管与幂等完成
- [x] 保持现有 Job API 和旧 checkpoint 兼容
- [x] 完成最小状态与 single-flight 测试
- [x] 更新 `PROGRESS.md`

## 07.2 Elasticsearch 与网络搜索

- [x] 固定 ES 9.3.6 image 与官方 Python client 9.3.0（同 9.3 minor）
- [x] 增加可选 `search` Docker profile、健康检查、volume 和资源限制
- [x] 凭据只从 `.env/config` 注入，日志和错误脱敏
- [x] 建立 `web_documents_v1` mapping、alias 和初始化命令
- [x] 实现 `WebSearchProvider` 接口和 Tavily 适配器
- [x] 实现 `web_search` LangChain StructuredTool
- [x] Harness 固定股票、日期、域名策略、条数和预算
- [x] 实现 URL canonicalization、content hash、版本化 upsert
- [x] 实现 BM25 + 股票/主题/日期/来源过滤
- [x] 转换为带 URL、发布时间、抓取时间和版本的 Evidence
- [x] Provider 未配置/限流/超时/空结果返回结构化错误
- [x] 完成 fake provider、内存索引与 ES mapping 最小测试
- [x] 更新 `PROGRESS.md`

## 07.3 缓存、增量与跨用户复用

- [x] 实现结构化 Retrieval/Analysis key
- [x] 实现 TTL + source snapshot/version 双重失效
- [x] 实现网络查询 24 小时回看窗口和水位推进
- [x] 实现 exact duplicate 的 in-flight join
- [x] 实现多股票 partial overlap，只补缺失工作单元
- [x] 实现 public 跨用户共享与 tenant 私有隔离
- [x] 实现 AnalysisArtifact 依赖图和精确失效
- [x] 用户记忆、偏好和最终文本不进入公共缓存
- [x] 增加命中率、节省调用、等待者和增量变化指标
- [x] 完成冻结时间和并发最小测试
- [x] 更新 `PROGRESS.md`

## 07.4 LangGraph、API 与输出

- [x] 增加工作拆分、缓存决策、执行/加入、快照组装节点
- [x] 增加分析缓存决策和复用节点
- [x] 只有校验通过的 AnalysisArtifact 可以共享
- [x] 输出层重新绑定当前 tenant/user/session 和引用
- [x] SSE 返回 cache decision、refresh、data_as_of 和 artifact lineage
- [x] “最新”请求等待增量；普通请求刷新失败可标记后回退旧快照
- [x] 共享工作失败不阻止各 Job 独立重试输出
- [x] 默认模型统一为 `deepseek-v4-flash`
- [x] 完成最小端到端测试
- [x] 更新 `PROGRESS.md`

## 07.5 集中 Gate

- [x] 11 只股票、5 用户、每人 5 只且有交叉
- [x] 精确重复只产生一次公共检索和一个持久化分析版本
- [x] 部分交叉只补查缺失项
- [x] TTL 后只做带 24 小时回看窗口的增量刷新
- [x] Evidence 变化只失效相关分析产物
- [x] 验证跨租户键隔离和最终文本不共享
- [x] 真实 ES 索引、版本化 upsert、查询和服务健康 Gate
- [x] Provider 未配置时的结构化失败 Gate
- [ ] 真实 Tavily 限流、超时和 Provider 故障恢复 Gate
- [x] 执行一次全量离线回归并集中修正
- [x] 执行一次受控 DeepSeek Flash Agent 在线流程
- [ ] 执行一次受控 Tavily + ES + DeepSeek Flash 联合在线流程
- [x] 将原始输出、失败案例、命中率和调用节省保存为 Markdown
- [x] 编写运行手册、Gate 报告和组件说明
- [ ] 组件稳定后重写最终 README，不按阶段叙述
- [ ] 在线 Gate 后更新 `PROGRESS.md` 为 `COMPLETE`
