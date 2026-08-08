# Step 06 — Memory与Context Compression

## 目标

实现可删除、可过期、可隔离的Session/Preference Memory，并按节点和Skill构建可追溯Context，在不损失Evidence的前提下控制Token。

## 前置条件

- Gate 05已通过；
- `MEMORY_CONTEXT_DESIGN.md`已审核；
- Skill能引用Context Policy，Model Gateway能记录Token/Usage。

## 子任务

1. 实现Session Memory、Preference Memory、Memory Source和Memory Audit Schema；
2. 建立用户/租户/Session复合隔离键、TTL、版本和删除语义；
3. 实现Candidate Memory分类、敏感检查、显式Preference确认和受控写入；
4. 实现Memory查询、删除、过期清理与审计事件；
5. 实现`ContextPolicy`、`ContextManifest`和节点级Context Builder；
6. 按Interpret、Select Skill、Plan、Report和Revise分别定义内容白名单；
7. 实现去重、优先级裁剪、结构化聚合和Token估算；
8. 仅在确定性压缩不足时调用一层模型摘要；
9. 为摘要记录输入范围、原始引用、模型、Prompt版本、时间和校验结果；
10. 实现Evidence保护检查，禁止摘要改写数字、单位、Source Locator和Snapshot；
11. 实现Context超限时的降级/拒绝策略，禁止无限摘要递归；
12. 用压缩开/关A/B测试Token、费用、延迟、Validator通过率和数字/引用一致性。

## 测试清单

- 跨用户、跨租户、跨Session访问被拦截；
- TTL过期与用户删除生效；
- Preference未确认不持久化；
- API Key、凭证和敏感文本不进Memory；
- 历史研究结论不会跳过本次Tool/Evidence；
- 压缩前后数字、单位和来源一致率100%；
- 摘要失败可回退到裁剪后Context并显式警告；
- 20题Regression与多轮追问测试通过。

## 交付物

- Memory Manager、表、TTL任务和审计；
- Context Policy/Builder/Manifest与Compression Pipeline；
- Evidence保护校验器；
- Memory隔离、压缩A/B和成本报告；
- 已更新的`PROGRESS.md`。

## Gate 06

- Memory隔离、TTL、删除和显式确认全部通过；
- 数字、单位和Evidence来源保留率100%；
- Context压缩效果、质量变化和额外费用均有数据；
- Validator通过率无不可接受退化；
- 用户审核Memory内容和Context策略。

## 停止条件

若压缩无法保证Evidence数字与引用一致，则只保留确定性裁剪，不上线模型摘要。
