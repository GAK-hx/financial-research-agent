# Git、Secret 与数据发布规则

## 首次远程提交前

1. 轮换所有曾在对话、终端或日志中出现过的 DeepSeek API Key；
2. 确认 `.env` 未被 Git 跟踪；
3. 运行 `bash scripts/secret_scan.sh`；
4. 确认 `data/reports/`、`lake/`、`artifacts/`、`tmp/` 和模型缓存未被跟踪；
5. 先创建私有 GitHub 仓库，不直接公开。

本地 Git 初始化不等于密钥已安全。已经暴露过的 Key 即使从文件删除，也必须在供应商平台吊销。

## 可以提交

- 源码、测试、迁移、Dockerfile、Compose 和 `.env.example`；
- 只包含结构和模拟值的测试 Fixture；
- 架构、操作、评测方法和聚合结果；
- 空目录占位文件 `.gitkeep`。

## 不可以提交

- `.env`、API Key、数据库口令、证书和 Token；
- Iceberg Lake、PostgreSQL/Milvus 数据、模型缓存和运行 Trace 原文；
- 未获得再分发许可的研报、PDF、新闻正文和第三方数据快照；
- 私有 Holdout 题目；
- 包含用户标识、会话内容或未脱敏错误载荷的产物。

## 数据许可边界

仓库只提交数据接口、Schema、质量规则和生成方法。第三方数据由使用者在本地按来源条款获取。
公开 README 可以描述使用 AkShare、研报和 DeepSeek API，但不能因此推定底层内容可以随仓库分发。

## 公开仓库前的额外审核

- 扫描完整 Git 历史，而不只是当前工作树；
- 生成依赖许可证清单并检查不兼容许可证；
- 检查所有图片、PDF、示例输出和数据字段是否可公开；
- 将真实运行产物替换为最小、合成、不可还原的演示 Fixture；
- 在 README 明确研究辅助、数据时点和非交易系统边界。

