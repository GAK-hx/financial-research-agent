# Step 08 — Evidence、报告与校验

## 目标

保证最终报告只基于当前Run的可追溯Evidence，并能拦截实体、日期、引用和关键数字错误。

## 依赖

- Step 04、06、07完成；
- Step 05若启用财务则完成。

## 任务

1. Evidence Builder为各域生成稳定statement和source locator；
2. Evidence ID包含Run隔离或由Store映射；
3. 指标Evidence记录公式版本和输入locator；
4. 研报Evidence记录机构、报告、页码和chunk ID；
5. 定义ResearchReport和ReportClaim；
6. Reporter只接收QuerySpec+Evidence；
7. 每个Claim至少一个Evidence ID；
8. 报告包含data_as_of和风险；
9. Entity Validator检查股票一致；
10. Date Validator检查数据截止日；
11. Citation Validator检查存在、归属和页码；
12. Numeric Validator比较结构化关键指标；
13. 失败允许一次带反馈修订；
14. 再失败返回validation failed，不标记完成。

## 验收标准

- 无Evidence Claim无法通过；
- 伪造ID、错误股票、错误日期被拦截；
- 关键数字错误被拦截；
- 机构观点保留归属；
- 无研报时不生成机构观点；
- 一次修订边界有效。

