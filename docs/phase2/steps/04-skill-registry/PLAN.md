# Step 04 — Skill Registry与首批研究/报告Skill

## 目标

将已验证的金融研究流程抽象为受控、版本化、可审计的Skill，以减少Prompt自由度，而不是引入可任意执行的插件系统。

## 前置条件

- Gate 03已通过；
- `SKILL_DESIGN.md`已审核；
- Tool、Evidence、Validator和Prompt均有稳定标识/版本。

## 子任务

1. 实现`SkillDefinition`、Trigger、Evidence Requirement、Workflow Constraint和版本引用Schema；
2. 建立Skill、Skill Version、Review、Activation和Run Snapshot业务表；
3. 实现`DRAFT → REVIEWED → ACTIVE → DEPRECATED`状态转移；
4. 实现只读Skill Registry加载、版本查询、校验和Snapshot；
5. 实现确定性候选过滤、可选结构化模型排序和最终程序校验；
6. 实现多Skill权限取交集、预算取更严限制和冲突拒绝；
7. 将Skill Selection加入Graph，无适用Skill时回退第一阶段默认流程；
8. 实现首批研究Skill：行情趋势、财务增长、盈利能力、综合个股研究；
9. 实现首批报告/审核Skill：研究报告检查、简版报告、风险优先报告；
10. 为每个Skill编写正例、反例、越权和缺Evidence测试；
11. 实现DRAFT导入和人工发布流程，不实现模型自动激活；
12. 对比Skill开/关的20题Regression和选择轨迹。

## 测试清单

- 只有ACTIVE版本可运行；
- Run中途Skill更新不改变当前Snapshot；
- 冲突Skill不得合并执行；
- Skill不能扩大Tool、Policy或Budget；
- 无Skill命中时默认流程仍可完成；
- DRAFT不能进入正式Run；
- 首批Skill的Evidence要求可被Validator验证。

## 交付物

- Skill Registry、Schema、数据库迁移和发布流程；
- 首批版本化Skill文件/记录；
- Skill选择节点与审计事件；
- Skill评测集和回归报告；
- 已更新的`PROGRESS.md`。

## Gate 04

- Skill选择结果可解释、可追溯；
- 越权、过期、冲突和DRAFT Skill全部被拦截；
- 首批Skill的必需Evidence覆盖率达标；
- 20题Regression不退化；
- 用户审核Skill内容与发布流程。

## 停止条件

若Skill选择导致经常性错误Tool路径或无法解释的回归退化，暂停报告Skill，先修正候选规则和组合语义。
