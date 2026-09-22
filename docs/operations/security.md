# 安全与发布

## 不进入Git的内容

- `.env`、API Key、Token、口令、证书和SSH密钥；
- 湖数据、数据库文件、模型缓存和运行Trace；
- 未获再分发许可的研报、PDF、新闻正文和第三方数据；
- 私有Holdout、用户输入和未脱敏错误载荷。

## 发布检查

```bash
bash scripts/secret_scan.sh
git status --short --ignored
git diff --check
```

密钥扫描器只输出文件与行号，不回显疑似密钥。曾出现在对话、日志或历史提交中的Key必须在Provider控制台
吊销，删除文件不能替代轮换。

## 身份与数据边界

- Gateway建立可信tenant/user身份并删除外部伪造头；
- Run、Memory、UserReport、Event和Trace按租户授权；
- 公共分析缓存不包含用户身份或会话文本；
- Tool只能读取授权数据域；
- 最终报告与原始Evidence分开存储，摘要不能覆盖原文。

SSH使用方法见[空配置模板](../security/SSH_SETUP.md)。
