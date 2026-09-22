from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from financial_research_agent.risk.models import DataAvailability, RiskFact

SOURCE_NAME = "akshare_eastmoney_financial_statement"
SOURCE_TIMEZONE = ZoneInfo("Asia/Shanghai")
MAPPING_VERSION = "eastmoney_risk_fact_v1"

STATEMENT_FIELD_MAP: dict[str, dict[str, tuple[str, str]]] = {
    "income": {
        "revenue": ("OPERATE_INCOME", "CNY"),
        "total_operating_income": ("TOTAL_OPERATE_INCOME", "CNY"),
        "parent_net_profit": ("PARENT_NETPROFIT", "CNY"),
        "interest_expense": ("FE_INTEREST_EXPENSE", "CNY"),
        "asset_impairment_loss": ("ASSET_IMPAIRMENT_LOSS", "CNY"),
        "credit_impairment_loss": ("CREDIT_IMPAIRMENT_LOSS", "CNY"),
    },
    "balance": {
        "current_assets": ("TOTAL_CURRENT_ASSETS", "CNY"),
        "current_liabilities": ("TOTAL_CURRENT_LIAB", "CNY"),
        "cash_and_equivalents": ("MONETARYFUNDS", "CNY"),
        "short_term_borrowings": ("SHORT_LOAN", "CNY"),
        "noncurrent_liabilities_due_within_one_year": ("NONCURRENT_LIAB_1YEAR", "CNY"),
        "accounts_receivable": ("ACCOUNTS_RECE", "CNY"),
        "notes_and_accounts_receivable": ("NOTE_ACCOUNTS_RECE", "CNY"),
        "inventory": ("INVENTORY", "CNY"),
        "goodwill": ("GOODWILL", "CNY"),
        "total_assets": ("TOTAL_ASSETS", "CNY"),
        "total_liabilities": ("TOTAL_LIABILITIES", "CNY"),
    },
    "cash_flow": {
        "operating_cash_flow": ("NETCASH_OPERATE", "CNY"),
        "ending_cash_equivalents": ("END_CASH_EQUIVALENTS", "CNY"),
    },
}


def _source_datetime(value) -> datetime | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    native = parsed.to_pydatetime()
    if native.tzinfo is None:
        native = native.replace(tzinfo=SOURCE_TIMEZONE)
    return native.astimezone(timezone.utc)


def _row_digest(row: pd.Series) -> str:
    payload = {
        str(key): None if pd.isna(value) else str(value)
        for key, value in sorted(row.items(), key=lambda item: str(item[0]))
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _opinion_fact(
    row: pd.Series,
    *,
    issuer_id: str,
    report_period,
    published_at: datetime,
    observed_at: datetime,
    source_record_id: str,
    content_sha256: str,
) -> RiskFact:
    raw = row.get("OPINION_TYPE")
    if pd.isna(raw) or not str(raw).strip():
        value = None
        availability = DataAvailability.NOT_DISCLOSED
    else:
        normalized = str(raw).strip().replace(" ", "")
        value = 0.0 if normalized in {"标准无保留意见", "无保留意见"} else 1.0
        availability = DataAvailability.PRESENT
    return RiskFact(
        issuer_id=issuer_id,
        report_period=report_period,
        metric_code="audit_opinion_flag",
        value=value,
        unit="boolean",
        availability=availability,
        source_name=SOURCE_NAME,
        source_record_id=f"{source_record_id}:OPINION_TYPE",
        source_published_at=published_at,
        observed_at=observed_at,
        content_sha256=content_sha256,
    )


def normalize_eastmoney_statement(
    raw: pd.DataFrame,
    statement: str,
    *,
    observed_at: datetime | None = None,
) -> tuple[list[RiskFact], list[dict[str, object]]]:
    if statement not in STATEMENT_FIELD_MAP:
        raise ValueError(f"unknown statement: {statement}")
    observed_at = observed_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    required_metadata = {"SECURITY_CODE", "REPORT_DATE", "NOTICE_DATE", "UPDATE_DATE"}
    missing_metadata = required_metadata - set(raw.columns)
    if missing_metadata:
        raise ValueError(f"source metadata fields missing: {sorted(missing_metadata)}")

    facts: list[RiskFact] = []
    rejected: list[dict[str, object]] = []
    for row_number, row in raw.iterrows():
        issuer_id = str(row.get("SECURITY_CODE", "")).strip().zfill(6)
        report_timestamp = pd.to_datetime(row.get("REPORT_DATE"), errors="coerce")
        notice_at = _source_datetime(row.get("NOTICE_DATE"))
        update_at = _source_datetime(row.get("UPDATE_DATE"))
        if (
            len(issuer_id) != 6
            or not issuer_id.isdigit()
            or pd.isna(report_timestamp)
            or notice_at is None
        ):
            rejected.append(
                {
                    "row_number": int(row_number),
                    "reason": "invalid_issuer_report_or_notice_date",
                }
            )
            continue
        published_at = max(value for value in (notice_at, update_at) if value is not None)
        if published_at > observed_at:
            rejected.append(
                {
                    "row_number": int(row_number),
                    "reason": "source_update_after_observation",
                }
            )
            continue
        report_period = report_timestamp.date()
        digest = _row_digest(row)
        record_root = (
            f"{issuer_id}:{statement}:{report_period.isoformat()}:"
            f"{published_at.isoformat()}:{digest[:12]}"
        )
        currency = str(row.get("CURRENCY", "")).strip().upper() or None
        if currency and (len(currency) != 3 or not currency.isalpha()):
            currency = None

        for metric_code, (source_field, unit) in STATEMENT_FIELD_MAP[statement].items():
            if source_field not in raw.columns:
                value = None
                availability = DataAvailability.NOT_AVAILABLE_FROM_SOURCE
            else:
                value = pd.to_numeric(row.get(source_field), errors="coerce")
                if pd.isna(value):
                    value = None
                    availability = DataAvailability.NOT_DISCLOSED
                else:
                    value = float(value)
                    availability = DataAvailability.PRESENT
            facts.append(
                RiskFact(
                    issuer_id=issuer_id,
                    report_period=report_period,
                    metric_code=metric_code,
                    value=value,
                    unit=unit,
                    currency=currency if unit == "CNY" else None,
                    availability=availability,
                    source_name=SOURCE_NAME,
                    source_record_id=f"{record_root}:{source_field}",
                    source_published_at=published_at,
                    observed_at=observed_at,
                    content_sha256=digest,
                )
            )
        if statement == "income":
            facts.append(
                _opinion_fact(
                    row,
                    issuer_id=issuer_id,
                    report_period=report_period,
                    published_at=published_at,
                    observed_at=observed_at,
                    source_record_id=record_root,
                    content_sha256=digest,
                )
            )
    return facts, rejected
