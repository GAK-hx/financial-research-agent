# Step 04 — 行情与指标工具

## 目标

提供脱离LLM也能独立运行的Market Query与Indicator工具，并生成可追溯Evidence。

## 依赖

- Step 03完成。

## 任务

1. 定义MarketQueryInput/Output；
2. 限制股票、日期、复权和最大1000行；
3. Market Tool读取Curated日线；
4. 定义IndicatorInput/Output；
5. 实现区间收益、年化波动率、MA5/MA20、最大回撤、成交量相对20日均量、区间高低；
6. 记录实际首末交易日和数据截止日；
7. 指标携带公式版本和输入locator；
8. Market/Indicator结果转换为Evidence；
9. 增加日期不足、空数据和非法参数错误；
10. 使用手工小样本验证公式。

## 交付物

- Market Tool；
- Indicator Tool；
- 指标定义和公式版本；
- Evidence模板；
- 单元与集成测试。

## 验收标准

- 相同输入结果稳定；
- 固定样本计算一致；
- 非交易日使用实际交易日并披露；
- 不接受任意SQL；
- 每项输出带来源和数据日期。

