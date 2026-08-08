# Step 08 验收记录

## 正式链路

```text
Current-run Evidence
→ Context裁剪（不传行情原始大表）
→ Evidence-only Model Reporter
→ ResearchReport Schema
→ Entity / Date / Citation / Numeric Validator
→ Pass
   或一次带错误反馈的修订
→ Pass / validation_failed
```

正式Reporter只接收`QuerySpec`和当前Run Evidence，不接收数据库连接、工具对象或历史Run内容。模型不可用时返回`generation_failed`，不会用模板报告冒充正式结果。

## Evidence Builder

- 只接收成功的Tool Result；
- Evidence ID统一改为`run_id:original_evidence_id`；
- 原ID保留在Source Metadata；
- Market/Financial要求Iceberg来源；
- Indicator要求Calculation来源、公式版本和输入Locator；
- Research Report要求Milvus来源、机构、标题、页码和Chunk ID；
- 重复ID、来源链缺失和Evidence预算超限直接失败。

## 校验规则

| 校验器 | 规则 |
|---|---|
| Entity | Report Subject、Claim股票和引用Evidence必须属于QuerySpec |
| Date | `data_as_of`必须等于当前Evidence可确定的最新日期 |
| Citation | ID必须存在于当前Run，跨Run ID拒绝 |
| Report Attribution | 研报引用必须保留机构且能定位页码 |
| Numeric | Claim中的数字、百分比、万元/亿元必须能在引用Evidence结构化数据中匹配 |
| Completion | 至少一个Claim、风险章节和“不构成投资建议”声明 |

## 负向验收

| 构造错误 | 结果 |
|---|---|
| 无引用Claim | Pydantic Schema拒绝 |
| 伪造Evidence ID | `CITATION_UNKNOWN` |
| 跨Run Evidence ID | `CITATION_WRONG_RUN` |
| 错误股票 | Entity Validator拒绝 |
| 错误截止日期 | `DATE_AS_OF_MISMATCH` |
| 错误关键数字 | `NUMERIC_UNSUPPORTED` |
| 研报无页码 | `REPORT_PAGE_MISSING` |
| 研报未写机构 | `REPORT_ATTRIBUTION_MISSING` |
| 无研报却生成机构观点 | `REPORT_EVIDENCE_ABSENT` |
| 第二次报告仍不合法 | `validation_failed`，不再修订 |

## 真实Evidence审计

### 宁德时代财务

- Evidence：1条；
- `data_as_of`：2026-03-31；
- Run级ID：Pass；
- Entity/Date/Citation/Numeric：全部Pass。

### 贵州茅台综合

- Market 1条、Indicator 1条、Research Report 5条，共7条；
- `data_as_of`：2026-07-14；
- 研报机构、页码和Chunk来源链：Pass；
- Entity/Date/Citation/Numeric：全部Pass。

以上使用`validation_only=true`验收草稿，不视为正式模型报告。

### 未配置模型的正式链路

- Orchestration：成功；
- Evidence：1条且ID带Run前缀；
- Reporting：`generation_failed`；
- 原因：`ProviderUnavailable:model provider is not configured`；
- Report：未生成。

## 测试

- 最终Docker镜像内44/44项测试通过；
- 一次修订可以修正错误数字；
- 第二次仍错误时停止；
- 空Evidence和Provider失败均不会产生模板报告。

## 当前限制

- 尚未配置真实模型，因此未评估正式报告的语言质量和具体模型遵循率；
- Numeric Validator覆盖结构化关键数字及常用百分比、万元、亿元换算，不是通用数学证明器；
- 数据新鲜度阈值尚未按数据域区分，目前只检查报告截止日与Evidence一致；
- Markdown渲染与API返回属于Step 09。
