from __future__ import annotations

import re
from datetime import date
from typing import Any

from financial_research_agent.domain.models import (
    Evidence,
    Intent,
    QuerySpec,
    ReportFact,
    ReportValidationProfile,
    ResearchReport,
    ValidationResult,
)
from financial_research_agent.memory.context import MAX_INLINE_EVIDENCE_ROWS
from financial_research_agent.reporting.facts import ReportFactExtractor

DATE_KEYS = {
    "data_as_of", "actual_end", "report_date", "as_of_date", "source_date",
    "published_at", "available_at",
}
STOCK_NAMES = {"600519": "贵州茅台", "300750": "宁德时代"}
NUMBER_PATTERN = re.compile(
    r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"(?:%|亿元|百万元|万元|元|倍|C)?"
)
DATE_TEXT_PATTERN = re.compile(
    r"\d{4}年\d{1,2}月\d{1,2}日|"
    r"\d{4}-\d{1,2}-\d{1,2}|"
    r"\d{1,2}月\d{1,2}日|"
    r"\d{4}(?:-\d{4})?年"
)
DURATION_RANGE_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:-|—|–|~|～|至|到)\s*"
    r"\d+(?:\.\d+)?\s*(?:个?月|年|周|天|日)"
)
POSITIVE_RANGE_SEPARATOR_PATTERN = re.compile(
    r"(?<=\d)\s*(?:-|—|–|~|～|至|到)\s*(?=\d)"
)
ORDINAL_LABEL_PATTERN = re.compile(
    r"(?:机构|候选)\s*\d+|第\s*\d+\s*(?:份|篇|页|个)"
)
NUMERIC_PREFIX_PATTERN = re.compile(
    r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
)
NEGATIVE_DIRECTION_PATTERN = re.compile(
    r"(?:微降|下降|下跌|下滑|减少|降低|回落|回撤|负增长)"
)
POSITIVE_DIRECTION_PATTERN = re.compile(
    r"(?:微增|增长|上升|增加|提高|回升|收窄)"
)
REPORT_STRUCTURED_NUMERIC_PATTERN = re.compile(
    r"目标价|目标价格|评级|盈利预测|每股收益|EPS|归母净利润|"
    r"营业收入|营收|毛利率|净利率|ROE|风险提示"
)
REPORT_CANDIDATE_DETAIL_PATTERN = re.compile(
    r"目标价|目标价格|评级|盈利预测|每股收益|EPS|归母净利润|"
    r"催化剂|风险提示|机构观点|研报认为|券商认为|详细观点"
)
RATING_VALUE_PATTERN = re.compile(
    r"强烈推荐|买入|增持|推荐|中性|持有|减持|卖出"
)


def _apply_direction(number: float, context: str) -> float:
    if number <= 0:
        return number
    directions = [
        (match.start(), -1)
        for match in NEGATIVE_DIRECTION_PATTERN.finditer(context)
    ]
    directions.extend(
        (match.start(), 1)
        for match in POSITIVE_DIRECTION_PATTERN.finditer(context)
    )
    if directions and max(directions)[1] < 0:
        return -number
    return number


def evidence_data_as_of(evidence: list[Evidence]) -> date | None:
    dates: list[date] = []

    def visit(value: Any, key: str | None = None) -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, child_key)
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif key in DATE_KEYS:
            if isinstance(value, date):
                dates.append(value)
            elif isinstance(value, str):
                try:
                    dates.append(date.fromisoformat(value[:10]))
                except ValueError:
                    pass

    for item in evidence:
        visit(item.data)
    return max(dates) if dates else None


def bind_report_data_as_of(
    report: ResearchReport, evidence: list[Evidence]
) -> ResearchReport:
    """Bind source-derived metadata that must never be guessed by the model."""
    latest = evidence_data_as_of(evidence)
    if latest is None or report.data_as_of == latest:
        return report
    return report.model_copy(update={"data_as_of": latest})


def bind_report_scope(
    report: ResearchReport, query: QuerySpec
) -> ResearchReport:
    """Deterministically mark unrequested analysis domains as unknown."""
    domain_by_dimension = {
        "technical": "market",
        "fundamental": "financial",
        "event": "event",
    }
    normalized = []
    for item in report.risk_vector:
        required_domain = domain_by_dimension.get(item.dimension)
        if required_domain and required_domain not in query.analysis_domains:
            item = item.model_copy(
                update={
                    "level": "unknown",
                    "rationale": "本次问题未请求该分析域，未执行对应数据工具。",
                    "evidence_ids": [],
                }
            )
        normalized.append(item)
    return report.model_copy(update={"risk_vector": normalized})


def _evidence_numbers(item: Evidence) -> list[float]:
    numbers: list[float] = []

    def add_token(token: str) -> None:
        numeric = NUMERIC_PREFIX_PATTERN.match(token)
        if numeric:
            numbers.append(float(numeric.group().replace(",", "")))

    def add_text(value: str) -> None:
        for token_match in NUMBER_PATTERN.finditer(value):
            token = token_match.group()
            add_token(token)
            numeric = NUMERIC_PREFIX_PATTERN.match(token)
            if not numeric:
                continue
            number = float(numeric.group().replace(",", ""))
            direction_context = value[
                max(0, token_match.start() - 24) : token_match.start()
            ]
            direction_context = re.split(r"[，。；,;]", direction_context)[-1]
            if "回撤" in direction_context:
                numbers.append(abs(number))
            directed = _apply_direction(number, direction_context)
            if directed != number:
                numbers.append(directed)

    def visit(value: Any, key: str | None = None) -> None:
        if key == "rows" and isinstance(value, list):
            if len(value) <= MAX_INLINE_EVIDENCE_ROWS:
                for child in value:
                    visit(child)
            return
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            numbers.append(float(value))
            if key is not None and "drawdown" in key.lower():
                numbers.append(abs(float(value)))
        elif isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, child_key)
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str):
            add_text(value)

    visit(item.data)
    visit(item.statement)
    visit(item.source.metadata)
    return numbers


def _claim_numbers(claim: str, stock_codes: list[str]) -> list[tuple[float, str, int]]:
    parsed: list[tuple[float, str, int]] = []
    numeric_claim = claim
    for stock_code in stock_codes:
        numeric_claim = numeric_claim.replace(stock_code, " " * len(stock_code))
    numeric_claim = DATE_TEXT_PATTERN.sub(
        lambda match: " " * len(match.group()), numeric_claim
    )
    numeric_claim = DURATION_RANGE_PATTERN.sub(
        lambda match: " " * len(match.group()), numeric_claim
    )
    numeric_claim = ORDINAL_LABEL_PATTERN.sub(
        lambda match: " " * len(match.group()), numeric_claim
    )
    numeric_claim = POSITIVE_RANGE_SEPARATOR_PATTERN.sub(" ", numeric_claim)
    for token_match in NUMBER_PATTERN.finditer(numeric_claim):
        token = token_match.group()
        numeric = NUMERIC_PREFIX_PATTERN.match(token)
        if not numeric:
            continue
        prefix = numeric_claim[max(0, token_match.start() - 2) : token_match.start()]
        suffix = numeric_claim[token_match.end() : token_match.end() + 8]
        if (
            re.search(r"[A-Za-z_]$", prefix)
            or re.match(r"[A-Za-z_]", suffix)
            or re.match(
                r"(?:日|天)(?:内|均线|均值|均量|平均成交量|相对成交量|成交量比|"
                r"波动率|最大回撤|回撤|动量|反转|流动性|Amihud|"
                r"数据|窗口|情况|期间|周期|样本|[）)])",
                suffix,
            )
        ):
            continue
        numeric_text = numeric.group()
        normalized_numeric_text = numeric_text.replace(",", "")
        decimal_places = len(normalized_numeric_text.partition(".")[2])
        value = float(normalized_numeric_text)
        broad_direction_context = numeric_claim[
            max(0, token_match.start() - 48) : token_match.start()
        ]
        direction_context = broad_direction_context
        direction_context = re.split(r"[，。；,;]", direction_context)[-1]
        # Drawdown is stored as a positive magnitude even when the following
        # prose describes the underlying price move as a decline.
        if "回撤" not in broad_direction_context:
            value = _apply_direction(value, direction_context)
        parsed.append((value, token[len(numeric_text) :], decimal_places))
    return parsed


def _number_supported(
    value: float, unit: str, decimal_places: int, candidates: list[float]
) -> bool:
    expected = [(value, 1.0)]
    if unit == "%":
        expected.append((value / 100.0, 0.01))
    elif unit == "亿元":
        expected.append((value * 100_000_000, 100_000_000.0))
        expected.append((value * 100, 100.0))
    elif unit == "百万元":
        expected.append((value * 1_000_000, 1_000_000.0))
    elif unit == "万元":
        expected.append((value * 10_000, 10_000.0))
    display_half_unit = 0.5 * (10**-decimal_places)
    for target, scale in expected:
        tolerance = max(1e-6, display_half_unit * scale, abs(target) * 1e-9)
        if any(abs(candidate - target) <= tolerance for candidate in candidates):
            return True
    return False


class ReportValidator:
    def validate(
        self,
        report: ResearchReport,
        query: QuerySpec,
        evidence: list[Evidence],
        run_id: str | None = None,
        *,
        report_facts: list[ReportFact] | None = None,
        validation_profile: str | None = None,
        selected_document_ids: set[str] | None = None,
    ) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        evidence_by_id = {item.evidence_id: item for item in evidence}
        request = query.report_request
        profile = validation_profile or (
            ReportValidationProfile.REPORT_ANALYSIS.value
            if request is not None and request.mode == "deep"
            else (
                ReportValidationProfile.CANDIDATE_LISTING.value
                if request is not None
                else None
            )
        )
        if report_facts is None and request is not None:
            report_facts = ReportFactExtractor().extract(
                evidence, topics=request.deep_topics
            )
        report_facts = report_facts or []
        facts_by_id = {item.fact_id: item for item in report_facts}
        selected_document_ids = selected_document_ids or set()
        if len(evidence_by_id) != len(evidence):
            errors.append("EVIDENCE_ID_DUPLICATE")
        if set(report.subjects) != set(query.stock_codes):
            errors.append("ENTITY_REPORT_SUBJECT_MISMATCH")
        latest = evidence_data_as_of(evidence)
        if latest is None:
            warnings.append("DATE_EVIDENCE_UNKNOWN")
        elif report.data_as_of != latest:
            errors.append(f"DATE_AS_OF_MISMATCH:expected={latest}:actual={report.data_as_of}")

        for fact in report_facts:
            source = evidence_by_id.get(fact.evidence_id)
            prefix = f"fact[{fact.fact_id}]"
            if source is None:
                errors.append(f"{prefix}:EVIDENCE_UNKNOWN:{fact.evidence_id}")
                continue
            if source.evidence_type != "research_report":
                errors.append(f"{prefix}:REPORT_EVIDENCE_REQUIRED")
                continue
            source_document_id = str(
                source.data.get("document_id")
                or source.source.metadata.get("document_id")
                or ""
            )
            source_page = source.data.get("page_number") or source.source.metadata.get(
                "page_number"
            )
            source_text = str(source.data.get("text") or "")
            if fact.document_id != source_document_id:
                errors.append(f"{prefix}:DOCUMENT_MISMATCH")
            if fact.page_number != source_page:
                errors.append(f"{prefix}:PAGE_MISMATCH")
            if fact.source_span not in source_text:
                errors.append(f"{prefix}:SOURCE_SPAN_MISMATCH")
            if selected_document_ids and fact.document_id not in selected_document_ids:
                errors.append(f"{prefix}:DOCUMENT_OUTSIDE_SELECTION")

        def resolve_citations(
            prefix: str,
            evidence_ids: list[str],
            *,
            required: bool,
        ) -> list[Evidence]:
            cited_items: list[Evidence] = []
            if required and not evidence_ids:
                errors.append(f"{prefix}:CITATION_MISSING")
                return cited_items
            if len(evidence_ids) != len(set(evidence_ids)):
                errors.append(f"{prefix}:CITATION_DUPLICATE")
            for evidence_id in evidence_ids:
                item = evidence_by_id.get(evidence_id)
                if item is None:
                    errors.append(f"{prefix}:CITATION_UNKNOWN:{evidence_id}")
                    continue
                if run_id is not None and not evidence_id.startswith(f"{run_id}:"):
                    errors.append(f"{prefix}:CITATION_WRONG_RUN:{evidence_id}")
                if item.subject not in query.stock_codes:
                    errors.append(f"{prefix}:ENTITY_EVIDENCE_MISMATCH:{item.subject}")
                if not item.source.locator.strip():
                    errors.append(
                        f"{prefix}:SOURCE_LOCATOR_MISSING:{item.evidence_id}"
                    )
                if item.evidence_type == "research_report" and selected_document_ids:
                    document_id = str(
                        item.data.get("document_id")
                        or item.source.metadata.get("document_id")
                        or ""
                    )
                    if document_id not in selected_document_ids:
                        errors.append(
                            f"{prefix}:REPORT_DOCUMENT_OUTSIDE_SELECTION:"
                            f"{item.evidence_id}"
                        )
                cited_items.append(item)
            return cited_items

        def validate_numbers(
            prefix: str,
            text: str,
            cited: list[Evidence],
        ) -> None:
            parsed = _claim_numbers(text, query.stock_codes)
            if not parsed:
                return
            report_citations = [
                item for item in cited if item.evidence_type == "research_report"
            ]
            non_report_citations = [
                item for item in cited if item.evidence_type != "research_report"
            ]
            if report_citations and not non_report_citations:
                # Natural-language report prose is not subjected to the generic
                # numeric regex. High-risk structured values still require a
                # typed fact linked to the same cited report Evidence.
                if not REPORT_STRUCTURED_NUMERIC_PATTERN.search(text):
                    return
                cited_ids = {item.evidence_id for item in report_citations}
                fact_candidates = [
                    fact.value
                    for fact in report_facts
                    if fact.evidence_id in cited_ids and fact.value is not None
                ]
                for value, unit, decimal_places in parsed:
                    if not _number_supported(
                        value, unit, decimal_places, fact_candidates
                    ):
                        errors.append(
                            f"{prefix}:REPORT_FACT_NUMERIC_UNSUPPORTED:{value}{unit}"
                        )
                return
            candidates = [
                number for item in cited for number in _evidence_numbers(item)
            ]
            for value, unit, decimal_places in parsed:
                if not _number_supported(
                    value, unit, decimal_places, candidates
                ):
                    errors.append(f"{prefix}:NUMERIC_UNSUPPORTED:{value}{unit}")

        summary_citations = resolve_citations(
            "summary", report.summary_evidence_ids, required=True
        )
        if (
            any(item.evidence_type == "report_candidate" for item in summary_citations)
            and REPORT_CANDIDATE_DETAIL_PATTERN.search(report.summary)
        ):
            errors.append("summary:REPORT_CANDIDATE_SCOPE_VIOLATION")
        if profile == ReportValidationProfile.CANDIDATE_LISTING.value and any(
            item.evidence_type == "research_report" for item in summary_citations
        ):
            errors.append("summary:REPORT_CONTENT_NOT_ALLOWED")
        validate_numbers("summary", report.summary, summary_citations)

        report_evidence_exists = any(item.evidence_type == "research_report" for item in evidence)
        for index, claim in enumerate(report.claims):
            prefix = f"claim[{index}]"
            cited = resolve_citations(
                prefix,
                claim.evidence_ids,
                required=True,
            )
            mentioned_codes = set(
                re.findall(
                    r"(?<![A-Za-z0-9.])\d{6}(?![A-Za-z0-9.])",
                    claim.claim,
                )
            )
            if not mentioned_codes.issubset(query.stock_codes):
                errors.append(f"{prefix}:ENTITY_CLAIM_MISMATCH")
            for code, name in STOCK_NAMES.items():
                if name in claim.claim and code not in query.stock_codes:
                    errors.append(f"{prefix}:ENTITY_CLAIM_MISMATCH:{name}")
            report_citations = [item for item in cited if item.evidence_type == "research_report"]
            candidate_citations = [
                item for item in cited if item.evidence_type == "report_candidate"
            ]
            if candidate_citations and REPORT_CANDIDATE_DETAIL_PATTERN.search(
                claim.claim
            ):
                errors.append(f"{prefix}:REPORT_CANDIDATE_SCOPE_VIOLATION")
            if (
                profile == ReportValidationProfile.CANDIDATE_LISTING.value
                and report_citations
            ):
                errors.append(f"{prefix}:REPORT_CONTENT_NOT_ALLOWED")
            for item in report_citations:
                page = item.source.metadata.get("page_number") or item.data.get("page_number")
                institution = item.data.get("institution")
                if not page:
                    errors.append(f"{prefix}:REPORT_PAGE_MISSING:{item.evidence_id}")
                if not institution or institution not in claim.claim:
                    errors.append(f"{prefix}:REPORT_ATTRIBUTION_MISSING:{item.evidence_id}")
            if not report_evidence_exists and re.search(r"(?:机构|券商|研报)(?:认为|指出|观点)", claim.claim):
                errors.append(f"{prefix}:REPORT_EVIDENCE_ABSENT")
            for fact_id in claim.fact_ids:
                fact = facts_by_id.get(fact_id)
                if fact is None:
                    errors.append(f"{prefix}:REPORT_FACT_UNKNOWN:{fact_id}")
                    continue
                if fact.evidence_id not in claim.evidence_ids:
                    errors.append(
                        f"{prefix}:REPORT_FACT_EVIDENCE_NOT_CITED:{fact_id}"
                    )
            if report_citations and RATING_VALUE_PATTERN.search(claim.claim):
                ratings = {
                    fact.text_value
                    for fact in report_facts
                    if fact.fact_type == "rating"
                    and fact.evidence_id in {item.evidence_id for item in report_citations}
                }
                mentioned = set(RATING_VALUE_PATTERN.findall(claim.claim))
                if not mentioned.intersection(ratings):
                    errors.append(f"{prefix}:REPORT_FACT_RATING_UNSUPPORTED")
            validate_numbers(prefix, claim.claim, cited)

        for index, risk in enumerate(report.risks):
            prefix = f"risk[{index}]"
            cited = resolve_citations(prefix, risk.evidence_ids, required=True)
            if risk.classification == "calculation" and not any(
                item.source.source_type == "calculation" for item in cited
            ):
                errors.append(f"{prefix}:CALCULATION_EVIDENCE_REQUIRED")
            validate_numbers(prefix, risk.risk, cited)

        for index, limitation in enumerate(report.limitations):
            prefix = f"limitation[{index}]"
            contains_number = bool(
                _claim_numbers(limitation.limitation, query.stock_codes)
            )
            cited = resolve_citations(
                prefix,
                limitation.evidence_ids,
                required=contains_number,
            )
            candidates = [
                number for item in cited for number in _evidence_numbers(item)
            ]
            for value, unit, decimal_places in _claim_numbers(
                limitation.limitation, query.stock_codes
            ):
                if not _number_supported(value, unit, decimal_places, candidates):
                    errors.append(f"{prefix}:NUMERIC_UNSUPPORTED:{value}{unit}")
        for index, dimension in enumerate(report.risk_vector):
            resolve_citations(
                f"risk_vector[{index}]",
                dimension.evidence_ids,
                required=dimension.level != "unknown",
            )
        for index, scenario in enumerate(report.scenarios):
            resolve_citations(
                f"scenario[{index}]",
                scenario.evidence_ids,
                required=False,
            )
        advanced = query.intent in {
            Intent.TECHNICAL,
            Intent.FUNDAMENTAL,
            Intent.EVENT,
            Intent.SCREENING,
            Intent.FACTOR,
        } or bool(
            {"technical_analysis", "fundamental_analysis", "event", "factor"}
            .intersection(query.dimensions)
        )
        if advanced:
            dimensions = {item.dimension for item in report.risk_vector}
            expected_dimensions = {
                "technical", "fundamental", "event", "data_confidence"
            }
            if dimensions != expected_dimensions:
                warnings.append("RISK_VECTOR_INCOMPLETE")
            scenario_names = {item.name for item in report.scenarios}
            if scenario_names != {"optimistic", "base", "stress"}:
                warnings.append("SCENARIOS_INCOMPLETE")
        if not report.risks:
            errors.append("RISKS_MISSING")
        if "不构成投资建议" not in report.disclaimer:
            errors.append("DISCLAIMER_MISSING")
        return ValidationResult(passed=not errors, errors=errors, warnings=warnings)
