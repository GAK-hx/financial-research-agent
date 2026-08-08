# Step 06 失败输出

## 1. 20题首轮模型波动

首轮为16/20，失败题为`eval-02`、`eval-05`、`eval-14`、`eval-16`，均通过Intent、
Tool、Arguments和Citation评分，但报告数字一致性校验失败。按既定策略只重试这4题
一次，前三题恢复，最终19/20。

`eval-16`重试后的具体输出：

```json
{
  "http_status": 200,
  "request_id": "321edd08a60f4eff9081217aa2d22cc0",
  "run_id": "ef38d8333aba4383810922298fbb315e",
  "reporting_status": "validation_failed",
  "score_errors": [
    "NUMERIC_INCONSISTENT",
    "TASK_NOT_COMPLETED"
  ],
  "validation": {
    "passed": false,
    "errors": [
      "claim[4]:NUMERIC_UNSUPPORTED:-12.0"
    ],
    "warnings": []
  },
  "error": {
    "code": "ORCHESTRATION_FAILED",
    "message": "research orchestration failed",
    "details": {
      "errors": [
        "COMPLETION_REPORT_NOT_COMPLETED"
      ]
    }
  },
  "report_context": {
    "token_estimate_before": 11615,
    "token_estimate_after": 5530,
    "compression_ratio": 0.4761084804132587,
    "evidence_protection_passed": true
  },
  "revision_context": {
    "token_estimate_before": 12374,
    "token_estimate_after": 6289,
    "compression_ratio": 0.5082430903507354,
    "evidence_protection_passed": true
  }
}
```

结论：Context保护校验通过，失败来自模型在修订后仍生成Evidence不支持的`-12.0`，
受Validator与Completion Checker正确拦截；这与Step04的同一已知失败一致。
完整脱敏响应保存在
`artifacts/phase2_step06/context_gate/evaluation/runs/eval-16.json`。

## 2. A/B命令首次失败

首次尝试使用`python -c`内联定义异步函数，Python语法拒绝：

```text
File "<string>", line 1
  ... async def main():
      ^^^^^
SyntaxError: invalid syntax
```

修正：新增可复现模块`financial_research_agent.evaluation.context_ab`，不再依赖脆弱
的内联脚本。最终结果写入
`artifacts/phase2_step06/context_gate/context_ab.json`。
