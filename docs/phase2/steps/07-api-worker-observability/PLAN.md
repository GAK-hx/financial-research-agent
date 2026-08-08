# Step 07 — Job API、Worker、SSE与可观测

## 目标

将持久化Graph包装为可查询、可取消、可恢复的Job服务，并在Docker中拆分API与Worker，提供不泄露隐藏推理的事件流和可观测性。

## 前置条件

- Gate 06已通过；
- Run/Event/Checkpoint/Cancel/Resume语义稳定；
- 日志脱敏和数据保留策略已确认。

## 子任务

1. 定义Run Create、Status、Result、Event、Cancel、Resume和Trace API Schema；
2. 实现`POST /runs`幂等创建和`GET /runs/{run_id}`状态查询；
3. 实现SSE事件流，包含阶段、节点、Tool、Budget警告和终态；
4. 实现Cancel/Resume，拒绝不合法状态转移与重复操作；
5. 实现Trace查询，仅返回可审计轨迹，不返回隐藏推理；
6. 实现Skill列表/详情与Session Memory查询/删除接口；
7. 将现有`app`拆为`api`与`worker`，共享版本化领域包而非共享进程内状态；
8. 第一版使用PostgreSQL原子领取Run和Lease，不引入Celery/Redis；
9. 实现Lease续期、过期回收、优雅停机和双Worker竞争控制；
10. 保留同步`POST /analyze`兼容，超时后返回Run ID而不取消后台Run；
11. 增加结构化日志、Correlation ID、节点时延、调用计数、Token/费用和错误指标；
12. 设定Compose资源上限、健康检查、Volume和启动顺序，记录单/双Worker资源数据。

## API范围

```text
POST   /runs
GET    /runs/{run_id}
GET    /runs/{run_id}/events
POST   /runs/{run_id}/cancel
POST   /runs/{run_id}/resume
GET    /runs/{run_id}/trace
GET    /skills
GET    /skills/{skill_id}
GET    /sessions/{session_id}/memory
DELETE /sessions/{session_id}/memory
POST   /analyze
```

## 测试清单

- 重复Idempotency Key不创建两个Run；
- SSE断线重连可从Event ID继续；
- 取消与完成竞态只产生一个合法终态；
- 重复Resume和过期Lease不重复副作用；
- 两个Worker不同时执行同一Attempt；
- API重启不中断Worker Run；
- SSE/Trace/日志不暴露隐藏推理和敏感凭证；
- `/analyze`的第一阶段客户端兼容测试通过。

## 交付物

- Job API、SSE、Cancel/Resume和Trace；
- PostgreSQL Run领取/租约Worker；
- API/Worker/PostgreSQL Docker Compose拆分；
- 指标、结构化日志和运维说明；
- 双Worker竞争与资源报告；
- 已更新的`PROGRESS.md`。

## Gate 07

- API、SSE、Cancel/Resume和同步兼容通过；
- 双Worker压测中重复Attempt和重复副作用为0；
- Docker一键启动和健康检查通过；
- 指标和日志能定位Run、节点和调用故障；
- 用户审核API与preview效果。

## 停止条件

若PostgreSQL领取无法在目标并发下保证唯一执行，暂停扩Worker，先重新评估队列中间件。
