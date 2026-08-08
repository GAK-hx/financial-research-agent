# Step 02新旧运行时差异报告

## 结论

在最终20题产物中，16个legacy与LangGraph均成功的用例具有完全一致的结构化语义；未发现由StateGraph迁移造成的Tool、Evidence、报告结构或Validator回归。

## 对照口径

逐题比较以下字段：

- Intent和股票代码；
- Tool名称序列及逐Tool成功状态；
- Evidence类型和主体；
- 报告是否存在及顶层字段；
- Validator是否通过；
- 受控错误码。

日期和Tool参数统一比较API JSON表示，避免将内存`date`对象与Checkpoint ISO字符串误判为差异。

## 结果

| 项目 | 结果 |
|---|---:|
| 总用例 | 20 |
| 产物缺失 | 0 |
| 双方成功 | 16 |
| 双方成功且语义完全一致 | 16 |
| LangGraph恢复legacy失败 | 0 |
| legacy成功而LangGraph本轮失败 | 1 |

唯一表面回归为`eval-10`：

- Planner因DeepSeek DNS失败使用规则降级；
- `report_search`成功；
- 返回5条合法Evidence；
- Reporter再次遇到DeepSeek DNS失败；
- 系统返回`REPORT_GENERATION_FAILED`，没有生成模板报告或绕过校验。

该差异属于已知Provider网络波动，不是Graph迁移差异。相同类型错误也出现在Step 01 legacy评测的`eval-11/12`。

## 结构差异

| 差异 | 影响 |
|---|---|
| LangGraph State中的日期为ISO字符串 | API输出一致；Tool输入会重新经过Pydantic校验 |
| 综合计划的Tool结果按Plan顺序输出 | Tool集合、依赖和Evidence一致；执行并发语义由同一PlanExecutor保证 |
| 报告生成与修订成为显式Graph节点 | 对外ReportingResult一致，可观测路径更清楚 |
| 唯一Finalize节点记录`terminal_writes=1` | 新增终态一致性保护，不改变API |
| LangGraph使用InMemorySaver | 仅适合当前单进程预览；Step 03迁移PostgreSQL |

## 机器可读报告

```text
artifacts/phase2_step02/langgraph_gate/runtime_comparison.json
```
