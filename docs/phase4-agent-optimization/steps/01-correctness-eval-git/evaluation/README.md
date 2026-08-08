# 评测数据与冻结输入

## 数据集分层

| 数据集 | 用途 | 是否进入仓库 | 是否用于开发修题 |
|---|---|---:|---:|
| `regression` | 确定性开发回归 | 是 | 是 |
| `holdout` | 历史第二阶段验证基线 | 是 | 已使用，不再视为私有 |
| `stability` | 同题多次运行稳定性 | 是 | 是 |
| `private_holdout` | 当前版本最终泛化验收 | 否 | 否 |

私有 Holdout 由 `EVAL_PRIVATE_HOLDOUT_PATH` 指向仓库外 JSON。其 Schema 与
`EvaluationDataset` 相同，`kind` 必须为 `private_holdout`，题号使用 `private-01` 等格式，
包含 20～100 道唯一题目。题目不能进入 Prompt、示例、失败修复文档或 Git 历史；只允许保存
聚合指标和已脱敏的失败分类。

## 冻结输入 Manifest

真实评测前先捕获 Iceberg Snapshot、研报哈希、检索配置和数据集哈希：

```bash
docker compose run --rm --no-deps app \
  python -m financial_research_agent.evaluation.snapshot \
  --dataset regression \
  --output /artifacts/evaluation/snapshot_manifest.json
```

运行评测时必须显式传入业务参考日期和 Manifest：

```bash
docker compose run --rm --no-deps \
  -e EVALUATION_REFERENCE_DATE=2026-07-15 \
  -e EVAL_SNAPSHOT_MANIFEST=/artifacts/evaluation/snapshot_manifest.json \
  -e API_BASE_URL=http://app:8000 app \
  python -m financial_research_agent.evaluation.run
```

生产服务不设置 `EVALUATION_REFERENCE_DATE`。只有冻结评测允许覆盖业务时钟。

## 判定原则

- 股票、日期、周期粒度、分析域、Tool 权限、引用和预算等 P0 指标必须 100%；
- 综合模型题集目标不低于 95%，但总体分数不能掩盖 P0 失败；
- 确定性 Validator 优先，LLM Judge 不判断公式、数值、日期或权限；
- 网络和供应商错误单独分类，保存原始输出和重试记录；
- 失败题修复只进入回归集，不把私有题目原文复制进开发资料。

