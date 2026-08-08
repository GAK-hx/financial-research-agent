# Skill选择与执行设计

## 1. 数据流

```text
Question
  → QueryInterpreter
  → ACTIVE候选过滤（Intent + Dimension）
  → 冲突与权限组合
  → Run Skill Snapshot
  → Planner
  → PlanValidator + Skill Tool/调用上限
  → Tool执行
  → EvidenceBuilder + Skill Evidence要求
  → 报告与原有Validator
```

无候选时回退第一阶段默认流程，原因记录为
`default_flow:no_active_skill`；通过`SKILLS_ENABLED=false`可做开关对照，原因记录
为`default_flow:skills_disabled`。

## 2. 为什么第一版不使用模型排序

首批目录只有七项，Intent和Dimension能确定候选。此时引入模型排序会增加一次
网络调用、非确定性和故障面，却没有足够候选量产生收益。Schema保留了以后增加
结构化排序的空间；若目录扩大，再让模型只在规则候选集中排序，最终结果仍须通过
程序校验。

## 3. 安全不变量

- 只有ACTIVE版本可选；
- Effective Tools始终是“系统可用Tool ∩ 每个Skill允许Tool”；
- 空交集、冲突组合、DRAFT和DEPRECATED均拒绝；
- Skill调用上限只能比全局更严格；
- Planner产生越界Tool时在执行前失败；
- 缺少必需Evidence时不进入报告生成；
- Snapshot保存版本、Checksum、约束和选择原因，Resume复用Checkpoint中的值。

## 4. 持久化边界

`skills`和`skill_versions`保存身份与不可变版本内容；`skill_reviews`、
`skill_activations`保存人工操作；`run_skill_snapshots`保存执行时副本；
`run_events.skill_selected`提供按Run查询的轻量审计轨迹。
