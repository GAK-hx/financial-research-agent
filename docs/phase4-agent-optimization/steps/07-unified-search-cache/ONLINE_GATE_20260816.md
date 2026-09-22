# Step 07 在线 Gate 原始记录

## 范围

本记录只包含 2026-08-16 实际执行的 PostgreSQL、Elasticsearch 与 DeepSeek V4 Flash 检查。
由于未配置 `WEB_SEARCH_API_KEY`，Tavily 联合流程不在通过范围内。

## 环境

- 默认模型：`deepseek-v4-flash`
- Agent 框架：LangChain Tool + LangGraph 状态编排
- 持久化：PostgreSQL，migration head=`20260815_0008`
- 网页索引：Elasticsearch 9.3.6，cluster status=`green`
- 服务：app、job-api、PostgreSQL、Elasticsearch 健康，job-worker 正常运行

## Elasticsearch 结果

```text
new=1
unchanged=1
updated=1
hit_count=1
stored_version=2
content_hash_match=true
serializer_warnings=0
```

测试文档在 Gate 后已删除。首次运行暴露的时间字符串反序列化 warning 已修正并复测为 0。

## 未配置 Provider 结果

```json
{"success": false, "error_code": "WEB_SEARCH_NOT_CONFIGURED", "evidence_count": 0}
```

系统没有把无来源内容转换为 Evidence，符合失败关闭设计。

## DeepSeek V4 Flash 结果

输入：

```text
分析贵州茅台2025年营收和归母净利润，简要说明同比变化。
```

终态摘要：

```text
HTTP 200
run_id=862a9f34b1764e428fef06d21c3a0f97
success=true
planner_source=model
reporting_status=completed
validation_passed=true
tool=financial_query
tool_success=true
cache_decision=miss
selected_skill=financial_growth_analysis@1.1.0
evidence_count=1
```

网络波动触发模型重试后恢复，最终多次 DeepSeek 请求返回 200。测试过程中没有记录或输出 API key。

## 回归

```text
168 passed, 23 skipped, 19 warnings in 11.07s
Ruff: PASS
compileall: PASS
secret scan excluding .env: PASS
```

warnings 是 FastAPI `on_event` 与 TestClient 的既有弃用提示，不是本 Step 新增失败。

## 遗留 Gate

- 配置 Tavily key；
- 执行真实网络检索、ES 落库、Evidence 生成与 Flash 报告联合流程；
- 验证真实供应商限流、日期边界与正文返回；
- 通过后再将 Step 07 标记为 `COMPLETE`。
