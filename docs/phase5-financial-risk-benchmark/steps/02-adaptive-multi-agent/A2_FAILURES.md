# V4FinBench A2失败记录

- 当前状态：`RESOLVED`；修复后固定参数LightGBM已完成全部五折。

## 2026-09-20：LightGBM系统运行库缺失

- 阶段：第0折可行性运行，尚未开始训练；
- 容器：`financial-research-agent-risk-eval:latest`；
- 原因：LightGBM Linux wheel依赖OpenMP运行库，`python:3.11-slim`未包含`libgomp.so.1`；
- 处理：在Dockerfile基础系统依赖中增加`libgomp1`后重建镜像；
- 数据与已完成A1产物未受影响。

```text
OSError: libgomp.so.1: cannot open shared object file: No such file or directory
```
