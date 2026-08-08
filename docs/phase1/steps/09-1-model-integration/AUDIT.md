# Step 01～09 模型部署缺口审计

## 结论

此前“完成”代表对应代码边界、真实数据链路或降级路径已经达到该步骤的验收标准，不代表所有生成式模型成功路径都已运行。

- Step 01～05不使用生成式模型，结论不受影响；
- Step 06的BGE是嵌入模型，已经在Docker中真实部署并完成索引与检索；
- Step 07的模型Planner只有适配器、Mock失败和规则回退证据，没有真实外部模型成功证据；
- Step 08的正式Reporter只有Mock Provider与手工校验草稿证据，没有真实外部模型报告和修订证据；
- Step 09的真实API只证明工具、Evidence与报告失败边界，`success=true`只在注入测试结果的API单元测试中出现。

## 证据类型说明

| 类型 | 含义 | 当前覆盖 |
|---|---|---|
| 单元/Mock | 验证Schema、Validator、降级和分支逻辑 | Step 07～09已覆盖 |
| 真实数据 | AkShare、Iceberg、PDF、Milvus产生真实结果 | Step 03～09工具侧已覆盖 |
| 真实基础设施 | Docker、Iceberg、Milvus、BGE实际运行 | Step 02～09已覆盖 |
| 真实生成式模型 | 外部模型真实生成Plan和Report | 尚未覆盖，交由临时Step 09.1 |

后续文档和简历证据必须区分上述四类，不能用Mock成功推导真实模型质量，也不能因为生成式模型未部署而否定已经真实验收的数据、工具和安全边界。

## 补验映射

| 原步骤 | 原结论保留 | 临时补验新增结论 |
|---|---|---|
| Step 06 | BGE索引与检索完成 | 部署生成式模型后的RAG回归 |
| Step 07 | 规则编排、Validator、Executor、Memory完成 | DeepSeek真实Planner可用性 |
| Step 08 | Evidence与确定性校验器完成 | DeepSeek真实报告与修订可用性 |
| Step 09 | API、日志、失败语义完成 | DeepSeek参与的真实HTTP成功链路 |

临时Step 09.1通过后，不删除原失败Artifact；成功与失败证据并存，分别证明正常路径和受控降级路径。

## 文档一致性修正

早期`STEP1_PLAN.md`曾写“模型不可用时提供确定性模板报告作为开发兜底”，但后续审核文档、Step 08实现和API失败语义均采用“明确失败、不伪造正式报告”。本次审计已将早期表述修正为当前生效规则：可以使用显式标记的手工草稿测试Validator，但正式链路在模型不可用时只能返回`generation_failed`。

`docs/phase1/CHECKLIST.md`仍是早期总清单快照，与各Step的Progress/Evidence不同步；它不作为当前完成度依据，统一状态整理留在Step 10的“各Step Progress审计”中处理。
