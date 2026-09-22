# Step 06 运行手册

## 默认行为

- “有哪些研报/研报清单”：只执行 `report_candidate_search`；
- “总结观点/目标价/评级/预测”：先候选，再由 LangGraph/Harness 调用
  `report_content_search`；
- 候选默认最近 90 天、Top 5；不足 3 份时扩大到 180 天；
- 普通深析最多 3 份，机构分歧最多 5 份；
- 默认模型为 `deepseek-v4-flash`，默认编排运行时为 LangGraph。

## 本地检查

```bash
IDENTITY_MODE=local .venv/bin/pytest -q
.venv/bin/ruff check src tests
```

本 Step 离线检查不需要 Docker。只有验证真实 PostgreSQL checkpoint、Milvus 索引和完整 API
部署时才需要启动现有 Compose 服务；本 Step 没有新增容器。

## 关键可观察字段

API/运行结果中的 `report_workflow` 包含：

- 校验档和模式；
- 请求/实际检索窗口及是否扩大；
- 候选集 ID、候选 ID；
- 选中文档和选择原因；
- 正文缺失文档及覆盖状态。

`report_facts` 保存目标价、评级、盈利预测等类型化事实及原文、文档、页码和 Evidence 链路。
Context Manifest 的 warnings 同步记录校验档、候选集、选中文档、窗口扩大和未知日期。

## 常见失败

| 错误 | 含义 | 处理 |
|---|---|---|
| `REPORT_DATA_EMPTY` | 90/180 天内没有已索引候选 | 检查 PDF 登记与索引覆盖，不自动联网补写 |
| `REPORT_SELECTION_OUTSIDE_CANDIDATE_SET` | 请求了候选集外 ID | 重新列候选或使用当前会话候选 |
| `REPORT_CONTENT_EMPTY` | 选中文档没有可用正文块 | 重建该文档索引并保留受控失败 |
| `REPORT_CONTENT_PARTIAL` | 多文档深析只取到部分正文 | 输出缺失文档和覆盖限制，不伪造观点 |
| `REPORT_CANDIDATE_SCOPE_VIOLATION` | 候选元数据被用于支持详细结论 | 改用正文 Evidence 或删除该结论 |
| `REPORT_FACT_*_UNSUPPORTED` | 目标价、评级等无法匹配类型化事实 | 核对原文、页码、单位、期间和 fact ID |

## 安全边界

- Planner 看不到正文 Tool；正文 Tool 只由 Harness 分支触发；
- 候选和正文 Tool 都不向模型暴露本机 `source_path`；
- 伪造候选 ID、错误文档、错误页码和跨选择引用不会通过校验；
- 同会话序号通过带 TTL 的候选元数据解析，记忆不复制正文；
- `report_search` 仅保留内部兼容类，不进入默认 Registry、Skill 或评测轨迹。
