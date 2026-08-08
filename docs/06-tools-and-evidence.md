# 06 工具与Evidence设计

## 1. 工具是唯一数据访问边界

模型看到工具名称、说明和输入Schema；数据库连接、表结构细节和执行实现对模型隐藏。

## 2. 工具接口规范

每个工具声明：

```text
name/version/description
input_schema/output_schema
read_only/allow_parallel
timeout/max_rows
data_domain/freshness
recoverable_errors
```

第一步所有工具必须只读。

## 3. 工具清单

### Market Query

按股票、日期和复权口径读取Curated日线。不得接受任意SQL。最大1000行。

### Indicator Calculator

消费Market结果或内部领域数据，计算收益率、波动率、均线、最大回撤、量比摘要和区间高低。

### Financial Query

按公司和报告期返回标准字段和确定性财务指标。只有真实表通过验收后才注册。

### Stock Comparison

统一时间和指标口径后比较2～5只股票，禁止直接拼接不同复权/日期口径。

### Report Search

先按股票Metadata过滤，再向量检索；返回报告、机构、页码、chunk ID、原文和分数。

## 4. Tool Result

结果包含task_id、success、领域payload、错误代码、耗时和source hints。Tool Result不是Evidence，也不能直接写报告。

## 5. Evidence模型

```text
evidence_id
evidence_type
subject
statement
structured_data
source_reference
observed_at/data_as_of
quality_flags
```

Evidence类型：Market、Financial、Indicator、Research Report。

## 6. 来源定位

- Iceberg：table、snapshot/query ID、股票、日期范围；
- Calculation：指标名、公式版本、输入Evidence ID；
- Report：文件/报告ID、页码、chunk ID、机构；
- 禁止只写“来源：AkShare”而无法定位具体数据。

## 7. Evidence组合

派生指标Evidence必须引用输入数据Evidence或查询locator。报告中的复合结论可以引用多个Evidence，但不能把多条Evidence合并后丢失来源。

## 8. 权限与安全

- Registry只注册审核过的工具；
- Schema在执行前校验；
- 参数有日期、数量和Top K上限；
- 工具无任意代码接口；
- 第二步Policy Layer决定不同运行模式可用工具；
- 未来副作用工具必须单独权限和人工审批。

## 9. 待审核决策

- Indicator Tool是接受Market Tool结果，还是自行查询Repository？建议执行器传递标准化领域结果，减少重复查询。
- Evidence Statement由工具模板生成还是模型生成？建议工具模板生成，保证事实稳定。
- 是否在第一步保存Evidence到文件？建议保存端到端示例，普通请求可只返回。
