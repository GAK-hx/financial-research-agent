# Step 09 — API与基础可观测性

## 目标

通过稳定API暴露Agent编排，并记录足够信息定位阶段、工具和模型问题。

## 依赖

- Step 07、08完成。

## 任务

1. `/health`检查应用配置；
2. `/tools`返回公开工具Schema；
3. `/analyze`接收ResearchRequest；
4. 返回query_spec、plan、tool_status、evidence、report、validation、timings；
5. 统一错误响应：code/message/run_id/details；
6. 每次请求分配run_id；
7. 使用结构化日志记录节点和耗时；
8. 脱敏模型配置和工具参数；
9. 记录模型/Prompt/工具版本；
10. 总超时和请求取消；
11. 保存三条演示Run JSON作为验收Artifact；
12. 更新Docker健康检查和资源统计。

## 验收标准

- 三个端点接口一致性测试通过；
- 错误均有run_id；
- 日志不包含API Key；
- 可从日志定位每个节点耗时和错误；
- 总时长不超过预算或明确超时；
- Compose服务健康且资源未明显超限。

## 不包含

- 持久化Run查询；
- 完整SSE Token Streaming；
- Langfuse平台集成。
