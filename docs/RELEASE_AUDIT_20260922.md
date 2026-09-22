# 私有仓库发布前审计（2026-09-22）

## 结论

状态：`PRIVATE_READY_WITH_BLOCKERS`。

当前工作树适合继续保存在私有仓库，但不满足公开发布条件。代码与文档候选文件未发现符合规则的API Key，
完整Git历史未发现DeepSeek `sk-...`密钥或私钥文件头；敏感本地目录也未被Git跟踪。

公开前仍必须由仓库所有者完成Key轮换、许可证选择和第三方数据许可复核。

## 已通过

- `scripts/secret_scan.sh`通过，并且扫描器只输出文件与行号，不会把疑似密钥复制到CI日志；
- 扫描全部5个Git提交，未发现`sk-`长密钥模式；
- 扫描全部5个Git提交，未发现RSA、EC或OpenSSH私钥头；
- `.env`、`*.pem`、`*.key`、`*.p12`和`*.pfx`从未被Git历史跟踪；
- `artifacts/`、`lake/`和`data/reports/`只跟踪`.gitkeep`；
- 当前最大已跟踪文件为`uv.lock`，约956 KiB，没有大于20 MiB的已跟踪文件；
- Docker Compose配置可以完成解析；
- 根README不包含真实Key，只使用占位符和环境变量名；
- 本轮未执行commit、push或仓库可见性修改。

## 阻断项

### 1. Key轮换

历史对话曾出现过DeepSeek Key。即使这些Key没有进入Git，只要离开了原始保密边界，就应在DeepSeek控制台
吊销并生成新Key。新Key只保存在本机未跟踪的`.env`或正式Secret Manager中。

此操作必须由账户所有者完成，项目代码不能替代Provider侧轮换。

### 2. 仓库许可证

仓库根目录目前没有`LICENSE`或`NOTICE`。保持私有时可以暂不选择开源许可证；若公开，需要先确定代码许可，
并检查Python、Java、模型、数据源和文档依赖的再分发约束。

### 3. 第三方数据与模型

- AkShare是数据接口，不代表底层行情和财务数据可以随仓库再分发；
- 研报、PDF、新闻正文、公告镜像和第三方Benchmark原始文件不得因本地可用而自动提交；
- BGE等模型权重不进入仓库，使用者应按对应模型许可证自行下载；
- 只允许公开Schema、采集方法、质量规则、不可还原的聚合指标和明确许可的最小Fixture。

### 4. 远端可见性核验

本地remote为`GAK-hx/financial-research-agent`的SSH地址，历史记录表明按私有仓库创建。当前环境没有GitHub CLI，
本轮未通过GitHub API独立复核实时可见性。没有执行任何远端写入或可见性修改。

## 私有提交前可以执行

```bash
bash scripts/secret_scan.sh
docker compose config --quiet
git diff --check
```

确认`git status`中不存在`.env`、真实PDF、湖数据、运行Trace或私有Holdout后，才可以提交到现有私有仓库。

## 公开前必须再次执行

1. 在DeepSeek控制台轮换所有曾暴露Key；
2. 选择代码许可证，并生成依赖许可证清单；
3. 逐项确认示例数据、Benchmark、PDF、图片与模型的分发权；
4. 使用具备远端权限的工具确认仓库仍为Private；
5. 扫描完整Git历史，而不只扫描工作树；
6. 使用最小合成Fixture替换可能包含真实内容的演示产物；
7. 由仓库所有者再次明确授权后，才允许改为Public。
