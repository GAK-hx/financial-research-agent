from __future__ import annotations

import hashlib
import html
import re
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from financial_research_agent.risk.domain.models import DisclosureEvent, DisclosureEventType

SOURCE_NAME = "akshare_cninfo_disclosure"
SOURCE_TIMEZONE = ZoneInfo("Asia/Shanghai")

EVENT_PATTERNS: tuple[tuple[DisclosureEventType, re.Pattern[str]], ...] = (
    (
        DisclosureEventType.FINANCIAL_RESTATEMENT,
        re.compile(r"前期会计差错|会计差错更正|更正后|财务报表更正|定期报告更正"),
    ),
    (
        DisclosureEventType.REGULATORY_INQUIRY,
        re.compile(r"问询函|监管函|关注函|纪律处分|行政处罚"),
    ),
    (
        DisclosureEventType.AUDIT_REPORT,
        re.compile(r"审计报告|审阅报告|审计意见|内部控制审计"),
    ),
    (
        DisclosureEventType.DEBT_OR_LIQUIDITY_ALERT,
        re.compile(r"债务逾期|未能清偿|违约|债务重组|流动性风险|偿债风险"),
    ),
    (DisclosureEventType.IMPAIRMENT, re.compile(r"减值|计提.{0,8}准备")),
    (
        DisclosureEventType.EARNINGS_FORECAST_REVISION,
        re.compile(r"业绩预告修正|业绩快报修正|业绩下修"),
    ),
    (DisclosureEventType.ANNUAL_REPORT, re.compile(r"年度报告(?!摘要)|年报(?!摘要)")),
)


def classify_title(title: str) -> list[DisclosureEventType]:
    title = clean_title(title)
    event_types = [event_type for event_type, pattern in EVENT_PATTERNS if pattern.search(title)]
    return event_types or [DisclosureEventType.OTHER]


def clean_title(title: str) -> str:
    without_tags = re.sub(r"<[^>]+>", "", html.unescape(title))
    return re.sub(r"\s+", " ", without_tags).strip()


def _published_at(value) -> datetime | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    native = parsed.to_pydatetime()
    if native.tzinfo is None:
        native = native.replace(tzinfo=SOURCE_TIMEZONE)
    return native.astimezone(timezone.utc)


def _event_digest(issuer_id: str, title: str, published_at: datetime, url: str) -> str:
    payload = "\x1f".join([issuer_id, title, published_at.isoformat(), url])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_disclosures(
    frames: dict[str, pd.DataFrame],
    *,
    observed_at: datetime | None = None,
) -> tuple[list[DisclosureEvent], list[dict[str, object]]]:
    observed_at = observed_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    required = {"代码", "简称", "公告标题", "公告时间", "公告链接"}
    grouped: dict[str, dict[str, object]] = {}
    tags: dict[str, set[str]] = defaultdict(set)
    rejected: list[dict[str, object]] = []
    for query_tag, frame in frames.items():
        missing = required - set(frame.columns)
        if missing:
            rejected.append(
                {"query_tag": query_tag, "reason": "missing_columns", "columns": sorted(missing)}
            )
            continue
        for row_number, row in frame.iterrows():
            issuer_id = str(row["代码"]).strip().zfill(6)
            issuer_name = str(row["简称"]).strip()
            title = clean_title(str(row["公告标题"]))
            url = str(row["公告链接"]).strip()
            published_at = _published_at(row["公告时间"])
            if (
                len(issuer_id) != 6
                or not issuer_id.isdigit()
                or not issuer_name
                or not title
                or published_at is None
                or not url.startswith(("http://", "https://"))
                or published_at > observed_at
            ):
                rejected.append(
                    {
                        "query_tag": query_tag,
                        "row_number": int(row_number),
                        "reason": "invalid_identity_title_date_or_url",
                    }
                )
                continue
            digest = _event_digest(issuer_id, title, published_at, url)
            grouped[digest] = {
                "issuer_id": issuer_id,
                "issuer_name": issuer_name,
                "title": title,
                "published_at": published_at,
                "url": url,
            }
            tags[digest].add(query_tag)
    events = [
        DisclosureEvent(
            event_id=f"disclosure-{digest[:24]}",
            issuer_id=str(item["issuer_id"]),
            issuer_name=str(item["issuer_name"]),
            title=str(item["title"]),
            published_at=item["published_at"],
            url=str(item["url"]),
            source_name=SOURCE_NAME,
            source_record_id=str(item["url"]),
            content_sha256=digest,
            query_tags=sorted(tags[digest]),
            event_types=classify_title(str(item["title"])),
            requires_document_review=True,
            observed_at=observed_at,
        )
        for digest, item in grouped.items()
    ]
    events.sort(key=lambda item: (item.issuer_id, item.published_at, item.event_id))
    return events, rejected
