# 第二阶段LangGraph Harness总实施计划

## 目标

将第一阶段Agent编排迁移到LangGraph持久化运行时，在不破坏Tool/Evidence/Validator边界的前提下，增加受控Skill、Gateway、Policy/Budget、Memory/Context Compression、Job API、恢复与评测。

## 九步实施顺序

```text
01 设计规范与LangGraph技术验证
  ↓
02 StateGraph迁移与第一阶段等价性
  ↓
03 PostgreSQL Checkpoint与业务持久化
  ↓
04 Skill Registry与研究/报告Skill
  ↓
05 Model/Tool Gateway、Policy与Budget
  ↓
06 Memory与Context Compression
  ↓
07 Job API、Worker、SSE与可观测
  ↓
08 恢复/安全/Regression/Holdout评测
  ↓
09 阶段验收与交付
```

| 步骤 | 核心产出 | 进入下一步前必须证明 | 详细计划 |
|---:|---|---|---|
| 01 | 规范、依赖决定、最小LangGraph Spike | 与Pydantic/异步Tool/DeepSeek兼容 | `steps/01-design-spike/PLAN.md` |
| 02 | 完整StateGraph和新旧运行时切换 | 20题行为等价，Tool/Evidence边界不变 | `steps/02-langgraph-runtime/PLAN.md` |
| 03 | PostgreSQL Checkpoint、业务Store和恢复 | 重启可恢复，无重复副作用 | `steps/03-postgres-checkpoint/PLAN.md` |
| 04 | Skill Registry、生命周期和首批Skill | 选择可解释，越权/DRAFT全拦截 | `steps/04-skill-registry/PLAN.md` |
| 05 | Model/Tool Gateway、Policy/Budget、Completion | 正式调用无Gateway绕过路径 | `steps/05-gateways-policy-budget/PLAN.md` |
| 06 | Session/Preference Memory与Context Compression | 跨用户隔离，数字/来源保留100% | `steps/06-memory-context/PLAN.md` |
| 07 | Job API、SSE、API/Worker和可观测 | 双Worker无重复Attempt与副作用 | `steps/07-api-worker-observability/PLAN.md` |
| 08 | 故障/安全测试与20+30+10×3评测 | 阻断性缺陷清零，阈值有实测数据 | `steps/08-reliability-evaluation/PLAN.md` |
| 09 | 空环境验收、手册、演示和总结 | 可复现证据完整并人工签字 | `steps/09-acceptance/PLAN.md` |

每步实时进度记录在同目录`PROGRESS.md`。未通过当步Gate时，不并行开始后续业务能力。

## Gate A：架构与可行性

- LangGraph/Pydantic/DeepSeek/现有异步Tool兼容；
- Graph State保持JSON安全序列化；
- 20题使用InMemorySaver不退化；
- Skill、Memory、Policy和Checkpointer边界审核。

## Gate B：持久化图运行

- 第一阶段节点全部迁移到StateGraph；
- AsyncPostgresSaver保存和恢复；
- 业务Run/Event/Budget与Checkpoint分离；
- 节点外部调用使用LangGraph Task和业务幂等键。

## Gate C：Skill与治理

- Skill选择、版本、权限和Evidence要求可审计；
- Model/Tool只能经Gateway调用；
- Policy和Budget调用前后生效；
- Skill不能扩大Tool权限或绕过Validator。

## Gate D：Memory与服务化

- Session/Preference/Skill Memory分层；
- Context压缩不丢失Evidence来源；
- Job API、SSE、Cancel/Resume可用；
- API与Worker拆分，双Worker不重复执行。

## Gate E：验收

- 第一阶段20题Regression不退化；
- 至少30题独立Holdout；
- 10题三次稳定性；
- 恢复、幂等、Policy、Budget、Memory隔离通过；
- Token、费用、P50/P95和资源披露；
- 用户人工审核。

## 实施原则

1. 先等价迁移，再增加Skill和Memory，不同时重写所有层；
2. LangGraph管理运行状态，业务Store管理治理记录；
3. Tool、Evidence、Validator继续框架无关；
4. Skill先人工维护，自动生成只产出DRAFT；
5. Context压缩只改变模型视图，不改变Evidence事实；
6. 每一步保留第一阶段Regression；
7. 第二阶段仍全部研究工具只读，Replan为0。

## 最终交付物

- LangGraph StateGraph和AsyncPostgresSaver；
- 金融Skill Registry与首批Skill；
- Model/Tool Gateway；
- Policy/Budget Ledger；
- Session/Preference Memory和Context Compression；
- Job API、SSE、Worker、Cancel/Resume；
- 恢复/安全/Holdout评测；
- Docker Compose、README、运维和阶段报告。
