# Step 01技术验证与兼容性报告

## 1. 结论

结论：`TECHNICAL_GO_WITH_RECORDED_RISKS`。

LangGraph 1.2.9与项目Python 3.11、Pydantic v2、现有异步Tool接口、Structured/Rule Planner、Plan Validator、Evidence Builder和DeepSeek Adapter兼容，可以进入Step 02的“等价迁移”设计审核。

本结论不代表已经切换正式运行时，也不代表20题实时模型链路可以在外部网络波动下稳定达到20/20。

## 2. 实现范围

新增了旁路`financial_research_agent.harness`实验模块和Docker Compose `harness` profile：

```text
interpret
→ plan
→ validate_plan
→ [interrupt / resume]
→ execute_tools
→ build_evidence
→ build_report_preview
```

正式`OrchestrationService`、`ResearchService`、`POST /analyze`和当前运行中的`app`容器没有切换到LangGraph。

## 3. 依赖与Docker

| 检查 | 结果 |
|---|---|
| Python | 3.11 |
| LangGraph | 1.2.9 |
| Checkpointer | InMemorySaver |
| Harness镜像构建 | 通过 |
| Harness `pip check` | `No broken requirements found` |
| App镜像重新构建 | 通过 |
| Compose配置校验 | 通过 |
| 在线App | 原容器继续健康运行，未重启 |

LangGraph 1.2.9引入`langchain-core`等传递依赖，但未安装`langchain`高层Agent。`langgraph-sdk`将Harness镜像的`websockets`约束到15.x；由于Step 01使用隔离镜像，该变化未进入正式App镜像。Step 02正式合并依赖前需再次运行完整API/SSE兼容测试。

## 4. 自动化测试

### 迁移前基线

```text
69 tests
69 passed
```

### LangGraph专项

```text
5 tests
5 passed
```

覆盖：

- Pydantic对象在节点边界转换为JSON-safe Graph State；
- InMemorySaver保存状态；
- interrupt前不执行Tool；
- 使用同一Thread ID恢复；
- 拒绝进入显式终态且Tool调用为0；
- 完成后再次读取/恢复不重复Tool调用；
- 异步Tool执行期间事件循环仍响应；
- 非JSON对象在Checkpoint前被拒绝。

### 最终App镜像

```text
75 tests
70 passed
5 skipped
```

5个Skip是LangGraph专项在未安装Harness依赖的正式App镜像中的预期隔离结果；同一5项已在Harness镜像全部通过。

## 5. 真实集成验证

路径：

```text
LangGraph
→ QueryInterpreter
→ DeepSeek Structured Planner
→ AnalysisPlan Pydantic校验
→ PlanValidator
→ 现有FinancialQueryTool
→ Iceberg
→ EvidenceBuilder
```

结果：

```json
{
  "stage": "completed",
  "planner_source": "model",
  "tool_success": [true],
  "evidence_count": 1,
  "errors": []
}
```

输出只记录Run ID、状态、工具成功状态和Evidence数量，没有记录API Key或完整Provider响应。

## 6. 20题Regression

### 首次发现：评测时钟未冻结

评测集`phase1_eval_v1`的`as_of_date`为2026-07-15，但生产解释器默认使用运行当天。2026-07-24直接运行时，“最近一年”等相对日期与固定预期不一致。

已增加显式`EVALUATION_REFERENCE_DATE`：

- 生产默认不设置，仍使用真实当天；
- 完整评测必须与数据集`as_of_date`一致，否则立即拒绝运行；
- 评测报告记录参考日期；
- 临时评测API使用2026-07-15，正式在线API未修改。

### 冻结日期后的首轮

```text
Intent              18/18
Tool Selection      18/18
Arguments           18/18
Citation            13/18
Numeric             12/18
Task Success        13/20
```

7个失败中，6个与DeepSeek域名临时DNS解析失败相关，1个是模型生成了Evidence不支持的数字并被Validator拦截。

### 仅重跑7个失败用例一次

```text
Intent              18/18
Tool Selection      18/18
Arguments           18/18
Citation            17/18
Numeric             17/18
Task Success        17/20
```

剩余3题：

| Case | 原因 | 系统行为 |
|---|---|---|
| eval-11 | Reporter请求临时DNS失败 | 明确`generation_failed`，未伪造报告 |
| eval-12 | Planner请求临时DNS失败 | 使用规则Plan；Tool、Evidence、Report和Validation成功，但评分器要求Planner必须为模型 |
| eval-16 | 模型报告实体不一致 | Validator拦截并返回`validation_failed` |

机器可读结果：

```text
artifacts/phase2_step01/frozen_20260715/evaluation/evaluation_report.json
artifacts/phase2_step01/frozen_20260715/evaluation/runs/eval-01.json ... eval-20.json
```

因此，本轮证明确定性解释、工具选择和参数没有退化，但同时证明第一阶段实时模型评测缺少Provider网络重试与稳定性统计。Model Gateway重试、费用和预算仍按计划放在Step 05；Step 01不越级实现。

## 7. 已确认边界

- LangGraph管理图运行和Checkpoint，不替代业务幂等；
- Graph State不保存Client、连接、DataFrame、协程、锁或密钥；
- interrupt节点与副作用节点分离；
- 模型不能直接创建Evidence；
- 报告预览明确标记`production_report=false`；
- Step 01使用InMemorySaver，PostgreSQL Checkpoint仍属于Step 03；
- Replan仍为0；
- 正式研究工具仍全部只读。

## 8. 风险与Step 02进入条件

| 风险 | 处置 |
|---|---|
| Provider DNS/限流导致Planner降级或Reporter失败 | Step 05 Model Gateway实现有界重试、错误分类和预算；Step 02继续保留现有显式失败语义 |
| 模型输出存在单次波动 | Step 08执行10题各3次稳定性；Validator继续阻断不合法报告 |
| LangGraph传递依赖约束`websockets` | Step 02合并正式镜像前执行API、SSE和全量依赖测试 |
| InMemorySaver不跨进程 | Step 03使用AsyncPostgresSaver，不把Spike能力描述为生产持久化 |
| 20题已经是回归集 | Step 08另建至少30题Holdout，不将17/20或历史20/20解释为泛化准确率 |

进入Step 02前仍需用户审核：

1. 接受`STATE_AND_BOUNDARIES.md`；
2. 接受技术兼容性为Go；
3. 接受Provider网络与模型稳定性风险进入后续既定步骤，而不是在Step 01扩大范围。
