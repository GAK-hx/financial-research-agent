# Step 06 实现清单

> 清单状态：`COMPLETE`。按一个完整 Step 执行，完整回归集中在收尾阶段完成。

## 06.1 数据模型与请求解析

- [x] 新增 `ReportAnalysisRequest`、候选集、选择和类型化事实模型
- [x] 为 `QuerySpec` 增加可选研报专属请求，保持旧 checkpoint 可读取
- [x] 增加 `report_candidate` Evidence 类型
- [x] 增加 `report_candidate_search`、`report_content_search` Tool 名称
- [x] 实现候选/深析的确定性触发规则
- [x] 保证研报日期不覆盖行情、财务等领域日期
- [x] 完成最小模型和解析测试
- [x] 更新 `PROGRESS.md`

## 06.2 候选检索工具

- [x] 复用现有混合索引实现按文档超额召回和去重
- [x] 实现用户显式日期严格筛选
- [x] 实现默认 90 天、少于 3 份扩大到 180 天
- [x] 实现 Top 5、未知日期策略和覆盖状态
- [x] 输出紧凑候选 Evidence，不暴露本地文件路径
- [x] 通过 LangChain StructuredTool 输出 content + artifact
- [x] 完成候选工具最小测试
- [x] 更新 `PROGRESS.md`

## 06.3 LangGraph 与正文访问控制

- [x] Planner 默认只规划候选工具
- [x] 增加请求解析、候选校验和深度决策节点
- [x] 实现按用户指定或确定性策略选择候选
- [x] 限制正文工具只能访问候选集成员
- [x] 实现普通深析 3 份、机构比较 5 份上限
- [x] 保存带租户/用户/会话范围和 TTL 的最近候选集
- [x] 支持候选 ID、机构/标题和会话序号选择
- [x] 拒绝伪造、跨租户、跨会话和过期候选
- [x] 更新预算、审计事件、SSE 状态和 checkpoint 默认字段
- [x] 完成分支最小测试
- [x] 更新 `PROGRESS.md`

## 06.4 上下文、事实与校验

- [x] 候选和深析使用独立 Context Policy/Manifest 字段
- [x] 深析上下文按文档和父块去重
- [x] 只对目标价、评级、预测和指标等按需提取 `ReportFact`
- [x] 校验模型抽取的原文片段、文档、页码和 Evidence 归属
- [x] `ReportClaim` 支持可选 `fact_ids`
- [x] 实现 `candidate_listing_v1` 校验档
- [x] 实现 `report_analysis_v2` 校验档
- [x] 将研报自然语言数字正则降为限定兜底
- [x] 保留行情、财务和指标的现有数值硬校验
- [x] 保留最多一次受控报告修正
- [x] 完成校验最小测试
- [x] 更新 `PROGRESS.md`

## 06.5 兼容、集中 Gate 与文档

- [x] `report_search` 保留一个发布周期的内部兼容别名
- [x] 默认 Tool schema 和 Skill 清单切换到新工具
- [x] 更新 Evidence Sufficiency 动态要求和安全补充策略
- [x] 更新现有 unit/eval 中旧工具名与预期轨迹
- [x] 测试 6 类正常流程和 4 类受控失败流程
- [x] 执行一次全量离线回归并集中修正
- [x] 执行一次小规模 `deepseek-v4-flash` 在线可行性测试
- [x] 把失败用例和原始模型输出保存为 Markdown
- [x] 生成 Step Gate 报告和运行手册
- [x] 确认最终 README 延后到 Step 07 组件边界稳定后统一重写
- [x] 更新 `PROGRESS.md` 为 `COMPLETE`
