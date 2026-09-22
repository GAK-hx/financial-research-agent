# 第五阶段进度

## 当前状态

- 状态：`STEP_03_COMPLETE_WITH_LIMITATIONS`；
- 当前Step：03-A～03-D已完成；本地Kind运行Gate通过，生产化限制已单列；
- 默认模型：DeepSeek V4.1 Flash（`deepseek-flash`）；
- GitHub：保持私有；
- 最近更新：2026-09-20。

## 已完成

- 100家公司三表、PIT特征、Iceberg、质量审计和Docker运行；
- 明确FinanceBench、FinQA、TAT-QA作为唯一效果Benchmark；
- 明确自有公司数据只用于业务展示、成功率、并发、缓存、成本和部署测试；
- 从Step 01 Gate移除双人标注、人工PDF核对和自建Holdout。
- FinanceBench 150例、FinQA 8,281例、TAT-QA 16,546例已按官方split接入，共24,977例；
- Agent输入与Gold分离，FinQA/TAT-QA官方评分入口和FinanceBench Gold Schema验证通过；
- Step 01统一Gate自动检查8/8通过。
- 三个公开Benchmark各20题单Agent/直接回答基线已完成；失败按0计入指标；
- Supervisor、Harness、LangGraph动态fan-out、Evaluator、一次定向修复和AgentScorecard已接入；
- FinQA公开训练程序Skill已在同题5例Canary上把官方Execution / Program从40% / 40%提升到80% / 80%。
- FinQA公开复杂子集20题中，单Agent/固定团队/动态团队官方Execution为30%/50%/55%，
  Program为20%/35%/40%；动态仅优于固定5个百分点且成本更高，因此固定团队作为复杂题默认。
- 四类风险专用Agent已完成自有PIT候选在线演示，结构化产物包含逐域结论、证据、限制、主体、报告期、数据截止和数据快照；该演示不用于准确率评测。
- FinanceBench复杂子集上动态团队未提高确定性数值准确率和证据召回，暂不晋级默认路径；
- TAT-QA复杂子集上动态团队将官方EM从30%提升至60%、F1从37.9提升至63.35，作为复杂题候选路径保留。
- V4FinBench一年期前瞻数据、官方公司分组五折及A1/A2基线已完成；固定参数LightGBM相对逻辑回归的PR-AUC、F1和Recall@Precision 5%分别提升66.7%、42.9%和81.7%，三项均在5/5折胜出；所有测试样本恰好覆盖一次。
- 公开复杂题正式消融已收口：FinanceBench默认单Agent，FinQA复杂题默认固定团队，TAT-QA复杂算术和table-text任务使用动态团队；动态团队不作为全局默认。
- FinQA受控执行器已支持把允许的嵌套表达式编译为官方顺序程序；4道历史格式失败题全部由REJECT变为ACCEPT，未通过官方答案评分的部分仍保留为真实失败。
- 5个source-time历史回放点已生成126,880条特征和39,040条候选，PIT泄漏与主键重复均为0；相邻快照潜在增量影响约5.1%～9.4%。
- 风险公共Artifact适配层已接入既有检索协调器：数据快照、公共分析、用户报告分离，首次并发分析使用single-flight，数据版本变化仅使受影响产物失效。
- Docker冻结响应Gate覆盖1/5/20/50用户；50用户250次交叉查询只执行20次唯一公司分析，热态新增分析0次；两家公司更新仅重算两家，公共产物用户身份泄漏0。该延迟不作为生产或简历数字。
- Spark 4.2 / PyIceberg 500万行合成数据Gate通过：5%公司增量使扫描行和计划文件均减少95%，失败提交不产生Snapshot，重跑主键重复0。
- Kubernetes Base/Kind清单与离线Manifest Gate通过：业务工作负载安全上下文、探针、资源限制、HPA、PDB、NetworkPolicy、Secret边界及共享湖PVC均完成；三逻辑节点运行与故障演练也已完成。
- Agent、数据分析、数据开发三份岗位交付文档与Kind运行手册已完成。
- Kind v0.33.0 / Kubernetes v1.37.0三逻辑节点全部Ready；Gateway、API、Worker、PostgreSQL和Redis完成真实部署，迁移与湖初始化Job完成。
- Worker强制退出后任务由新Worker接管且只产生一个终态；Redis停机时已有事实可读、新任务明确返回可重试503；租户越权读取返回404。
- Gateway滚动更新期间80/80请求成功，回滚后Ready；SSE按Last-Event-ID续传无重复终态。
- K8s运行结果明确保留限制：未安装metrics-server，不声明HPA动态扩缩容；Kind不是多机生产集群；本地RWO湖PVC、PostgreSQL和Redis不能直接作为生产方案。

## 后续可选优化

- 若进入生产化阶段：增加metrics-server或云监控、对象存储、托管PostgreSQL/Redis、多可用区、镜像漏洞扫描和容量压测；
- 若继续提高Agent效果：仍只在FinanceBench、FinQA、TAT-QA等公开Benchmark上比较，不把自有公司演示当准确率；
- GitHub继续保持私有，公开前另做密钥历史、许可证和大文件检查。
