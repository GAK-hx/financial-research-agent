# Step 08最终评测报告

评测日期：2026-07-26  
状态：`PASSED_WITH_MODEL_TIER_CONSTRAINT`

## 1. 结论

Gate 08通过。LangGraph编排、Skill选择、受控Tool执行、Evidence链、Memory/Context、
Policy/Budget和Worker恢复路径均达到本阶段门槛。正式质量档位使用
`deepseek-v4-pro`；`deepseek-v4-flash`适合低成本开发回归，但当前不作为正式报告模型。

所有模型报告仍经过引用、实体、日期和数字一致性校验。自动修复最多执行一次；修复后
仍不通过则保持`validation_failed`，不会把有疑问的报告作为成功结果返回。

## 2. 数据集与可复现信息

| 集合 | 版本 | SHA-256 | 数量 |
|---|---|---|---:|
| Regression | `phase1_eval_v1` | `17c242d024ea8bddee3bbc9d63fabfaecd5415106209267835230a8b0bb75f34` | 20 |
| Holdout | `phase2_holdout_v1` | `85dce36a0be6531fd3f575eea9fe0e06ae7acff2f13b86acfc07d508a920ca03` | 30 |
| Stability | `phase2_stability_v1` | `f00fdb33683f0df15d69510b09d793dc0df553a31a1871842e5175de337d117c` | 10×3 |

统一参考日期为`2026-07-15`，编排运行时为LangGraph，Planner和Report Prompt版本分别为
`planner_v2`、`report_v2`。

## 3. 正式结果

### Regression / V4 Pro

- 20/20通过，任务成功率100%；
- Intent、Skill、Tool、参数、Evidence覆盖、引用、数字和Budget闭合均为100%；
- P50 19.215秒，P95 108.299秒；
- 36次模型调用，133,590 Token，估算费用424,489微元。

### Holdout / V4 Pro

- 29/30通过，任务成功率96.67%，达到`≥90%`门槛；
- Intent、Skill、Tool、参数、Evidence覆盖、引用和Budget闭合均为100%；
- 数字一致率与Completion通过率均为96.43%，达到审核后`≥95%`门槛；
- P50 19.888秒，P95 68.489秒；
- 60次模型调用，224,377 Token，估算费用707,584微元。

唯一失败报告被校验器阻断。后续已修复价格区间`1323.69-1634.99元`被误判为负数的
解析边界，并对原题做真实模型复测，结果100%通过；原始失败产物仍保留。

### Stability / Harness稳定性

修复后使用V4 Flash完成10题×3次多轮评测：

- Skill集合一致率100%；
- Tool集合一致率100%；
- Evidence集合一致率100%；
- Evidence结构化数字一致率100%；
- 报告必需字段与核心板块一致率100%；
- Budget闭合率100%。

稳定性提升来自Harness对实际取数参数的确定性归一化：模型仍决定任务类型和DAG，
但股票、日期、复权方式、研报检索原问题及Top-K由Harness固定。这样避免模型改写检索词
导致同一问题命中不同Milvus片段。

## 4. 模型档位结论

| 模型 | 用途 | 实测结论 |
|---|---|---|
| DeepSeek V4 Pro | 少量关键可行性、正式质量基线 | Holdout 96.67%；缺陷题3次复测100% |
| DeepSeek V4 Flash | 大规模开发回归、多轮稳定性 | 编排与Evidence轨迹100%稳定；端到端报告通过率70% |

Flash的9次失败均由报告校验或Completion安全拦截，未出现越权、错误引用被放行或Budget
未闭合。当前推荐“Flash做便宜回归，Pro做正式报告和关键验收”，不能用Flash结果替代
Pro质量基线。

## 5. A/B结果

- Skill开启时，28个合法Holdout问题的预期Skill匹配率为100%；关闭后不再产生Skill约束；
- Memory开启时可将“继续分析它近3个月的走势”解析为会话中的`600519`，关闭时解析失败；
- Context Compression将估算Token从13,523降至260，压缩比约1.92%；
- 压缩前后Evidence保护均通过，来源与数字未进入摘要改写路径。

## 6. 故障、安全与治理

最终容器测试共137项通过、19项按环境条件跳过。已覆盖：

- 模型连接错误、协议中断、429和退避重试；
- 未分类客户端异常后的Attempt预算清理；
- Worker Lease丢失、恢复、唯一终态与重复执行保护；
- 并发Budget预留、耗尽、释放和幂等结算；
- Prompt Injection未知参数、Skill升权、写操作和Simulation拒绝；
- 跨Tenant/User Memory隔离、敏感字段递归脱敏；
- 伪造引用、错误主体、错误日期和不受支持数字拦截；
- Context压缩Evidence保护和SSE游标续传。

阻断指标中，越权成功、跨域Memory泄漏、Evidence来源丢失、重复副作用、Budget超限和
严重凭证泄漏均为0。

## 7. 资源基线

空闲到低负载采样：

| 服务 | CPU | 内存 |
|---|---:|---:|
| LangGraph API | 0.39% | 523.6 MiB / 1000 MiB |
| PostgreSQL | 0.27% | 125.4 MiB / 512 MiB |
| Milvus | 8.02% | 567 MiB / 1.758 GiB |
| etcd | 1.08% | 57.6 MiB / 256 MiB |

评测后PostgreSQL数据库体积约70 MB。资源数据用于后续基线比较，不作为跨硬件性能承诺。

## 8. 已知限制

- 当前正式能力只覆盖数据底座已有的`600519`和`300750`；
- Flash在严格报告校验下通过率不足，不应承担正式报告生成；
- 19项跳过测试依赖本地未提供的可选外部集成环境，不影响本次核心单元和容器验收；
- FastAPI仍有`on_event`弃用告警，可在后续维护中迁移到Lifespan，不属于Gate 08阻断项。

