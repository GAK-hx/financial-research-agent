# Step 06 验收证据

状态：`PASSED`

## 自动化与集成

- 正式Docker镜像全量：115项测试通过；
- PostgreSQL Memory隔离、TTL、删除、版本冲突和API确认路径通过；
- LangGraph正式路径包含`load_memory`与`remember_query`；
- Context Manifest在Plan、Report、Revise节点生成并持久化；
- 一层摘要的新数字注入、Evidence Locator篡改均被测试拦截。

## 20题Regression

最终结果：

```text
Task Success          19/20
Intent                18/18
Tool Selection        18/18
Arguments             18/18
Citation              18/18
Numeric Consistency   17/18
P50 / P95             24.090s / 76.941s
Model Calls           38
```

与Step04最终基线19/20一致；唯一失败仍为`eval-16`的模型数字格式问题。首轮失败题仅
重试一次，首轮与最终结果均在`FAILED_CASES.md`说明。

## Memory与Context实测

- 同Session指代追问恢复`600519`，时间范围正确解析为最近三个月；
- 追问仍调用正式行情与指标工具，Validator通过；
- 真实追问Report Context由3711降至786，Evidence保护通过；
- 1000行受控A/B由13504降至241，来源、Snapshot、数字和单位保护通过；
- 模型摘要路径可用但默认关闭，因此本Gate无额外摘要模型费用。

## Gate 06

Memory隔离与用户控制、Context可追溯、Evidence保护、压缩效果和回归基线均达到
Step06要求。`Gate 06 = PASSED`，可以进入Step07。
