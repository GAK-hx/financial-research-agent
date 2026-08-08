# 第二阶段框架参考

## LangGraph：正式运行时依赖

- [LangGraph Overview](https://docs.langchain.com/oss/python/langgraph/overview)：用于确认低层编排、持久化执行、Streaming和人工中断的框架定位；
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)：用于设计Thread、Checkpoint、Pending Writes和状态恢复；
- [LangGraph Functional API / Durable Execution](https://docs.langchain.com/oss/python/langgraph/functional-api)：用于设计副作用Task、幂等和可恢复执行；
- [LangGraph Checkpointers](https://docs.langchain.com/oss/python/integrations/checkpointers/index)：用于选择PostgreSQL Checkpointer并区分开发/生产存储。

## Hermes和Pi：设计参考，非运行时依赖

- [Hermes Agent](https://github.com/NousResearch/hermes-agent)：参考Skill、Memory、Context和Gateway的组织思路，不接入完整Hermes运行时；
- [Pi Agent SDK](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/sdk.md)：参考Session、事件流和Context Compaction，不引入TypeScript Coding Agent依赖。

## 使用原则

1. 实现前在Step 01固定确切依赖版本；
2. 架构只采用与本项目边界匹配的能力，不照搬通用Agent的广权限默认值；
3. 所有推荐均需用本项目Regression、恢复、安全和成本测试验证；
4. 不以官方文档的功能宣称代替本项目的验收证据。
