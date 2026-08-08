# Step 09 — 阶段验收与交付

## 目标

对功能、治理、恢复、评测、Docker部署和文档进行统一验收，形成可演示、可面试说明、可继续迭代的第二阶段基线。

## 前置条件

- Gate 08已通过；
- 阻断性安全、一致性和Evidence缺陷为0；
- 候选版本的代码、配置、镜像、Skill、Prompt和数据Snapshot已冻结。

## 子任务

1. 逐项审核`CHECKLIST.md`，每项链接到测试、报告或运行证据；
2. 从空环境构建镜像并使用Docker Compose启动全部必需服务；
3. 执行数据/数据库初始化、健康检查、烟雾测试和一次完整Run；
4. 执行关键Regression、恢复、越权、Budget、Memory隔离和SSE断线重连验收；
5. 实测单Worker和双Worker的CPU、内存、磁盘、P50/P95、Token和费用；
6. 验证备份/恢复、Checkpoint清理、Memory TTL和Artifact保留操作手册；
7. 更新README、架构图、API说明、Docker说明、Skill手册和Memory说明；
8. 生成一份演示脚本：提交Run → SSE → Tool/Evidence → 报告 → Trace → Resume；
9. 生成技术总结，准确区分LangGraph能力和项目自研治理层；
10. 记录已知限制：日线/中长期数据、只读研究、Replan=0、非自动交易；
11. 记录后续候选：更多数据源、Skill编辑器、队列中间件、更强评测和受控Replan；
12. 由用户进行最终人工验收，通过后关闭第二阶段。

## 必须披露的边界

- LangGraph提供图运行、Checkpoint和恢复能力；
- 项目自身实现Skill Registry、Tool/Model Gateway、Policy/Budget、Evidence/Validator和Memory规则；
- Hermes和Pi仅作设计参考，未将其整套运行时冒充为项目实现；
- 评测数字仅来自冻结版本和已保存原始结果。

## 交付物

- 已签字的验收清单与阶段报告；
- 可复现Docker Compose、配置模板和运维手册；
- 演示脚本、技术总结和已知限制；
- 冻结的Regression/Holdout/稳定性报告；
- 已更新的阶段与步骤`PROGRESS.md`。

## Gate 09

- `CHECKLIST.md`必须项全部通过并有证据；
- 从空环境可依文档部署、运行、恢复和删除Memory；
- 架构、评测数据和简历表述一致；
- 用户完成人工验收并确认阶段关闭。

## 停止条件

任何必须项缺少可重复证据，或简历表述超出已实现能力，不关闭第二阶段。
