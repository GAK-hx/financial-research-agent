# 第二阶段框架比较

| 方案 | 优势 | 不适配点 | 结论 |
|---|---|---|---|
| LangGraph | Python、持久化图、Checkpoint、恢复、Streaming、HITL | Policy、Budget、Evidence和业务幂等仍需实现 | 作为核心运行时 |
| LangChain Agent | 快速Tool Loop和丰富集成 | 高层ReAct会弱化现有受控轨迹 | 只选必要组件 |
| Hermes Agent | Skills、Memory、Context、Gateway成熟 | 通用个人Agent权限过宽，完整运行时侵入大 | 参考设计 |
| Pi Agent Core | Session、事件、Compaction和Provider设计优秀 | TypeScript/Coding Agent生态，与Python数据栈割裂 | 参考设计 |
| 完全自研 | 可控、学习深入 | 恢复和状态正确性成本高，面试可信度依赖大量证明 | 不再作为主方案 |

最终选择：LangGraph解决通用运行时稳定性；项目自身实现金融Skill、Tool Gateway、Evidence、Policy/Budget、Memory规则和Validator。
