# Step 01-B 阶段报告：正确性小池采集主链路

## 结论

状态为 `PARTIAL_PASS`。冻结的20家公司全部完成三大报表采集、原始快照保存、长表标准化和本地
Iceberg 写入，覆盖门槛 `>=19/20` 已达到；但公告事件池、人工 PDF/源值抽检和100家公司扩展池尚未完成，
因此 01-B 与 Step 01 均不能标记为完成。

## 结果

| 项目 | 结果 |
|---|---:|
| 冻结公司 | 20 |
| 三表成功公司 | 20/20 |
| 至少8个报告期 | 20/20 |
| 标准化事实 | 35,877 |
| Iceberg Snapshot | 2274091845582899815 |
| 输入指纹 | 4f709d29fa41a97cef96056b1ad1621a1d379590eb78e10bdfe3eb8327e542ab |
| 本地占用 | 约15 MiB |
| 断点续跑 | 5.3秒复用同一Snapshot，未重复追加 |
| 数据源 | AkShare 1.18.83 / 东财按报告期三表 |

## 已验证

- 20家公司在查看覆盖结果前冻结；
- 每家公司完成后单独保存原始 Parquet、标准化事实、拒绝明细和结果检查点；
- 最多2家公司并发，每个源调用具有90秒硬超时和有限重试；
- DWD 事实同时保留报告期、公告日/更新日推导的有效发布时间、系统观测时间、来源记录和内容哈希；
- 缺失值使用 `NOT_DISCLOSED` 或 `NOT_AVAILABLE_FROM_SOURCE`，没有补0；
- Iceberg 按输入文件指纹隔离 Catalog，相同输入重跑复用原 Snapshot；
- 银行、保险仍验证数据可读，但被标为不适用通用工商企业比率。

## 已发现并修复

1. 沙箱 DNS 失败导致新浪接口长退避：增加子进程硬超时，并区分环境错误与来源错误；
2. `multiprocessing.Queue` 传输大 DataFrame 导致父子进程等待：改用 Pipe 先接收再回收子进程；
3. 本地 Iceberg Catalog 父目录未创建：在初始化 Catalog 前显式创建；
4. 断点续跑可能重复写入：增加公司成功检查点和全量输入指纹复用。

## 尚未通过

- 未完成公告、更正、监管问询和审计报告事件池；
- 未对抽样字段执行人工 PDF/源页面对账，不能声称99.5%对账率；
- 只完成20家公司小池，尚未扩展到100家公司；
- 当前 API 返回的是抓取时最新行，旧报告原始版本需要历史快照/PDF补充；
- 尚未生成 DWS 风险特征、标签与规则/逻辑回归基线。

## 本地产物

- 汇总：`artifacts/phase5_step01/correctness_pool_v1/report.md`；
- 公司检查点：`artifacts/phase5_step01/correctness_pool_v1/companies/*/result.json`；
- 原始快照：各公司目录下 `raw/`；
- 标准化事实：各公司目录下 `risk_facts.parquet`；
- Iceberg：`artifacts/phase5_step01/correctness_pool_v1/iceberg/4f709d29fa41a97c/`；
- 早期失败样例：`artifacts/phase5_step01/source_audit/`。
