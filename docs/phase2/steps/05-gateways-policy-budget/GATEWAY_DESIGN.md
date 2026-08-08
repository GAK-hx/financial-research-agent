# Step 05 Gateway设计

## 1. 为什么需要Gateway

LangGraph负责运行状态和节点跳转，但它本身不保证模型或Tool一定经过项目的权限、
预算和审计规则。Step 05把正式调用收口到两个Gateway：

```text
LangGraph Node
  → Policy授权
  → 逻辑调用预算Reserve
  → 幂等调用记录
  → 每次真实尝试的Policy + Attempt预算
  → Provider或Tool
  → Usage/结果审计
  → Commit或Release
```

模型仍然只负责规划和报告内容；真实数据只能由Tool Gateway调用已注册Tool读取。

## 2. Model Gateway

`ModelGateway`统一处理：

- 允许的模型操作：`plan`、`generate_report`、`revise_report`；
- Provider、Model、Prompt和Gateway版本记录；
- 逻辑模型调用与每次HTTP尝试分别计数；
- 网络/限流错误的有界重试；
- DeepSeek返回的输入、输出、缓存命中/未命中Token记录；
- 按配置价格计算人民币微元；
- Provider不返回Usage时标记`estimated=true`；
- 调用成功Commit，失败Release逻辑调用，但已发生的HTTP尝试仍Commit；
- 异常只持久化类型化错误码，不保存密钥、完整Prompt或隐藏推理。

逻辑调用和尝试分开计数很重要：网络失败不应伪装成一次成功业务调用，但真实发出的
请求必须占用Attempt预算，避免重试风暴。

## 3. Tool Gateway

`ToolGateway`统一处理：

- 只允许Registry中存在且被当前Skill允许的Tool；
- Pydantic参数校验；
- 只读、非模拟域、股票、日期和行数范围检查；
- 按Plan依赖关系调度；
- 全局与Skill并行数取更严格值；
- 每次执行前重新做Policy检查；
- Tool超时和瞬时数据源错误有界重试；
- 逻辑调用、实际尝试、版本、Policy决定和结果统一审计；
- 工具异常对外仅返回Tool名和异常类型，避免异常文本泄露敏感值。

依赖失败的Task不会执行，返回`DEPENDENCY_FAILED`。这类跳过不是实际Tool调用，
因此不消耗Tool Attempt。

## 4. 正式路径与兼容路径

正式Docker LangGraph运行时使用PostgreSQL Business Store，因此会初始化两个
Gateway。内存单元测试和旧版Legacy Runtime仍保留兼容分支，便于等价性回归；
它们不属于正式生产路径。

正式路径的集成测试会同时验证：

- 规划和报告产生两条Model Call；
- 财务取数产生一条Tool Call；
- 每条调用都带Gateway、Policy和Budget关联；
- Completion Checker通过且没有未结算Reservation。

## 5. 主要实现

- `governance/gateways.py`
- `providers/model.py`
- `governance/policy.py`
- `governance/store.py`
- `orchestration/langgraph_runtime.py`
- `persistence/models.py`
- `persistence/store.py`
