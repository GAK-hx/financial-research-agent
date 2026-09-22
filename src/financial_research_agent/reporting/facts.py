from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from financial_research_agent.domain.models import Evidence, ReportFact


SENTENCE_PATTERN = re.compile(r"[^\n。！？!?；;]+[。！？!?；;]?")
PERIOD_PATTERN = re.compile(r"(?:20\d{2}(?:E|年)?(?:[-—/]20\d{2}(?:E|年)?)?|\d{1,2}[QH])")
TARGET_PRICE_PATTERN = re.compile(
    r"(?:目标价(?:格)?|目标价格区间)[^。；\n]{0,32}?"
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>元|港元|美元)"
)
RATING_PATTERN = re.compile(
    r"(?:"
    r"(?:投资)?评级[^。；\n]{0,16}?"
    r"(?P<rating_after>强烈推荐|买入|增持|推荐|中性|持有|减持|卖出)"
    r"|"
    r"(?P<rating_before>强烈推荐|买入|增持|推荐|中性|持有|减持|卖出)"
    r"[^。；\n]{0,8}?评级"
    r")"
)
FORECAST_PATTERN = re.compile(
    r"(?P<metric>归母净利润|净利润|营业收入|营收|每股收益|EPS|ROE)"
    r"[^。；\n]{0,48}?"
    r"(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>亿元|百万元|万元|元|%|倍)"
)
METRIC_PATTERN = re.compile(
    r"(?P<metric>毛利率|净利率|市盈率|PE|市净率|PB|资产负债率)"
    r"[^。；\n]{0,32}?"
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|倍)"
)


def _fact_id(
    evidence_id: str,
    fact_type: str,
    source_span: str,
    discriminator: str,
) -> str:
    digest = hashlib.sha256(
        f"{evidence_id}|{fact_type}|{source_span}|{discriminator}".encode(
            "utf-8"
        )
    ).hexdigest()[:16]
    return f"fact_{digest}"


def _currency(unit: str) -> str | None:
    return {"元": "CNY", "港元": "HKD", "美元": "USD"}.get(unit)


class ReportFactExtractor:
    """Deterministically derive high-risk report facts with a source chain.

    These facts are derived artifacts. They never replace the original report
    Evidence and are created only from text already retrieved by the controlled
    report-content tool.
    """

    def extract(
        self,
        evidence: Iterable[Evidence],
        *,
        topics: Iterable[str] = (),
    ) -> list[ReportFact]:
        requested = set(topics)
        if not requested:
            return []
        facts: list[ReportFact] = []
        seen: set[str] = set()
        for item in evidence:
            if item.evidence_type != "research_report":
                continue
            text = str(item.data.get("text") or "")
            document_id = str(
                item.data.get("document_id")
                or item.source.metadata.get("document_id")
                or ""
            )
            page_number = item.data.get("page_number") or item.source.metadata.get(
                "page_number"
            )
            if not text or not document_id or not page_number:
                continue
            for match in SENTENCE_PATTERN.finditer(text):
                span = match.group().strip()[:1000]
                if not span:
                    continue
                period_match = PERIOD_PATTERN.search(span)
                period = period_match.group() if period_match else None
                if "target_price" in requested:
                    for target in TARGET_PRICE_PATTERN.finditer(span):
                        facts.append(
                            self._numeric_fact(
                                item,
                                document_id,
                                int(page_number),
                                span,
                                fact_type="target_price",
                                metric_name="目标价",
                                value=float(target.group("value")),
                                unit=target.group("unit"),
                                currency=_currency(target.group("unit")),
                                period=period,
                                seen=seen,
                            )
                        )
                if "rating" in requested:
                    for rating in RATING_PATTERN.finditer(span):
                        facts.append(
                            self._text_fact(
                                item,
                                document_id,
                                int(page_number),
                                span,
                                fact_type="rating",
                                metric_name="投资评级",
                                text_value=(
                                    rating.group("rating_after")
                                    or rating.group("rating_before")
                                ),
                                period=period,
                                seen=seen,
                            )
                        )
                if "earnings_forecast" in requested:
                    for forecast in FORECAST_PATTERN.finditer(span):
                        if period is None:
                            continue
                        facts.append(
                            self._numeric_fact(
                                item,
                                document_id,
                                int(page_number),
                                span,
                                fact_type="earnings_forecast",
                                metric_name=forecast.group("metric"),
                                value=float(forecast.group("value")),
                                unit=forecast.group("unit"),
                                currency=(
                                    "CNY"
                                    if forecast.group("unit")
                                    in {"亿元", "百万元", "万元", "元"}
                                    else None
                                ),
                                period=period,
                                seen=seen,
                            )
                        )
                    for metric in METRIC_PATTERN.finditer(span):
                        facts.append(
                            self._numeric_fact(
                                item,
                                document_id,
                                int(page_number),
                                span,
                                fact_type="financial_metric",
                                metric_name=metric.group("metric"),
                                value=float(metric.group("value")),
                                unit=metric.group("unit"),
                                currency=None,
                                period=period,
                                seen=seen,
                            )
                        )
                if "catalyst" in requested and re.search(
                    r"催化|驱动因素|积极因素", span
                ):
                    facts.append(
                        self._text_fact(
                            item,
                            document_id,
                            int(page_number),
                            span,
                            fact_type="catalyst",
                            metric_name=None,
                            text_value=span,
                            period=period,
                            seen=seen,
                        )
                    )
                if "risk" in requested and re.search(
                    r"风险提示|主要风险|不及预期|风险", span
                ):
                    facts.append(
                        self._text_fact(
                            item,
                            document_id,
                            int(page_number),
                            span,
                            fact_type="risk",
                            metric_name=None,
                            text_value=span,
                            period=period,
                            seen=seen,
                        )
                    )
        unique = {item.fact_id: item for item in facts}
        return list(unique.values())

    @staticmethod
    def _numeric_fact(
        evidence: Evidence,
        document_id: str,
        page_number: int,
        source_span: str,
        *,
        fact_type: str,
        metric_name: str,
        value: float,
        unit: str,
        currency: str | None,
        period: str | None,
        seen: set[str],
    ) -> ReportFact:
        fact_id = _fact_id(
            evidence.evidence_id,
            fact_type,
            source_span,
            f"{metric_name}:{value}:{unit}:{period}",
        )
        if fact_id in seen:
            return ReportFact(
                fact_id=fact_id,
                fact_type=fact_type,
                metric_name=metric_name,
                value=value,
                unit=unit,
                currency=currency,
                period=period,
                source_span=source_span,
                document_id=document_id,
                page_number=page_number,
                evidence_id=evidence.evidence_id,
            )
        seen.add(fact_id)
        return ReportFact(
            fact_id=fact_id,
            fact_type=fact_type,
            metric_name=metric_name,
            value=value,
            unit=unit,
            currency=currency,
            period=period,
            source_span=source_span,
            document_id=document_id,
            page_number=page_number,
            evidence_id=evidence.evidence_id,
        )

    @staticmethod
    def _text_fact(
        evidence: Evidence,
        document_id: str,
        page_number: int,
        source_span: str,
        *,
        fact_type: str,
        metric_name: str | None,
        text_value: str,
        period: str | None,
        seen: set[str],
    ) -> ReportFact:
        fact_id = _fact_id(
            evidence.evidence_id,
            fact_type,
            source_span,
            f"{metric_name}:{text_value}:{period}",
        )
        if fact_id not in seen:
            seen.add(fact_id)
        return ReportFact(
            fact_id=fact_id,
            fact_type=fact_type,
            metric_name=metric_name,
            text_value=text_value[:500],
            period=period,
            source_span=source_span,
            document_id=document_id,
            page_number=page_number,
            evidence_id=evidence.evidence_id,
        )
