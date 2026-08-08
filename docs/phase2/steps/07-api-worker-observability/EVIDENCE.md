# Step 07 验收证据

状态：`PASSED`

## 自动化

- 最终Docker镜像全量测试：122/122通过；
- PostgreSQL原子领取、幂等键、Lease续期/回收、取消与恢复通过；
- SSE游标、Trace脱敏、同步超时转后台Job和Worker单元测试通过；
- 旧同步`/analyze`兼容测试通过。

## 双Worker

- 20个受控任务，worker-1/worker-2领取9/11；
- 每个Job Attempt均为1；
- 重复Node Attempt组为0；
- 重复Tool副作用组为0；
- Worker-2可优雅停止并记录`worker_stopped`。

## 真实V4 Pro Job

Run ID：`5327af148f2a405e8e4bbb2e49d73c38`

- 相同Idempotency-Key两次提交得到同一Run，`created=true/false`；
- `financial_growth_analysis@1.0.0`选择正确；
- 1次Financial Tool、2次模型调用，均Attempt 1；
- 7090 Token、24603 microunits；
- 报告Validator与Completion Checker通过；
- SSE共34个事件，`Last-Event-ID`续传正确；
- Trace隐藏推理扫描为0。

## 进程解耦

Run `2404e7ea4e0a44e987ac371fd112248f`执行期间重启Job API，Worker未中断，
最终Attempt 1、Completed，证明队列与运行状态不依赖API进程内存。

## Gate 07

API、SSE、Cancel/Resume、同步兼容、API/Worker拆分、双Worker一致性、健康检查、
指标与资源边界均达到Step07要求。`Gate 07 = PASSED`。
