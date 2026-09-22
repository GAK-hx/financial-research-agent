# Step 02 进度

- 状态：`SUCCESS`；
- 前置：Step 01 Gate 已完成；
- 当前任务：已完成；Step 02最终Gate为7/7通过；
- 默认模型：DeepSeek V4.1 Flash（`deepseek-flash`）；
- 最近更新：2026-09-20。

## 任务

- [x] 默认模型切换到DeepSeek V4.1 Flash正式API名并通过最小在线验证；
- [x] 增加FinanceBench官方PDF语料准备入口，确保不把Gold Evidence当作Agent输入；
- [x] 在Docker内确认公开输入引用84份官方文档，并完成单文档下载可行性检查；
- [x] 完整准备84份FinanceBench官方PDF（158 MiB、12,013页、空文档0）；
- [x] 建立只含官方PDF页文本的FinanceBench检索索引（11,948个文本页、39,898,454字符）；
- [x] 实现直接回答与单Agent检索的统一公开Benchmark推理入口；
- [x] 增加FinanceBench确定性数值/证据评分及FinQA、TAT-QA官方评分入口；
- [x] Benchmark推理逐题落盘并支持断点续跑；网络中断不丢失已完成结果；
- [x] 完成三个公开Benchmark各20题开发Canary，并以失败计0保存统一基线；
- [x] 修正结构化输出边界：本地宽容解析、结构错误不机械重试、失败题可选择性重跑；
- [x] 冻结复杂子集正式开发基线与同题对照；
- [x] 类型化多 Agent 产物；
- [x] Supervisor 和 LangGraph 动态 fan-out；
- [x] Harness 团队、Benchmark工具白名单与预算校验；
- [x] 四类风险子 Agent；
- [x] 四类风险子Agent角色、职责、工具白名单与预算已注册；
- [x] 四类风险子Agent真实候选在线最小演示；
- [x] 风险产物包含主体、报告期、数据截止、数据快照及逐域结构化结论；
- [x] 实现反证复核 Evaluator；
- [x] 实现最多一次定向修复路径，并以确定性程序规范化消除4道历史格式误拒；
- [x] AgentScorecard；
- [x] 从公开FinQA train split构建程序示例Skill，且保持dev/test Gold不可见；
- [x] FinQA程序Skill同题5例Canary：官方Execution / Program由40% / 40%提升至80% / 80%；
- [x] FinanceBench最多一次覆盖补查；5题Evidence Recall / Precision达到93.3% / 78.3%；
- [x] B/C/D同题5例Canary与成本报告；
- [x] 冻结官方复杂子集清单：三组各20题，排除Canary且不含Gold内容；
- [x] FinQA复杂子集B/C/D单轮验证：Execution为30% / 50% / 55%，Program为20% / 35% / 40%；
- [x] A1规则/统计路径公开风险标签评测；
- [x] A路径正式公开数据选型：V4FinBench一年期前瞻任务；
- [x] V4FinBench单文件下载、官方折和统计基线；
- [x] V4FinBench A2固定参数LightGBM五折基线与A1对照；
- [x] FinQA复杂子集B/D扩大验证；
- [x] FinanceBench复杂子集B/D验证；
- [x] TAT-QA复杂子集B/D验证；
- [x] A/B/C/D正式消融与按任务路由结论；
- [x] 最终Gate 7/7通过，失败案例与依赖故障报告已保存。

## 进度记录

| 日期 | 状态 | 说明 |
|---|---|---|
| 2026-09-06 | BLOCKED_BY_DEPENDENCY | 仅完成计划，等待 Step 01 |
| 2026-09-16 | IN_PROGRESS | Step 01统一Gate通过；按官方API切换至V4.1 Flash正式模型名，开始公开Benchmark基线 |
| 2026-09-18 | IN_PROGRESS | 三组20题Canary完成；修复5个非网络结构失败，推理成功率恢复为100%，进入类型化团队实现 |
| 2026-09-19 | IN_PROGRESS | LangGraph动态团队闭环完成；三组各5题同题对照显示TAT-QA正增量、FinQA程序格式改善、FinanceBench退化，按失败归因继续修复 |
| 2026-09-20 | IN_PROGRESS | 接入6,251条公开FinQA训练程序Skill；验证集答案在推理阶段不可见，同题5例官方Execution / Program达到80% / 80%，开始处理FinanceBench检索覆盖 |
| 2026-09-20 | IN_PROGRESS | FinanceBench覆盖检查与固定团队C完成；B/C/D各15题Canary显示动态团队相对固定团队Token减少28.5%，但相对单Agent尚无整体质量优势，转向冻结官方复杂子集验证 |
| 2026-09-20 | IN_PROGRESS | 冻结三组各20题官方复杂子集；FinQA 20题B/C/D显示多Agent较单Agent有正增量，但动态仅领先固定5个百分点且成本更高，正式Gate再做三次稳定性验证 |
| 2026-09-20 | IN_PROGRESS | 四类风险专用Agent在自有PIT候选上完成在线演示；动态选择四角色，生成4条结构化风险结论并保留证据、限制和数据时点；自有样例不计准确率 |
| 2026-09-20 | IN_PROGRESS | FinanceBench复杂子集B/D均20/20成功；数值准确率同为45%、证据召回同为62.5%，D证据精确率更低且Token约增加95.6%，因此不晋级默认路径 |
| 2026-09-20 | IN_PROGRESS | TAT-QA复杂子集B/D均20/20成功；官方EM由30%升至60%，F1由37.9升至63.35，但Token为5.86倍；D仅作为复杂题候选路径 |
| 2026-09-20 | IN_PROGRESS | V4FinBench h=1单文件、官方五折和A1完成；PR-AUC 3.83%、ROC-AUC 91.02%、F1 9.17%，概率校准后ECE 0.042%；五折测试覆盖996,500行且无重复 |
| 2026-09-20 | IN_PROGRESS | V4FinBench A2固定参数LightGBM完成；未做逐折调参，PR-AUC、F1和Recall@Precision 5%相对A1分别提升66.7%、42.9%和81.7%，三项均在5/5折胜出；停止继续刷分，进入正式消融 |
| 2026-09-20 | IN_PROGRESS | TAT-QA固定团队20题补齐：C的EM/F1为55.0/58.35，D为60.0/63.35且Token低7.8%；正式消融收口为FinanceBench走B、FinQA复杂题走C、TAT-QA指定复杂类型走D |
| 2026-09-20 | IN_PROGRESS | FinQA嵌套程序增加确定性顺序编译；历史4道格式失败题全部由REJECT变为ACCEPT，官方Execution/Program为3/4和2/4，未把格式成功等同于答案全对 |
| 2026-09-20 | SUCCESS | Step 02最终Gate 7/7通过；风险评测镜像已固化LightGBM、OpenMP和FinQA官方评分依赖，进入Step 03 |
