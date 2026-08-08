# 04 记忆管理设计

## 1. “记忆”不是一个统一聊天记录

金融Agent需要区分不同语义、生命周期和可信度的记忆。把所有内容塞进messages会导致上下文膨胀、证据丢失和错误事实长期保留。

## 2. 记忆类型

### 2.1 Run Memory（运行记忆）

单次研究任务的状态：Request、QuerySpec、Plan、Task状态、ToolResult、Evidence、Draft和Validation。

第一步：内存对象，Run结束后可保存调试JSON。

第二步：持久化，支持恢复、回放和审计。

### 2.2 Working Memory（工作记忆）

模型当前一步需要看到的最小上下文：当前问题、当前计划、已完成任务摘要、相关Evidence和Validator反馈。

它是动态视图，不是新的事实存储。

### 2.3 Evidence Memory（证据记忆）

本次Run收集到的标准化Evidence集合。它是报告事实的唯一入口。

规则：

- Evidence不可由模型自由创建；
- 只能由成功工具结果转换；
- 保存source locator和observed_at；
- Report Claim只能引用当前Run Evidence；
- Evidence内容可摘要，但原始结构化数据和来源不可丢失。

### 2.4 Conversation/Session Memory（会话记忆）

跨多轮请求保存用户前文、当前研究标的和未完成意图。

第一步不实现跨会话持久化，只允许一次请求内对话上下文。

第二步需要区分：用户原话、系统确认过的偏好、临时任务上下文，避免把模型推测写成用户事实。

### 2.5 Semantic/Long-term Memory（长期语义记忆）

保存可跨任务复用的信息，例如用户偏好的报告格式、关注行业、常用股票池。长期记忆不是行情或财务事实库；市场事实仍从数据域实时查询。

第二步实现，且需要写入策略、来源、过期时间和用户删除能力。

### 2.6 Procedural Memory（程序性记忆）

系统Prompt、工具说明、指标口径、报告模板和策略规则。它通过版本化配置管理，不通过向量“记住”。

## 3. Context Manager

Context Manager负责从记忆中选择信息给模型，不负责创造事实。

```text
完整Run Memory
→ 按当前节点选择
→ 去除原始大表/重复内容
→ 保留任务、Evidence摘要和来源ID
→ Token预算检查
→ Model Context
```

### 节点上下文

- Interpreter：用户问题、当前日期、股票映射规则；
- Planner：QuerySpec、工具Schema、任务上限；
- Reporter：QuerySpec、Evidence、报告Schema；
- Revision：草稿、Validator错误、Evidence；
- 模型永远不需要数据库连接或完整历史Trace。

## 4. 记忆写入策略

| 记忆 | 写入者 | 是否允许模型直接写 |
|---|---|---:|
| Run Memory | Orchestrator | 否 |
| Working Memory | Context Manager生成 | 否 |
| Evidence Memory | Evidence Builder | 否 |
| Session Memory | Harness规则 | 仅提出候选 |
| Long-term Memory | Policy审批后的Memory Manager | 否 |
| Procedural Memory | 开发者配置 | 否 |

## 5. 记忆读取与可信度

优先级：Curated数据/Evidence > 用户明确陈述 > 系统配置 > 会话摘要 > 模型推断。

长期记忆只能辅助个性化和任务连续性，不能替代行情、财务或研报查询。

## 6. 记忆生命周期

- Working Memory：节点结束即可丢弃或重建；
- Run Memory：至少保留到任务结束；
- Evidence Memory：与报告一起保存；
- Session Memory：由会话期限控制；
- Long-term Memory：带来源、更新时间、过期和删除策略；
- Procedural Memory：随版本发布。

## 7. 第一步实现

第一步必须实现：

- 内存`RunContext`；
- Evidence Store；
- 节点级上下文构建；
- Evidence ID和当前Run隔离；
- 最大Evidence数量与模型上下文预算；
- Run结束导出调试JSON（可选）。

第一步不实现：跨会话记忆、长期偏好记忆、向量化对话历史、自动上下文压缩。

## 8. 第二步实现

- Run/Task/Evidence持久化；
- Session Memory；
- Context压缩与摘要；
- 长期偏好Memory；
- Memory候选审核、过期和删除；
- 恢复时重建Working Memory；
- 防止不同用户/Run之间记忆串线。

## 9. 待审核决策

- 第二步是否需要真正的多轮对话，还是以一次研究任务为主要交互？
- 长期记忆只保存用户偏好，还是也保存历史研究结论？建议不保存结论，只保存报告引用。
- 第一步Run调试产物保存在文件还是SQLite？建议文件，第二步再迁移数据库。

