# Step 01：数据底座与公开 Benchmark 接入

## 目标

建立可复现的自有财务数据底座，并接入 FinanceBench、FinQA、TAT-QA 官方公开数据与评分入口。自有公司数据只做业务演示和性能测试，不自建 Benchmark 或人工标签。

## 工作包

### 01-A 自有数据底座

- 冻结财务风险指标口径、来源能力和ODS/DWD/DWS/ADS模型；
- 完成100家公司三表、公告、PIT特征和Iceberg快照；
- 检查主体、期间、单位、缺失状态、主键重复和未来数据泄漏；
- 程序化风险信号只作为Agent演示输入，不作为Gold。

### 01-B 公开 Benchmark 适配

- 从官方仓库读取 FinanceBench 公开150例；
- 从官方仓库读取 FinQA train/dev/test；
- 从官方仓库读取 TAT-QA train/dev/test gold；
- 保留官方ID和split，不自行划分私有集；
- 将Agent输入与Gold答案/证据/程序分目录隔离；
- 保存官方来源、许可说明、任务和评分政策。

### 01-C 评分入口

- FinanceBench：答案、数值和Gold Evidence评分，语义Judge只作辅助；
- FinQA：封装官方Execution Accuracy与Program Accuracy；
- TAT-QA：封装官方Exact Match、F1和scale处理；
- 统一结果结构记录输出、证据、Trace、延迟、Token、成本和错误类型；
- 只做最小样本可行性运行，完整模型对比归Step 02。

### 01-D 集中 Gate

- 在Docker中读取并标准化三个官方数据集；
- 验证案例ID唯一、官方split保留、输入不含Gold字段；
- 验证评分器能对最小预测文件输出指标；
- 合并数据底座和公开Benchmark适配报告；
- 删除双人标注、人工PDF核对、自建私有Holdout等阻塞项。

## Step 01 Gate

- 100家公司覆盖100/100；
- 关键值完整率不低于99%，程序化对账率不低于99.5%；
- 主键重复、相同输入重复写入和PIT泄漏均为0；
- FinanceBench、FinQA、TAT-QA官方数据均能读取；
- 官方split、原始ID和Gold字段完整；
- Agent输入与Gold物理隔离，输入中无答案/证据/程序泄漏；
- 三个评分入口完成最小可行性验证；
- Docker基础检查通过并生成统一Gate报告。

## 不在本 Step

- 不执行完整模型Benchmark；
- 不创建人工标签或自建Benchmark；
- 不把程序化风险候选作为真实标签；
- 不实现动态Supervisor；
- 不公开GitHub；
- 不执行Kubernetes部署，K8s归Step 03。
