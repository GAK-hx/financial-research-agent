# FinQA程序规范化回归失败记录

## 2026-09-20：官方评分器依赖缺失

- 状态：`RESOLVED_WITH_EXISTING_APP_IMAGE`；
- 阶段：4道历史格式失败题已完成推理，准备运行官方FinQA评分器；
- 原因：新构建的risk-eval镜像没有显式安装官方评分脚本需要的`sympy`；
- 处理：把`sympy`加入项目核心依赖，当前评分先使用本项目已有且包含该依赖的app镜像；
- 影响：不影响4道题的推理结果，原始输出已落盘；后续重建的所有项目镜像都会包含该依赖。

```text
ModuleNotFoundError: No module named 'sympy'
```
