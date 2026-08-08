# Step 01 运行手册

## 1. 生产运行

复制示例配置并填写新的 DeepSeek Key：

```bash
cp .env.example .env
docker compose up -d --build app
docker compose ps app
```

生产环境不要设置 `EVALUATION_REFERENCE_DATE`。`QueryInterpreter` 默认按
`BUSINESS_TIMEZONE=Asia/Shanghai` 使用真实当前日期，API 响应的
`execution_metadata` 会记录执行时间、业务参考日期、时区和数据最大可用日期。

研报默认放在本仓库 `data/reports/`，Compose 映射为容器内 `/data/reports`。本地如需复用
其他目录，只能在未提交的 `.env` 中设置 `REPORTS_HOST_DIR`。

## 2. 离线 CI 等价检查

```bash
bash scripts/secret_scan.sh
docker compose config --quiet
docker compose run --rm --no-deps app sh -c \
  "pip install 'ruff>=0.8,<1' && ruff check src tests && \
   python -m unittest discover -s tests -q"
```

需要验证 PostgreSQL 路径时：

```bash
docker compose run --rm --no-deps \
  -e RUN_POSTGRES_TESTS=1 app \
  python -m unittest discover -s tests -q
```

## 3. 冻结评测输入

先生成当前数据输入的 Manifest：

```bash
docker compose run --rm --no-deps app \
  python -m financial_research_agent.evaluation.snapshot \
  --dataset regression \
  --output /artifacts/evaluation/snapshot_manifest.json
```

Manifest 固定数据集哈希与日期、两张 Iceberg 表的 Snapshot ID、研报文件哈希和检索配置。
正式评测在请求发送前会再次读取当前输入并拒绝任何漂移。

```bash
docker compose run --rm --no-deps \
  -e EVALUATION_REFERENCE_DATE=2026-07-15 \
  -e EVAL_SNAPSHOT_MANIFEST=/artifacts/evaluation/snapshot_manifest.json \
  -e API_BASE_URL=http://app:8000 app \
  python -m financial_research_agent.evaluation.run
```

## 4. 私有 Holdout

私有题集必须位于仓库外，使用 `EVAL_PRIVATE_HOLDOUT_PATH` 指定。题集原文、单题响应和失败
输出不得提交 Git；可提交的只有聚合指标和不可反推题目的失败分类。

```bash
docker compose run --rm --no-deps \
  -e EVAL_DATASET=private_holdout \
  -e EVAL_PRIVATE_HOLDOUT_PATH=/private/private_holdout.json \
  -e EVALUATION_REFERENCE_DATE=2026-07-15 \
  -e EVAL_SNAPSHOT_MANIFEST=/artifacts/evaluation/private_manifest.json \
  -e API_BASE_URL=http://app:8000 app \
  python -m financial_research_agent.evaluation.run
```

## 5. GitHub 前置条件

在 DeepSeek 平台吊销所有曾暴露的 Key、写入新 Key 并重新运行 Secret 扫描后，才允许创建
首次提交和私有远程仓库。公开前还需单独审核研报、数据许可、运行产物和完整 Git 历史。

