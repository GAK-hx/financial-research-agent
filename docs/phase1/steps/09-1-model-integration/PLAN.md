# 临时Step 09.1 — 模型部署后的跨步骤补充验收

## 定位

这是进入Step 10前的一次临时补验，不是新的产品功能阶段。

前面各步骤是在“暂未配置生成式模型”的条件下逐步实现的，因此有些部分已经用真实数据和真实基础设施验收，有些部分只验证了接口、Mock输出或模型不可用时的降级。Step 09.1的任务是部署正式模型后，补验Step 07、08、09此前没有走通的真实模型路径，并确认Step 06的本地嵌入模型未受影响。

本步骤遵循两个原则：

1. 以验证为主，不提前开展Step 10的20题评测；
2. 只修复真实模型联调中发现的阻断问题，不在临时步骤中扩展多模型路由、复杂重试平台或新Agent框架。

## 前序步骤模型依赖审计

| Step | 模型依赖 | 当前真实验收情况 | 尚未验证的内容 | 09.1处理 |
|---|---|---|---|---|
| 01 设计规范 | 无运行时模型；只定义模型边界 | 设计和安全边界已确认 | 无 | 不重复验收 |
| 02 数据管理 | 无生成式模型 | Iceberg、批次、质量、隔离均真实验收 | 无 | 只跑回归 |
| 03 行情采集 | 无生成式模型 | 真实日线、Raw、幂等和质量审计已完成 | 无 | 只跑回归 |
| 04 行情/指标工具 | 无生成式模型 | 工具脱离LLM真实运行，指标确定性计算 | 无 | 只跑回归 |
| 05 财务工具 | 无生成式模型 | 真实财务数据、指标和Evidence已完成 | 无 | 只跑回归 |
| 06 RAG | 本地BGE嵌入模型 | BGE已在Docker实际运行，生成512维向量并写入88个Chunk | 生成式模型部署后是否仍能稳定检索 | 做轻量回归，不重建索引 |
| 07 Agent编排 | 生成式Planner | 规则Planner、InvalidProvider回退、Plan Validator和真实工具编排已验收 | 正式模型是否能输出可执行且合规的Plan | 核心补验 |
| 08 报告与校验 | 生成式Reporter | Mock Provider、手工`validation_only`草稿和确定性Validator已验收 | 正式模型能否生成/修订通过校验的报告 | 核心补验 |
| 09 API/可观测性 | 依赖Planner和Reporter | 真实HTTP、工具、Evidence、失败语义已验收；成功响应只用测试替身 | 正式模型参与的`success=true`端到端Run | 核心补验 |

## 已确认的验收缺口

### Step 07

- 真实Run均为`planner_source=rule_fallback`；
- 模型Planner成功路径没有实际调用过外部模型；
- 当前测试中的`InvalidProvider`只证明模型失败后可以安全回退；
- 尚未证明DeepSeek输出的任务名、参数、依赖关系能通过Plan Validator。

### Step 08

- 一次修订通过`SequenceProvider`模拟，没有调用真实模型；
- 真实Evidence的Validator审计使用手工构造草稿，并明确标记`validation_only=true`；
- 尚未证明正式模型会只使用当前Run Evidence、保留机构与页码、避免编造数字；
- 尚未证明模型收到校验错误后能完成一次有效修订。

### Step 09

- 三条真实API Artifact的工具与Evidence成功，但报告均为`generation_failed`；
- API单元测试中的`success=true`来自注入的测试结果，不是正式模型端到端结果；
- `/health`当前只证明模型配置字段是否非空，不能证明外部模型可调用。

## 输入条件

### 用户提供

1. 可调用DeepSeek V4的API Key，仅写入本地`.env`，不发送到聊天或写入文档；
2. 确认是DeepSeek官方API还是第三方OpenAI-compatible代理；
3. 若为第三方代理，提供Base URL、模型名和JSON Output兼容信息；
4. 允许进行约10～20次小规模付费调用，用于预检、四类Run和必要的一次修订验证。

### 默认配置

第一轮补验只使用一个模型，避免在验证阶段引入路由变量：

```env
MODEL_PROVIDER=openai_compatible
MODEL_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-v4-flash
MODEL_API_KEY=<仅保存在本地>
```

执行时按用户选择使用`deepseek-v4-flash`，本临时步骤不同时比较多个模型；模型对比属于Step 10。

## 分步计划

### 09.1.0 基线与密钥安全

1. 保存当前48项Docker测试基线；
2. 检查`.env`不会进入版本控制、Artifact或Docker镜像层；
3. 只通过Compose `env_file`向App容器注入Key；
4. 在容器内执行一次最小JSON请求，验证DNS、TLS、认证、模型名和JSON Output；
5. 检查应用日志及错误响应中没有API Key和Authorization Header；
6. 预检失败时停止付费E2E，先记录认证、余额、模型名或网络问题。

产物：一份脱敏预检结果，只记录时间、模型名、HTTP结果、延迟和Token用量（若API返回）。

### 09.1.1 Step 06嵌入模型回归

1. 不重新下载BGE、不重建Milvus Collection；
2. 确认`research_reports_v1`仍有88个Chunk、维度仍为512；
3. 重跑600519和300750两条固定检索；
4. 确认股票过滤、Top 1报告和页码与Step 06证据一致；
5. 记录生成式模型部署没有破坏App容器中的BGE查询能力和900MB资源边界。

判定：这是回归项。Step 06此前已真实部署BGE，不把它误标为“模型未部署”。

### 09.1.2 Step 07真实模型Planner补验

对Market、Financial、Report、Comprehensive四种意图各运行一条标准问题：

1. 确认Provider真实被调用，`planner_source=model`；
2. 确认输出可以解析为`AnalysisPlan`；
3. 确认工具全部来自Registry白名单；
4. 确认股票、日期、参数与`QuerySpec`一致；
5. 确认Market→Indicator依赖，以及Comprehensive中Market/Report并行关系；
6. 通过Plan Validator后再执行真实工具；
7. 确认不同Run的Working/Evidence Memory仍然隔离；
8. 增加一条提示注入/越权问题，确认模型不能调用未知工具、SQL或Python。

判定规则：

- 四类中每一类都必须至少有一次`planner_source=model`且工具执行成功；
- 若回退规则Planner，Run可以继续，但该题的“模型Planner补验”不算通过；
- 模型输出不合规但被Validator拦截，安全边界算通过，模型可用性仍需修正后复测。

### 09.1.3 Step 08真实Reporter与修订补验

使用真实工具产生的四域Evidence，不使用手写正式报告：

1. 分别生成Market、Financial、Report和Comprehensive正式报告；
2. 确认Reporter输入只包含`QuerySpec`和当前Run Evidence；
3. 确认输出通过ResearchReport Pydantic Schema；
4. 确认Entity、Date、Citation、Attribution、Numeric和Completion校验全部通过；
5. 确认每个关键Claim至少引用一个当前Run Evidence ID；
6. 确认报告没有出现Evidence中不存在的关键数字或其他股票事实；
7. 对一份合法Evidence构造带明确校验错误的错误草稿，调用真实模型执行一次修订；
8. 确认修订使用错误反馈、最多一次，修订后通过或明确`validation_failed`；
9. 模型不可用时仍不得用模板报告冒充成功。

判定规则：四类标准报告必须生成，且确定性Validator全部通过；真实修订至少完成一次可审计调用。若修订仍失败，记录为模型能力缺口，不能把Mock测试结果当作真实通过。

### 09.1.4 Step 09真实API成功链路补验

通过Docker暴露的HTTP API运行四条请求，而不是直接调用内部Service：

1. `/health`显示配置完整，并通过独立模型预检证明可调用；
2. `/tools`仍只公开四个只读工具；
3. Market、Financial、Report、Comprehensive均返回HTTP 200；
4. 每条响应必须为`success=true`、`reporting_status=completed`；
5. 响应包含Plan、逐工具状态、Evidence、正式Report、Validation、timings和版本；
6. `run_id`贯穿Evidence ID、错误、日志和Artifact；
7. 日志能区分模型规划、规则回退、工具执行、报告生成和校验耗时；
8. 保存四条脱敏成功Artifact，替代此前只能证明失败边界的三条Artifact作为补充证据；
9. 旧的`generation_failed` Artifact保留，用于证明无模型时的正确失败语义。

### 09.1.5 最小兼容修正与回归

联调中只允许修复阻断真实验证的问题，例如：

- DeepSeek JSON Output所需的明确JSON指令、最小Schema示例和`max_tokens`；
- 空内容、截断JSON或响应字段差异的明确处理；
- 模型读取超时必须服从Run剩余总预算；
- Planner回退原因和模型调用结果的必要日志；
- 报告Schema解析失败进入现有的一次修订边界。

以下内容不在临时步骤扩展：多模型自动路由、成本优化器、完整重试平台、SSE、Langfuse和Harness。

修正后：

1. 新增真实Provider兼容性测试的Mock覆盖，真实付费测试保持显式运行，不能混入普通单元测试；
2. 重跑全部Docker测试；
3. 重跑受影响的四类真实Run；
4. 核对App、Milvus和etcd资源没有超过Compose限制。

### 09.1.6 回写原步骤与审核

1. 新建Step 09.1 `EVIDENCE.md`，汇总预检、四类Plan、四类Report、四类API Run和资源结果；
2. 在Step 07进度中回写真实模型Planner补验结果；
3. 在Step 08进度中回写真实Reporter和真实修订结果；
4. 在Step 09进度中回写真实`success=true` API结果；
5. Step 06只追加回归结果，不改写原先BGE已完成的历史结论；
6. 明确区分单元/Mock、真实数据、真实基础设施和真实生成式模型四类证据；
7. 用户审核通过后解锁Step 10。

## 最终验收门槛

- DeepSeek模型在App容器内可调用，密钥无泄露；
- Step 06两条固定RAG查询回归通过；
- Step 07四类真实模型Plan均至少成功一次且通过Validator；
- Step 08四类正式报告全部通过确定性校验，并完成一次真实修订调用；
- Step 09四类HTTP Run均为`success=true`；
- 无模型时的规则降级和报告明确失败语义仍然有效；
- 全部Docker测试通过且资源未超限；
- Step 07、08、09的模型补验状态均有可复核Artifact；
- 用户审核后才进入Step 10。

## 与Step 10的边界

Step 09.1回答：“此前未运行的真实模型路径现在能否正确走通？”

Step 10回答：“这条已经走通的链路在20题中有多准、多稳、多快，是否达到第一阶段完成标准？”

因此Step 09.1只做少量标准样例和必要修正；Intent、Tool Selection、Argument、Citation、Numeric、Task Success、P50/P95的正式统计仍属于Step 10。
