from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from datetime import timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

CHINA_TIMEZONE = ZoneInfo("Asia/Shanghai")
ANNUAL_REPORT = "annual_report"
RISK_EVENT_TYPES = {
    "financial_restatement",
    "regulatory_inquiry",
    "debt_or_liquidity_alert",
    "impairment",
    "earnings_forecast_revision",
}


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _direct_pdf_url(event: dict[str, Any]) -> str:
    query = parse_qs(urlparse(str(event["url"])).query)
    announcement_ids = query.get("announcementId", [])
    if not announcement_ids or not announcement_ids[0].isdigit():
        raise ValueError("announcementId missing from CNINFO detail URL")
    published = event["published_at"]
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    disclosure_date = published.astimezone(CHINA_TIMEZONE).date().isoformat()
    return (
        f"https://static.cninfo.com.cn/finalpage/{disclosure_date}/"
        f"{announcement_ids[0]}.PDF"
    )


def _load_events(disclosure_root: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in sorted((disclosure_root / "companies").glob("*/disclosure_events.parquet")):
        events.extend(pq.read_table(path).to_pylist())
    for event in events:
        event["event_types"] = set(json.loads(event.pop("event_types_json")))
    return events


def select_documents(
    disclosure_root: Path,
    *,
    risk_document_count: int = 10,
) -> list[dict[str, Any]]:
    events = _load_events(disclosure_root)
    selected: list[dict[str, Any]] = []
    issuer_ids = sorted({str(event["issuer_id"]) for event in events})
    for issuer_id in issuer_ids:
        annual = [
            event
            for event in events
            if str(event["issuer_id"]) == issuer_id
            and ANNUAL_REPORT in event["event_types"]
        ]
        if annual:
            picked = max(annual, key=lambda event: event["published_at"])
            picked["selection_role"] = "annual_report"
            selected.append(picked)

    selected_ids = {str(event["event_id"]) for event in selected}
    risk_events = [
        event
        for event in events
        if event["event_types"] & RISK_EVENT_TYPES
        and str(event["event_id"]) not in selected_ids
    ]
    risk_events.sort(key=lambda event: event["published_at"], reverse=True)
    for event in risk_events[:risk_document_count]:
        event["selection_role"] = "risk_event"
        selected.append(event)
    return selected


def _download(session, url: str, *, retries: int, backoff_seconds: float) -> bytes:
    errors: list[str] = []
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, timeout=(10, 90))
            response.raise_for_status()
            payload = response.content
            if not payload.startswith(b"%PDF"):
                raise ValueError(f"response is not PDF: {response.headers.get('content-type')}")
            return payload
        except Exception as exc:  # noqa: BLE001 - source errors belong in the audit artifact
            errors.append(f"attempt={attempt}: {type(exc).__name__}: {exc}")
            if attempt < retries:
                time.sleep(backoff_seconds * (2 ** (attempt - 1)))
    raise RuntimeError(" | ".join(errors))


def _inspect_pdf(path: Path, event: dict[str, Any]) -> dict[str, Any]:
    import pymupdf

    document = pymupdf.open(path)
    page_count = document.page_count
    sample_page_count = min(10, page_count)
    sample_text = "\n".join(document[index].get_text("text") for index in range(sample_page_count))
    document.close()
    compact = _compact_text(sample_text)
    issuer_name = _compact_text(str(event["issuer_name"]))
    issuer_id = str(event["issuer_id"])
    identity_match = issuer_name in compact or issuer_id in compact
    return {
        "page_count": page_count,
        "sample_page_count": sample_page_count,
        "sample_text_chars": len(sample_text),
        "issuer_identity_match": identity_match,
        "machine_document_passed": bool(
            page_count > 0 and len(compact) >= 100 and identity_match
        ),
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Step 01 巨潮资讯 PDF 文档抽检",
        "",
        f"- 计划抽检：{report['planned_documents']}",
        f"- 下载成功：{report['downloaded_documents']}",
        f"- 机器文档检查通过：{report['machine_passed_documents']}",
        f"- 机器通过率：{report['machine_pass_rate']:.4%}",
        f"- 状态：`{report['status']}`",
        "",
        "机器检查只验证 PDF 格式、可读性、页数及前10页的发行人身份，不替代人工核对具体数值、",
        "表格口径或风险事实。失败输入和错误原文保留在 report.json。",
        "",
        "| 代码 | 公司 | 公告 | 页数 | 身份匹配 | 机器检查 |",
        "|---|---|---|---:|---|---|",
    ]
    for item in report["documents"]:
        lines.append(
            f"| {item['issuer_id']} | {item['issuer_name']} | {item['title']} | "
            f"{item.get('page_count', '-')} | {item.get('issuer_identity_match', False)} | "
            f"{item.get('machine_document_passed', False)} |"
        )
    lines.extend(
        [
            "",
            "## 仍需人工完成",
            "",
            "- 按标注指南由独立复核人检查抽样数值和证据定位；",
            "- 人工签字前，`pdf_manual_audit_status` 保持 `pending_independent_human_review`。",
        ]
    )
    return "\n".join(lines) + "\n"


def write_manual_review_worksheet(
    root: Path,
    documents: list[dict[str, Any]],
    *,
    statement_root: Path,
) -> Path:
    review_path = root / "manual_numeric_review.csv"
    if review_path.exists():
        with review_path.open(encoding="utf-8-sig", newline="") as stream:
            previous = list(csv.DictReader(stream))
        if any(row.get("reviewer") or row.get("pdf_value") for row in previous):
            raise ValueError("manual worksheet contains human work; refusing overwrite")
    columns = [
        "event_id",
        "issuer_id",
        "issuer_name",
        "title",
        "pdf_path",
        "metric_code",
        "report_period",
        "api_value",
        "pdf_value",
        "unit",
        "page_or_table_locator",
        "matched",
        "reviewer",
        "reviewed_at",
        "notes",
    ]
    rows: list[dict[str, Any]] = []
    for item in documents:
        base = {
            "event_id": item["event_id"],
            "issuer_id": item["issuer_id"],
            "issuer_name": item["issuer_name"],
            "title": item["title"],
            "pdf_path": item.get("path", ""),
        }
        is_annual = item.get("selection_role") == "annual_report"
        if "selection_role" not in item:
            # Legacy manifests lack selection_role. A broad title classifier can
            # also tag a reply about an annual report as an annual document.
            title = str(item.get("title", ""))
            is_annual = bool(re.search(r"20\d{2}年?年度报告", title)) and not bool(
                re.search(r"问询|回复|专项说明|提示性公告", title)
            )
        if not is_annual:
            rows.append({**base, "notes": "Review document claim and evidence; not a numeric annual row"})
            continue
        fact_path = statement_root / "companies" / item["issuer_id"] / "risk_facts.parquet"
        if not fact_path.exists():
            rows.append({**base, "notes": "No matching API fact file"})
            continue
        annual = pq.read_table(fact_path).to_pandas()
        annual["report_period"] = annual["report_period"].astype(str)
        annual = annual[
            (annual["report_period"] == "2025-12-31")
            & (annual["metric_code"].isin(
                ["revenue", "parent_net_profit", "operating_cash_flow"]
            ))
        ]
        for fact in annual.itertuples(index=False):
            rows.append(
                {
                    **base,
                    "metric_code": fact.metric_code,
                    "report_period": fact.report_period,
                    "api_value": "" if fact.value is None else fact.value,
                    "unit": fact.unit,
                    "notes": "PDF numeric value may use yuan/wan-yuan; record conversion in notes",
                }
            )
    with review_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return review_path


def run_document_audit(
    root: Path,
    *,
    disclosure_root: Path,
    risk_document_count: int = 10,
    retries: int = 5,
    backoff_seconds: float = 3.0,
    statement_root: Path | None = None,
) -> tuple[Path, Path]:
    import requests

    root.mkdir(parents=True, exist_ok=True)
    pdf_root = root / "pdfs"
    pdf_root.mkdir(parents=True, exist_ok=True)
    events = select_documents(disclosure_root, risk_document_count=risk_document_count)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 Step01DocumentAudit/1.0",
            "Referer": "https://www.cninfo.com.cn/",
        }
    )
    documents: list[dict[str, Any]] = []
    for event in events:
        item = {
            "event_id": str(event["event_id"]),
            "issuer_id": str(event["issuer_id"]),
            "issuer_name": str(event["issuer_name"]),
            "title": str(event["title"]),
            "published_at": event["published_at"].isoformat(),
            "event_types": sorted(event["event_types"]),
            "selection_role": event.get("selection_role", "risk_event"),
            "detail_url": str(event["url"]),
        }
        try:
            pdf_url = _direct_pdf_url(event)
            item["pdf_url"] = pdf_url
            payload = _download(
                session,
                pdf_url,
                retries=retries,
                backoff_seconds=backoff_seconds,
            )
            path = pdf_root / f"{item['issuer_id']}-{item['event_id']}.pdf"
            path.write_bytes(payload)
            item.update(
                {
                    "status": "downloaded",
                    "path": str(path.relative_to(root)),
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    **_inspect_pdf(path, event),
                }
            )
        except Exception as exc:  # noqa: BLE001 - source errors belong in the audit artifact
            item.update(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "machine_document_passed": False,
                }
            )
        documents.append(item)

    downloaded = sum(item["status"] == "downloaded" for item in documents)
    passed = sum(bool(item["machine_document_passed"]) for item in documents)
    report = {
        "source": "CNINFO official disclosure PDFs",
        "selection": "latest annual report per issuer plus latest distinct risk-event documents",
        "planned_documents": len(events),
        "downloaded_documents": downloaded,
        "machine_passed_documents": passed,
        "machine_pass_rate": passed / len(events) if events else 0.0,
        "status": "MACHINE_PASS" if events and passed == len(events) else "PARTIAL",
        "pdf_manual_audit_status": "pending_independent_human_review",
        "documents": documents,
    }
    review_path = write_manual_review_worksheet(
        root,
        documents,
        statement_root=statement_root or root.parent / "correctness_pool_v1",
    )
    report["manual_numeric_review_path"] = str(review_path)
    json_path = root / "report.json"
    markdown_path = root / "report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and inspect sampled CNINFO PDFs")
    parser.add_argument("--root", default="/artifacts/phase5_step01/document_audit_v1")
    parser.add_argument(
        "--disclosure-root", default="/artifacts/phase5_step01/disclosure_pool_v1"
    )
    parser.add_argument("--risk-document-count", type=int, default=10)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--backoff-seconds", type=float, default=3.0)
    parser.add_argument(
        "--statement-root", default="/artifacts/phase5_step01/correctness_pool_v1"
    )
    parser.add_argument("--worksheet-only", action="store_true")
    args = parser.parse_args()
    if args.worksheet_only:
        root = Path(args.root)
        report = json.loads((root / "report.json").read_text(encoding="utf-8"))
        worksheet = write_manual_review_worksheet(
            root,
            report["documents"],
            statement_root=Path(args.statement_root),
        )
        print(json.dumps({"worksheet": str(worksheet)}, ensure_ascii=False))
        return
    paths = run_document_audit(
        Path(args.root),
        disclosure_root=Path(args.disclosure_root),
        risk_document_count=args.risk_document_count,
        retries=args.retries,
        backoff_seconds=args.backoff_seconds,
        statement_root=Path(args.statement_root),
    )
    print(json.dumps({"report": [str(path) for path in paths]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
