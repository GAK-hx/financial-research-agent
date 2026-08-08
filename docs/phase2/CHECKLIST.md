# 第二阶段验收清单

## 设计与技术验证

- [x] LangGraph运行时边界设计
- [x] Graph State与节点设计
- [x] Checkpoint/业务Store边界设计
- [x] Skill Schema与生命周期设计
- [x] Memory/Context压缩策略设计
- [x] LangGraph最小Spike技术验证
- [x] 用户审核Step 01并关闭Gate 01

## Graph与持久化

- [x] 第一阶段节点等价迁移
- [x] InMemorySaver Regression
- [x] AsyncPostgresSaver
- [x] 状态加密
- [x] 业务Run/Event/Call表
- [x] Interrupt/Resume
- [x] 节点幂等

## Skill

- [x] Skill Registry
- [x] Skill版本与状态
- [x] 研究Skill
- [x] 报告Skill
- [x] Tool/Evidence约束
- [x] DRAFT审核与发布

## Gateway与治理

- [x] Model Gateway
- [x] Tool Gateway
- [x] Policy Engine
- [x] Budget Reserve/Commit/Release
- [x] Token/费用
- [x] Completion Checker

## Memory与Context

- [x] Run/Working/Evidence Memory
- [x] Session隔离与30天TTL
- [x] Preference显式写入
- [x] Memory查询和删除
- [x] 节点/Skill Context Policy
- [x] 压缩来源和版本
- [x] Evidence保护

## API与部署

- [x] Job API
- [x] SSE
- [x] Cancel/Resume
- [x] 同步兼容
- [x] API/Worker拆分
- [x] PostgreSQL Compose
- [x] 双Worker无重复执行

## 评测与验收

- [x] 第一阶段20题Regression
- [x] 30题未见Holdout
- [x] 10题三次稳定性
- [x] Worker/DB/模型/工具/预算故障注入
- [x] 恢复成功率和重复Evidence率
- [x] Skill选择与Policy拦截准确率
- [x] Memory隔离与压缩质量
- [x] P50/P95、Token、费用和资源
- [ ] 用户人工审核

## 阶段交付

- [x] Docker构建、迁移、健康检查与正式Run
- [x] PostgreSQL备份恢复演练
- [x] Memory TTL、查询、清理和删除手册
- [x] Checkpoint与Artifact保留边界
- [x] Job API、Worker、Events和Trace演示
- [x] 最终技术交付说明
- [x] 已知限制与后续候选
