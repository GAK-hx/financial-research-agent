# Step 01 进度

- 状态：`IMPLEMENTED`
- 计划审核：已确认
- 实现开始：2026-08-08
- Gate 结论：`TECHNICAL_GO / RELEASE_BLOCKED`

## 已完成的前置变更

- [x] 默认模型配置、示例环境和 README 示例已改为 `deepseek-v4-flash`；
- [x] 已识别生产 Compose 固定评测日期问题；
- [x] 已识别相邻旧项目研报目录导致的不可独立克隆问题；
- [x] 已识别“最近一个完整交易月”语义对齐缺陷。

## 待执行

- [x] 生产/评测时钟分离与时间表达模型；
- [x] 原问题与 QuerySpec 语义对齐；
- [x] 报告 Evidence 支撑结构和 Validator；
- [x] 版本化评测 Manifest 与仓库外私有 Holdout 入口；
- [x] Git、CI、Secret 和数据发布规则；
- [x] Docker、PostgreSQL 与真实 Flash 集中验证；
- [x] 生成 Evidence、失败案例、运行手册和 Gate 报告；
- [ ] 用户轮换已暴露 Key；
- [ ] 用户提供私有 Holdout 并完成 ≥95% 泛化验收；
- [ ] 用户决定后创建首次 commit 和私有 GitHub remote。
