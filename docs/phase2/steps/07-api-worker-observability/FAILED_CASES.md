# Step 07 失败输出

## 1. 新建Job对象提交后的ORM属性失效

首次PostgreSQL专项测试为2项通过、3项错误：

```text
sqlalchemy.orm.exc.DetachedInstanceError:
Instance <ResearchJobRecord ...> is not bound to a Session;
attribute refresh operation cannot proceed
```

原因：`updated_at`由数据库生成，事务提交后才构造API Snapshot，属性已脱离Session。
修正为事务内`flush + refresh + snapshot`，复测通过。

## 2. 专项测试遗留队列干扰

修正上述错误后，历史失败测试留下的Queued记录先被领取，导致：

```text
AssertionError: 2 != 1
AssertionError: recovered.run_id != first.run_id
```

修正：PostgreSQL测试使用专用租户并在每个测试前清理该租户遗留Job。生产领取逻辑
无需修改。

## 3. 全量回归第一次

结果：120/122。两个第一阶段同步API测试继承了Job API容器环境变量
`ANALYZE_VIA_JOBS=true`，误走真实队列：

```text
FAIL: test_health_tools_and_successful_analyze
AssertionError: '<generated-run-id>' != 'api-run-001'

FAIL: test_partial_failure_keeps_run_and_evidence
AssertionError: True is not false
```

修正：旧同步兼容测试显式设置`analyze_via_jobs=False`，隔离部署环境。

## 4. 全量回归第二次

结果：121/122。真实`job-worker-1`与测试进程共享PostgreSQL，抢先领取测试Job：

```text
FAIL: test_idempotency_and_two_worker_atomic_claim
AssertionError: 0 != 1
```

该结果说明真实Worker正在正确监听队列，但自动化环境未隔离。停止真实Worker后，
最终全量回归122/122通过，无代码修改。
