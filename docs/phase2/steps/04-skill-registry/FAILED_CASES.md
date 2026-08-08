# Step 04 评测失败明细

## 结论

最终20题为19/20，没有Provider网络失败，也没有Skill选择、Tool权限、Evidence要求
或持久化失败。唯一未通过的是已在Step 03出现的`eval-16`数字格式问题。

原始脱敏输出：

- `artifacts/phase2_step04/skill_gate/evaluation/runs/eval-16.json`
- `artifacts/phase2_step04/skill_gate/evaluation/evaluation_report.json`

## eval-16

问题：`600519今年行情与券商观点`

运行轨迹：

```yaml
selected_skill: comprehensive_stock_research@1.0.0
planner_source: model
tools:
  market_query: success
  report_search: success
  indicator_calculator: success
reporting_status: validation_failed
```

模型在预测数字中使用了`183,015.67`、`198,958.30`等千位分隔格式。当前数字
提取器把逗号两侧识别成多个数字片段，Validator因无法逐项证明而拒绝报告，例如：

```text
claim[5]:NUMERIC_UNSUPPORTED:183.0
claim[5]:NUMERIC_UNSUPPORTED:15.67
claim[6]:NUMERIC_UNSUPPORTED:86.0
claim[6]:NUMERIC_UNSUPPORTED:196.94
```

这不是Skill回归：该题在Step 03也失败；Step03/Step04结构语义对比无差异。当前
行为是安全的，未通过校验的数字没有被标记为成功报告。数字规范化修复应在后续
Validator专项中实现并回归，而不是在Step04放宽规则。
