# Step 06 Context Pipeline实现

## 1. 节点级白名单

Context Builder不再把整个Graph State直接交给模型，而是按节点构建最小输入：

| 节点 | 允许内容 |
|---|---|
| Interpret | 问题与有限Session Memory |
| Select Skill | QuerySpec、候选Skill ID与Policy版本 |
| Plan | QuerySpec、Skill约束、受控Tool Schema、Budget与有限Memory |
| Report | QuerySpec、验证后Evidence、报告章节和显式Preference |
| Revise | 原报告、Validator错误及对应Evidence |

每次构建生成`ContextManifest`，记录Policy/Skill版本、条目哈希、裁剪项、压缩前后
Token估算、摘要深度、Evidence保护哈希、告警和构建时间，并持久化到PostgreSQL。

## 2. 压缩顺序

当前稳定路径为确定性压缩：

1. 保留Evidence ID、statement、结构化指标与Source；
2. 将可从Source Locator重新定位的批量`rows`替换为行数和定位说明；
3. 按节点数量上限裁剪非Evidence Memory；
4. 复检Token预算；
5. 对受保护字段重新计算哈希。

一层模型摘要接口已经实现，但默认关闭。只有确定性处理仍超限、Policy允许且摘要器
已配置时才会触发；摘要仅处理Memory/Preference，不能处理Evidence，不能递归，
若引入新数字则校验失败并回退。

## 3. Evidence保护

保护投影包含Evidence ID、类型、主体、statement中的数字与单位、Source Locator、
Source Metadata，以及Snapshot、公式版本、报告机构、页码等归因字段。压缩前后
投影哈希不一致时，Graph在调用报告模型前即拒绝继续。

1000行同输入A/B结果：

| 模式 | 压缩前Token估算 | 压缩后 | 比例 | 平均构建耗时 | Evidence保护 |
|---|---:|---:|---:|---:|---|
| 关闭 | 13504 | 13504 | 1.000000 | 14.184ms | 通过 |
| 开启 | 13504 | 241 | 0.017847 | 7.248ms | 通过 |

该A/B是Context Builder的受控基准，不把Token估算等同于供应商账单Token。真实追问
Run的Report Context从3711降至786，比例为0.211803，Validator通过。
