# DeepSeek V4 Flash 在线可行性输出

- 日期：2026-08-15
- 模型：`deepseek-v4-flash`
- 数据：完全合成的研报片段，不含本地文件、用户数据或真实持仓
- 目的：验证 `ReportFact -> Prompt -> fact_ids -> ReportValidator` 链路
- 结果：`PASS`

## 原始结构化结果

```json
{
  "model_name": "deepseek-v4-flash",
  "report": {
    "subjects": ["600519"],
    "summary": "示例证券在2026年8月14日发布的《合成研报样例》中，对贵州茅台给予买入评级，目标价为180元。",
    "summary_evidence_ids": ["flash-gate:report-1"],
    "claims": [
      {
        "claim": "示例证券在2026年8月14日发布的《合成研报样例》中给予贵州茅台买入评级。",
        "evidence_ids": ["flash-gate:report-1"],
        "fact_ids": ["fact_5c322b51aa1c7fac"],
        "confidence": "medium"
      },
      {
        "claim": "示例证券在2026年8月14日发布的《合成研报样例》中给出贵州茅台目标价为180元。",
        "evidence_ids": ["flash-gate:report-1"],
        "fact_ids": ["fact_e5a5091a93157f32"],
        "confidence": "medium"
      }
    ],
    "risks": [
      {
        "risk": "目标价和评级基于示例证券的模型和假设，可能因市场变化而调整。",
        "classification": "model_interpretation",
        "evidence_ids": ["flash-gate:report-1"],
        "confidence": "medium"
      }
    ],
    "limitations": [
      {
        "limitation": "仅基于一份合成研报，覆盖范围有限。",
        "category": "scope",
        "evidence_ids": ["flash-gate:report-1"]
      }
    ],
    "risk_vector": [
      {"dimension": "technical", "level": "unknown", "rationale": "未提供技术分析相关证据。", "evidence_ids": []},
      {"dimension": "fundamental", "level": "unknown", "rationale": "未提供基本面分析相关证据。", "evidence_ids": []},
      {"dimension": "event", "level": "unknown", "rationale": "未提供事件相关证据。", "evidence_ids": []},
      {"dimension": "data_confidence", "level": "medium", "rationale": "证据来自单一合成研报，置信度中等。", "evidence_ids": ["flash-gate:report-1"]}
    ],
    "scenarios": [
      {"name": "optimistic", "assumptions": ["示例证券的买入评级和180元目标价实现。"], "implication": "股价可能达到或超过目标价。", "evidence_ids": ["flash-gate:report-1"]},
      {"name": "base", "assumptions": ["示例证券的评级和目标价反映市场共识。"], "implication": "股价可能围绕目标价波动。", "evidence_ids": ["flash-gate:report-1"]},
      {"name": "stress", "assumptions": ["市场条件恶化或公司基本面变化。"], "implication": "股价可能低于目标价。", "evidence_ids": ["flash-gate:report-1"]}
    ],
    "data_as_of": "2026-08-14",
    "disclaimer": "仅供研究参考，不构成投资建议。"
  },
  "validation": {"passed": true, "errors": [], "warnings": []},
  "facts": [
    {
      "fact_id": "fact_e5a5091a93157f32",
      "fact_type": "target_price",
      "metric_name": "目标价",
      "value": 180.0,
      "unit": "元",
      "currency": "CNY",
      "period": null,
      "text_value": null,
      "source_span": "示例证券认为经营质量稳定，给予买入评级，目标价为180元。",
      "document_id": "synthetic-doc-1",
      "page_number": 2,
      "evidence_id": "flash-gate:report-1",
      "confidence": "medium",
      "extraction_method": "rule"
    },
    {
      "fact_id": "fact_5c322b51aa1c7fac",
      "fact_type": "rating",
      "metric_name": "投资评级",
      "value": null,
      "unit": null,
      "currency": null,
      "period": null,
      "text_value": "买入",
      "source_span": "示例证券认为经营质量稳定，给予买入评级，目标价为180元。",
      "document_id": "synthetic-doc-1",
      "page_number": 2,
      "evidence_id": "flash-gate:report-1",
      "confidence": "medium",
      "extraction_method": "rule"
    }
  ]
}
```

## 说明

首次启动本地脚本时缺少 `PYTHONPATH=src`，在发出模型请求前即终止；补充本地包路径后，
Flash 请求一次成功。模型正确复用了两个 `fact_id`，最终校验无错误、无警告。
