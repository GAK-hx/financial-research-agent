# Step 08测试失败输出

## 集中测试第1轮

- 时间：2026-07-26
- 结果：126/127通过，1项失败
- 失败：`test_harness_and_stability_failures_are_visible`

```text
AssertionError: False is not true :
["EVIDENCE_EXPECTED:['indicator', 'market']:ACTUAL:['indicator']",
 "TASK_NOT_COMPLETED"]
```

分类：`LABEL_DEFECT`

原因：该单元测试复用了只包含`indicator` Evidence的最小响应夹具，却将必需Evidence
错误标为`market + indicator`。这不涉及生产路径、真实数据或网络。

修正：测试的目标是验证Harness字段和稳定性差异检测，因此将夹具预期收敛为其真实包含
的`indicator` Evidence。正式Holdout和Stability数据集仍要求行情题同时具备
`market + indicator`，未降低验收标准。

## 集中测试第2轮

- 时间：2026-07-26
- 结果：126/127通过，1项错误
- 失败：`test_harness_and_stability_failures_are_visible`

```text
TypeError: '<' not supported between instances of 'NoneType' and 'NoneType'
at evaluation/stability.py response_fingerprint -> sorted(tool_name)
```

分类：`SYSTEM_DEFECT`

原因：稳定性指纹默认所有响应均具有`tool_name`。测试使用了不完整响应夹具，导致缺失
字段进入排序。真实API正常响应包含该字段，但失败响应或损坏产物仍可能不完整。

修正：指纹生成器过滤缺失Tool名称，并将Evidence的可选字符串字段归一化为空字符串；
评测器现在可以对不完整响应生成失败结果，而不是自身崩溃。

## 留出集首轮后的针对性测试

- 时间：2026-07-26
- 结果：34/35通过，1项失败
- 失败：`test_stock_code_does_not_form_partial_chinese_year`

```text
AssertionError: False is not true :
['claim[1]:ENTITY_EVIDENCE_MISMATCH:600519']
```

分类：`LABEL_DEFECT`

原因：新测试已把行情Evidence主体改为`300750`，但仍通过默认夹具附带了`600519`
研报Evidence及第二条Claim。失败来自测试数据内部主体不一致，不是股票代码与中文年份
解析修复失效。

修正：该测试只保留验证所需的单条行情Evidence，不附带无关研报Evidence。

## 容器增量构建网络失败

- 时间：2026-07-26
- 阶段：修正测试夹具后的镜像增量构建

```text
failed to resolve source metadata for docker.io/library/python:3.11-slim:
Head "https://docker.m.daocloud.io/v2/library/python/manifests/3.11-slim?ns=docker.io":
net/http: TLS handshake timeout
```

分类：`NETWORK_FAILURE`

处理：本地构建缓存及上一次成功镜像均保留；提高外层重试次数后继续构建，不调整测试
门槛，也不把网络失败计为业务用例通过。
