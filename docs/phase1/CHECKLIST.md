# 第一阶段总清单

## 设计门

- [x] 全部板块文档已审核
- [x] 十个步骤PLAN已审核
- [x] 关键决定已写入`../DECISIONS.md`
- [x] 第一版股票池确定
- [x] 复权和财务指标口径确定
- [x] RAG分块基线确定
- [x] Replan与模型降级策略确定
- [x] Docker优先部署原则确定

## 数据管理

- [x] Namespace和表结构确认
- [x] 批次元数据设计完成
- [x] 数据质量框架实现并测试（行情具体规则在Step 03补充）
- [x] Simulation与正式数据隔离
- [x] 数据来源和版本可追踪

## 行情与指标

- [x] 日线首次回填
- [x] 日线增量更新
- [x] 业务键去重
- [x] Market Tool
- [x] Indicator Tool
- [x] 指标手算测试

## 财务

- [x] 第一版报表范围确定
- [x] 字段映射和单位规则
- [x] 财务表写入
- [x] Financial Tool
- [x] 财务指标公式测试

## RAG

- [x] 6份PDF可解析
- [x] 页码和股票Metadata
- [x] 向量维度运行时探测
- [x] `research_reports_v1`
- [x] 股票过滤检索
- [x] 固定查询验证

## Agent编排

- [x] Query Interpreter
- [x] 规则Planner
- [x] 模型Planner
- [x] Plan Validator
- [x] Tool Registry
- [x] 并行Executor
- [x] Run/Working/Evidence Memory

## 报告与校验

- [x] Evidence Builder
- [x] 结构化Report
- [x] Entity/Date Validator
- [x] Citation Validator
- [x] Numeric Validator
- [x] 一次修订和失败返回

## API与可观测

- [x] `/health`
- [x] `/tools`
- [x] `/analyze`
- [x] 统一错误Schema
- [x] 结构化日志
- [x] 阶段timing和run_id

## 测试与验收

- [x] 单元测试
- [x] Iceberg集成测试
- [x] Milvus集成测试
- [x] API端到端测试
- [x] 20题最小评测集
- [x] 三条标准演示路径
- [x] README真实指标和限制
- [x] 所有步骤PROGRESS有验收证据
