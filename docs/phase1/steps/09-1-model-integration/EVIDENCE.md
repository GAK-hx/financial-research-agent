# 临时Step 09.1 Evidence

## 验收环境

- Provider：项目内部适配器名`openai_compatible`
- API：DeepSeek官方OpenAI兼容接口
- 模型：`deepseek-v4-flash`
- Prompt：`planner_v2`、`report_v2`
- 部署：Docker Compose中的`app`、`milvus`、`etcd`
- 密钥：仅由本地`.env`经Compose `env_file`注入；文件权限`600`

`openai_compatible`不是DeepSeek模型或官方Provider枚举，而是本项目对“使用OpenAI请求格式的HTTP适配器”的内部命名。DeepSeek官方接口支持该请求格式，因此无需引入DeepSeek专用Agent框架。

## 1. 模型预检

最小结构化请求成功，返回模型为`deepseek-v4-flash`，JSON可解析，实测延迟2251ms。预检只记录模型、结果和耗时，不记录Authorization Header或Key。

## 2. Step 06回归

| 检查 | 结果 |
|---|---|
| PDF / 页 / Chunk | 6 / 30 / 88 |
| 向量维度 | 512 |
| Milvus实体数 | 88 |
| 幂等新增 | 0 |
| 跨股票误召回 | 0 |
| 600519 Top 1 | 华鑫证券，第2页，score 0.690399 |
| 300750 Top 1 | 交银国际，第1页，score 0.762495 |

结论：生成式模型接入没有破坏原有BGE嵌入和Milvus过滤检索。

## 3. Step 07 Planner补验

四类问题均至少完成一次`planner_source=model`的真实Run，模型输出先解析为`AnalysisPlan`，再经过确定性Plan Validator和Tool Registry。Comprehensive保持`market_query`与`report_search`并行，`indicator_compute`依赖`market_query`。

提示注入样例要求执行Shell、Python并读取API Key，模型最终计划仍只包含白名单内的`market_query`和`indicator_compute`，且依赖关系正确；未知工具没有进入Executor。

联调中发现并修复：

1. 初始模型使用通用`steps/tool/params`结构：向Prompt提供实际Pydantic Schema和最小示例；
2. 模型曾遗漏指标依赖：在Prompt明确依赖规则，并由Plan Validator强制验证语义依赖；
3. Provider增加JSON输出约束、`max_tokens`、空内容和截断响应处理。

## 4. Step 08 Reporter与Validator补验

Market、Financial、Report、Comprehensive四类正式报告均基于当前Run Evidence生成并通过Entity、Date、Citation、Attribution、Numeric和Completion校验。

真实修订专项测试：

- 在合法Market报告中注入无证据数字`99.0%`；
- 修订前：`NUMERIC_UNSUPPORTED:99.0%`；
- Flash调用次数：1；
- 修订后：校验通过，恢复为Evidence支持的`-10.61%`；
- Artifact：`artifacts/model_runs/deepseek_flash_revision.json`。

综合HTTP Run也真实触发一次自动修订并最终通过，证明修订不是只在独立测试脚本中有效。

联调中修复了Numeric Validator的确定性边界：展示精度舍入、中文涨跌方向、日期数字、均线/窗口标签，以及研报数字与Evidence Chunk的一一引用约束。所有修复均补充单元测试。

保留的失败前Artifact位于`artifacts/model_runs/`，文件名包含`before_*_fix`，用于证明Validator确实拦截了错误，而不是降低校验标准换取成功。

## 5. Step 09真实HTTP补验

| 场景 | HTTP | Run ID | Evidence | 总耗时 | Artifact |
|---|---:|---|---:|---:|---|
| Market | 200 | `524dbdfebdf04f9c8630dda220d054ca` | 2 | 10756ms | `deepseek_flash_market.json` |
| Financial | 200 | `c7f1d0215f984f77b40af718960b63d3` | 1 | 11513ms | `deepseek_flash_financial.json` |
| Report | 200 | `bc6913cdf05f4dc585bc32bf364f3212` | 5 | 25183ms | `deepseek_flash_report.json` |
| Comprehensive | 200 | `7c72f7f476de4adba93dc3504f4ee331` | 7 | 31078ms | `deepseek_flash_comprehensive.json` |

四条响应均满足：`success=true`、`planner_source=model`、`reporting_status=completed`、`validation.passed=true`，并记录`deepseek-v4-flash`、`planner_v2`和`report_v2`。

## 6. 回归、安全与资源

- 完整测试：56/56通过；另有1条第三方Starlette弃用Warning，不影响本步骤。
- 测试工具只临时安装在当前可丢弃容器，未写入生产镜像依赖。
- 工作区（排除本地`.env`）密钥特征匹配：0。
- App最近500行日志密钥特征匹配：0。
- 资源快照：App 470MiB/900MiB、Milvus 636MiB/1.758GiB、etcd 48.32MiB/256MiB。

## 7. 结论与边界

Step 09.1通过，Step 10可以开始。当前证据证明四类标准链路能够使用真实模型完成规划、工具执行、报告生成、校验和有限修订；它不代表20题准确率、P95延迟或成本已经达标，这些统计属于Step 10。
