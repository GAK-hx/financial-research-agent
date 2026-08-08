# Skill审核与发布

## 1. 生命周期

```text
DRAFT → REVIEWED → ACTIVE → DEPRECATED
```

- `import`只允许导入`DRAFT`；
- `review`必须由显式操作者执行并记录审核人和说明；
- `activate`只接受`REVIEWED`，同一Skill已有ACTIVE版本会被旧版替换并留痕；
- `deprecate`只接受`ACTIVE`；
- 模型运行路径没有发布权限。

状态变化不修改内容Checksum；若要修改触发条件、工具、Evidence或预算，必须创建
新版本。已有Run持有的Snapshot不随发布状态变化。

## 2. CLI

以下命令在具备数据库连接的应用容器中执行：

```bash
python -m financial_research_agent.skills.cli list
python -m financial_research_agent.skills.cli import --file /path/skill.json --actor alice
python -m financial_research_agent.skills.cli review --version-id example@1.0.0 --actor reviewer
python -m financial_research_agent.skills.cli activate --version-id example@1.0.0 --actor publisher
python -m financial_research_agent.skills.cli deprecate --version-id example@1.0.0 --actor publisher
```

内置目录随发行版经过同一审计流程初始化：

```bash
python -m financial_research_agent.skills.cli bootstrap --actor system-bootstrap
```

初始化操作幂等；人工废弃的内置版本不会被下次启动自动重新激活。

## 3. 审核清单

1. 触发条件是否会误选无关问题；
2. `allowed_tools`是否只包含最小必要集合；
3. Evidence类型和数量是否能由现有数据源稳定产出；
4. 调用与并行上限是否不超过全局上限；
5. 冲突关系是否双向、可解释；
6. 正例、反例、越权和缺Evidence测试是否通过；
7. ID、版本、Checksum和替代关系是否正确。
