# GitHub SSH配置说明

本仓库只记录配置方法，不保存任何个人私钥、公钥正文、指纹或本机绝对路径。

## 生成仓库专用密钥

在本机执行，并自行选择未被Git跟踪的保存位置：

```bash
ssh-keygen -t ed25519 -C "financial-research-agent-deploy-key" \
  -f ~/.ssh/<private-key-file>
```

生成后：

- 私钥`~/.ssh/<private-key-file>`只保存在本机或Secret Manager；
- 公钥`~/.ssh/<private-key-file>.pub`只添加到GitHub仓库的Deploy keys；
- 不要把私钥、公钥正文、指纹或真实路径复制到源码、README、Issue、CI日志或运行产物。

只需要推送时可以为Deploy key开启写权限；普通拉取应保持只读。

## 本机SSH配置

可在本机`~/.ssh/config`中增加一个仅供本项目使用的Host别名：

```sshconfig
Host <github-host-alias>
  HostName ssh.github.com
  Port 443
  User git
  IdentityFile ~/.ssh/<private-key-file>
  IdentitiesOnly yes
```

测试连接：

```bash
ssh -T <github-host-alias>
```

设置仓库Remote：

```bash
git remote set-url origin \
  git@<github-host-alias>:<github-owner>/<repository>.git
```

尖括号字段必须在本机替换，不能把替换后的个人值提交到仓库。

## 环境变量

模型、数据库、Redis、Gateway和加密配置以`.env.example`为结构模板：

```bash
cp .env.example .env
```

只在未跟踪的`.env`中填写真实值。提交前执行：

```bash
bash scripts/secret_scan.sh
git status --short --ignored
```

如果Key曾出现在对话、日志或提交历史中，应在对应Provider控制台吊销并重新生成；只从文件中删除不等于完成轮换。
