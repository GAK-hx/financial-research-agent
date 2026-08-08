# 第三阶段验收清单

## 框架基础

- [x] 显式依赖 LangChain 所需包并锁定兼容版本
- [x] 模型正式路径使用 ChatModel/Runnable
- [x] 规划和报告使用 Structured Output
- [x] Tool 正式入口为 StructuredTool
- [x] 图状态包含标准 Message 轨迹
- [x] 研报检索实现 BaseRetriever/Document
- [x] Context/Skill 能通过 Middleware 或 Runnable 生命周期接入
- [x] 长期记忆提供 LangGraph Store 兼容入口

## 项目增强能力

- [x] 所有正式模型调用仍经过 ModelGateway
- [x] 所有正式工具调用仍经过 ToolGateway
- [x] Policy、Budget、幂等和审计保持有效
- [x] DAG 依赖和并行调度保持有效
- [x] ToolMessage artifact 可重建 Evidence
- [x] Context Manifest 和 Evidence 保护保持有效
- [x] Memory 隔离、TTL、删除和敏感检查保持有效
- [x] 报告数字、来源、机构和日期校验保持有效

## 运行与交付

- [x] PostgreSQL Checkpoint 恢复通过
- [x] API/Worker/SSE 兼容新运行路径
- [x] Docker Compose 可复现部署
- [x] 旧API响应格式保持兼容
- [x] Regression、Holdout、稳定性达到阈值
- [x] LangSmith关闭时本地系统可完整运行
- [x] README、架构、演示和简历口径更新

## 执行方式

- [x] Step 01只执行核心链路冒烟测试
- [x] Step 02只执行增强能力组合冒烟测试
- [x] Step 03一次性完成集中回归和Docker验收
- [x] 不为接口包装重复建设无业务价值的测试
