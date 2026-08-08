# Step 02实现证据

状态：`READY_FOR_REVIEW`。最终镜像、全量回归、20题对照和真实API均已完成。

## 1. 已实现

- 正式`ResearchGraphState`，Checkpoint内容为JSON安全数据；
- Interpret、Plan、Plan Validation、Tool Execution、Evidence、Report、Report Validation、一次修订和Finalize节点；
- 所有Graph条件边由程序控制，模型不能选择下一节点；
- Tool Registry、Plan Validator、PlanExecutor、Evidence Builder和Report Validator均复用第一阶段实现；
- 唯一Finalize节点和`terminal_writes=1`约束；
- `legacy/langgraph`配置切换，默认`legacy`；
- API延迟导入LangGraph，未安装Harness依赖的正式App仍可启动；
- Docker `langgraph-app`旁路服务，默认端口8001，内存上限1000 MB；
- 新旧评测产物比较器。

## 2. 已执行的可行性证据

### 最终镜像全量回归

```text
81 tests
81 passed
0 skipped
0 failed
```

该次执行位于最终`financial-research-agent-langgraph-app:latest`镜像，包含第一阶段全量、LangGraph正式运行时、Step 01 Spike和评测比较器测试。覆盖完整成功路径、报告一次修订、Tool全部失败、单一终态写入、JSON安全Checkpoint及旧/新运行时语义比较。

### 真实API链路

问题：

```text
分析贵州茅台最近三年的营收和利润
```

结果摘要：

| 项目 | 结果 |
|---|---|
| HTTP/API | `success=true` |
| 运行时 | LangGraph |
| Planner | DeepSeek `deepseek-v4-flash`，`planner_source=model` |
| Tool | `financial_query`成功 |
| 数据 | Iceberg `financial.metrics`，11个报告期 |
| 报告 | 生成成功 |
| Validator | `passed=true` |
| 总耗时 | 约12.3秒 |

链路证明模型计划、StateGraph、受控Tool、Iceberg、Evidence、报告生成和确定性校验可以在同一Run中工作。

### 最终Docker服务

```text
configuration ready
model configured
iceberg ready
milvus ready
```

最终`langgraph-app`镜像构建成功，RAG/PyTorch层复用缓存，固定安装`langgraph==1.2.9`。Gate容器使用`ORCHESTRATION_RUNTIME=langgraph`和冻结评测日期启动。

## 3. 20题Regression

首次完整执行：

```text
Intent              18/18
Tool Selection      18/18
Arguments           18/18
Citation            13/18
Numeric             13/18
Task Success        13/20
```

7个失败均进入合法受控终态。检查发现其中4个原本在legacy最终基线成功的用例受到本轮DeepSeek连接超时或DNS失败影响。按验收规则仅重试这4题一次：

```text
Intent              18/18
Tool Selection      18/18
Arguments           18/18
Citation            15/18
Numeric             15/18
Task Success        16/20
P50                 16.222s
P95                 39.623s
```

最终4个失败：

| Case | 结果 | 归因 |
|---|---|---|
| eval-10 | Tool和5条Evidence成功，Report失败 | DeepSeek DNS失败 |
| eval-11 | Tool和5条Evidence成功，Report失败 | DeepSeek DNS失败 |
| eval-12 | Tool、Evidence、Report和Validator成功，但Planner为规则降级 | DeepSeek Planner DNS失败，评分器要求`planner_source=model` |
| eval-16 | 3个Tool和7条Evidence成功，Report失败 | DeepSeek DNS失败 |

因此确定性部分仍为18/18；失败没有来自Graph条件边、工具越权、Evidence丢失或Validator绕过。Provider重试和稳定性仍按计划由Step 05 Model Gateway解决。

机器可读产物：

```text
artifacts/phase2_step02/langgraph_gate/evaluation/evaluation_report.json
artifacts/phase2_step02/langgraph_gate/evaluation/runs/eval-01.json ... eval-20.json
artifacts/phase2_step02/langgraph_gate/runtime_comparison.json
```

## 4. 已发现并修正

| 问题 | 判断 | 处理 |
|---|---|---|
| 旧运行时Tool参数在内存中含`date`，Checkpoint中为ISO字符串 | 序列化表示差异，不是API语义差异 | 等价比较统一使用`model_dump(mode="json")` |
| Evidence节点计时最初显示为`completed` | 可观测性字段错误 | 计时保持`building_evidence`，运行终态单独设为`completed/failed` |
| RAG和Harness合并profile导致PyTorch层缓存失效 | Docker构建分层不合理 | 改为`INSTALL_PROFILE`与`INSTALL_HARNESS`两个正交参数 |
| Docker镜像代理出现哈希不一致、401和TLS超时 | 外部构建环境故障 | 未修改依赖哈希；最终Gate重试可复现构建 |

## 5. 与旧运行时的最终差异

| 项目 | Legacy | LangGraph Step 02 |
|---|---|---|
| 跨阶段状态 | Python上下文 | JSON安全Graph State |
| Checkpoint | 无 | InMemorySaver |
| Tool DAG/并发 | PlanExecutor | 同一PlanExecutor，封装为Graph节点 |
| 报告修订 | Service内分支 | 显式条件边 |
| 终态 | Service返回 | 唯一Finalize节点 |
| 日期内存表示 | `date`对象 | Checkpoint内ISO字符串 |
| API Schema | 原Schema | 不变 |
| 默认启用 | 是 | 否，显式配置后启用 |

20题逐题比较结果：

- 20/20产物齐全，无缺失；
- 16个双方均成功的用例，Intent、股票、Tool Trace、Tool结果、Evidence类型/主体、报告结构、Validator结果全部一致；
- 唯一legacy成功而LangGraph本轮失败的`eval-10`明确为Provider DNS失败；
- legacy与LangGraph共同失败的3题也均为Provider连接/降级问题；
- 未发现LangGraph业务语义回归。

## 6. Gate 02结论

结论：`TECHNICAL_GO_WITH_RECORDED_PROVIDER_RISK`。

通过项：

- 最终镜像可构建；
- 81/81测试通过；
- 20题全部进入合法终态；
- 确定性Intent、Tool和参数18/18；
- 双方成功用例16/16语义一致；
- Tool/Evidence/Validator边界未改变；
- 模型不能自由选边或绕过工具；
- 同步`POST /analyze`Schema未改变；
- `legacy`回退路径仍保留。

未作为Step 02阻塞项：

- DeepSeek DNS/连接稳定性；
- `InMemorySaver`不能跨进程恢复；
- Tool逐调用持久化幂等。

三项分别已进入Step 05、Step 03和Step 03/05。下一步仅等待用户审核Gate 02，不提前开始Step 03。
