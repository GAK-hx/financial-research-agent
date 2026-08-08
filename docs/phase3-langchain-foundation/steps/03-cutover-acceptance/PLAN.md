# Step 03 — 正式路径切换与集中验收

## 目标

将LangChain路径设为默认正式路径，集中完成必要测试、Docker演示和文档更新，
确认框架调整未破坏已经跑通的项目能力。

## 实施内容

1. 将API和Worker默认切换到LangChain/LangGraph正式路径；
2. 检查并删除确认无用的重复入口和临时适配代码；
3. 保留必要回退配置，避免网络或模型兼容问题阻断演示；
4. 集中运行受本次修改影响的单元和集成测试；
5. 运行核心Regression，不重新扩张无意义测试集；
6. 对模型相关流程进行少量Pro可行性测试和必要的Flash重复验证；
7. 验证PostgreSQL Checkpoint、Gateway、Budget、Memory和恢复；
8. 验证Document—Artifact—Evidence—Claim来源链；
9. 使用Docker Compose从空环境完成端到端运行；
10. 失败案例保存输入、节点轨迹和模型原始输出到Markdown；
11. 对比迁移前后成功率、Validator通过率、Token和延迟；
12. 更新README、架构、组件介绍、Demo Script和简历口径。

## 集中验收标准

- LangChain标准接口实际进入默认路径；
- LangGraph仍是正式状态化运行时；
- 所有Model/Tool调用继续经过Gateway；
- 核心评测成功率达到95%；
- Evidence数字和来源保护保持100%；
- API、Worker、Checkpoint和Docker演示可用；
- 不存在阻断性缺陷。

## Gate 03

- 代码、运行路径和项目介绍均以LangChain/LangGraph为基础；
- 现有金融增强能力保留；
- 集中验收通过；
- 用户完成最终人工审核。
