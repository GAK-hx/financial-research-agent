from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from financial_research_agent.domain.models import (
    Intent,
    QuerySpec,
    ResolvedTimeExpression,
)

STOCK_ALIASES = {
    "贵州茅台": "600519",
    "茅台": "600519",
    "600519": "600519",
    "宁德时代": "300750",
    "宁德": "300750",
    "300750": "300750",
    "中国平安": "601318", "招商银行": "600036", "兴业银行": "601166",
    "长江电力": "600900", "紫金矿业": "601899", "中信证券": "600030",
    "中国神华": "601088", "恒瑞医药": "600276", "平安银行": "000001",
    "美的集团": "000333", "格力电器": "000651", "五粮液": "000858",
    "比亚迪": "002594", "海康威视": "002415", "立讯精密": "002475",
    "东方财富": "300059", "迈瑞医疗": "300760", "京东方A": "000725",
}

MARKET_TERMS = ("股价", "行情", "走势", "涨跌", "收益率", "波动", "回撤", "均线", "成交量")
REPORT_TERMS = ("研报", "观点", "机构", "券商", "研究报告")
FINANCIAL_TERMS = ("财务", "营收", "收入", "利润", "净利润", "现金流", "毛利率", "负债率", "ROE")
EVENT_TERMS = ("事件", "公告", "新闻", "舆情", "时间线", "影响")
FACTOR_TERMS = ("因子", "截面", "筛选", "排名", "股票池")
TECHNICAL_INTENT_TERMS = ("技术分析", "技术面", "量价", "动量", "技术指标")
FUNDAMENTAL_INTENT_TERMS = ("基本面", "基本面分析")
COMPARISON_TERMS = ("比较", "对比")

DIMENSION_TERMS = {
    "technical_analysis": TECHNICAL_INTENT_TERMS,
    "fundamental_analysis": FUNDAMENTAL_INTENT_TERMS,
    "return": ("收益率", "涨跌", "表现", "走势"),
    "volatility": ("波动",),
    "drawdown": ("回撤",),
    "trend": ("均线", "趋势"),
    "volume": ("成交量", "放量", "缩量"),
    "financial_growth": ("营收", "收入", "利润", "增长"),
    "profitability": ("毛利率", "ROE", "盈利能力"),
    "leverage": ("负债率", "杠杆"),
    "institution_view": ("研报", "观点", "机构", "券商"),
    "momentum": ("动量",),
    "liquidity": ("流动性", "Amihud"),
    "factor": ("因子",),
    "cross_section": ("截面", "筛选", "排名", "股票池"),
    "event": ("事件", "公告", "新闻", "舆情", "时间线"),
    "concise": ("简版", "简洁", "精简"),
    "risk": ("风险优先", "重点风险", "风险"),
}


def _subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year, zero_month = divmod(month_index, 12)
    month = zero_month + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _previous_business_day(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _business_day_start(end: date, quantity: int) -> date:
    candidate = end
    remaining = quantity - 1
    while remaining:
        candidate -= timedelta(days=1)
        if candidate.weekday() < 5:
            remaining -= 1
    return candidate


def _first_day_of_month(value: date) -> date:
    return date(value.year, value.month, 1)


def _first_day_of_quarter(value: date) -> date:
    quarter_month = ((value.month - 1) // 3) * 3 + 1
    return date(value.year, quarter_month, 1)


COMPLETE_PERIOD_PATTERN = re.compile(
    r"(?:最近|近)(?P<count>\d+|一个|一|两|二|三|四|五|六)?个?完整"
    r"(?P<trading>交易)?(?P<unit>季度|季|月|年|日|天)"
)
CHINESE_QUANTITIES = {
    None: 1,
    "一": 1,
    "一个": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
}


class QueryInterpreter:
    def __init__(
        self,
        today: date | None = None,
        timezone_name: str = "Asia/Shanghai",
    ) -> None:
        self.timezone_name = timezone_name
        self.today = today or datetime.now(ZoneInfo(timezone_name)).date()

    def interpret(self, question: str) -> QuerySpec:
        stock_codes = self._stocks(question)
        intent = self._intent(question)
        analysis_domains = self._domains(question)
        time_scope = self.resolve_time_expression(question, intent)
        dimensions = self._dimensions(question)
        return QuerySpec(
            stock_codes=stock_codes,
            start_date=time_scope.start_date,
            end_date=time_scope.end_date,
            intent=intent,
            dimensions=dimensions[:8],
            analysis_domains=analysis_domains,
            time_scope=time_scope,
        )

    @staticmethod
    def _dimensions(question: str) -> list[str]:
        lowered = question.lower()
        return [
            name
            for name, terms in DIMENSION_TERMS.items()
            if any(term.lower() in lowered for term in terms)
        ]

    @staticmethod
    def _stocks(question: str) -> list[str]:
        positions: list[tuple[int, str]] = []
        for alias, code in STOCK_ALIASES.items():
            position = question.find(alias)
            if position >= 0:
                positions.append((position, code))
        for match in re.finditer(r"(?<!\d)\d{6}(?!\d)", question):
            positions.append((match.start(), match.group()))
        codes: list[str] = []
        for _, code in sorted(positions):
            if code not in codes:
                codes.append(code)
        if not codes:
            raise ValueError("question must identify an allowed stock")
        return codes

    @staticmethod
    def _intent(question: str) -> Intent:
        domains = QueryInterpreter._domains(question)
        if len(domains) >= 2:
            return Intent.COMPREHENSIVE
        if "factor" in domains:
            return Intent.FACTOR
        if "event" in domains:
            return Intent.EVENT
        # A comparison over multiple securities is a cross-sectional request,
        # even when the requested dimensions contain words such as “technical”.
        # Route it before the single-security analysis intents so the harness can
        # expose one bounded stock_comparison tool instead of N single-stock calls.
        if (
            any(term in question for term in COMPARISON_TERMS)
            and len(QueryInterpreter._stocks(question)) >= 2
        ):
            return Intent.SCREENING
        if any(term.lower() in question.lower() for term in TECHNICAL_INTENT_TERMS):
            return Intent.TECHNICAL
        if any(term.lower() in question.lower() for term in FUNDAMENTAL_INTENT_TERMS):
            return Intent.FUNDAMENTAL
        if domains == ["financial"]:
            return Intent.FINANCIAL
        if domains == ["report"]:
            return Intent.REPORT
        return Intent.MARKET

    @staticmethod
    def _domains(question: str) -> list[str]:
        lowered = question.lower()
        factor = any(term.lower() in lowered for term in FACTOR_TERMS)
        technical = any(term.lower() in lowered for term in TECHNICAL_INTENT_TERMS)
        fundamental = any(
            term.lower() in lowered for term in FUNDAMENTAL_INTENT_TERMS
        )
        market = any(term.lower() in lowered for term in MARKET_TERMS) or technical
        report = any(term.lower() in lowered for term in REPORT_TERMS)
        financial = (
            any(term.lower() in lowered for term in FINANCIAL_TERMS) or fundamental
        )
        event = any(term.lower() in lowered for term in EVENT_TERMS)
        if factor:
            # “动量因子”或“ROE 因子”描述的是因子类别，不应被误判为
            # 同时请求技术面/基本面分析；只有用户明确写出分析域时才保留。
            market = market and any(
                term in lowered for term in ("技术面", "技术分析", "行情", "股价")
            )
            financial = financial and any(
                term in lowered for term in ("基本面", "财务分析", "财务")
            )
        domains = [
            name
            for name, active in (
                ("market", market),
                ("financial", financial),
                ("report", report),
                ("event", event),
                ("factor", factor),
            )
            if active
        ]
        return domains or ["market"]

    def resolve_time_expression(
        self, question: str, intent: Intent
    ) -> ResolvedTimeExpression:
        iso_dates = [date.fromisoformat(value) for value in re.findall(r"\d{4}-\d{2}-\d{2}", question)]
        if len(iso_dates) >= 2:
            return ResolvedTimeExpression(
                original_text=f"{iso_dates[0].isoformat()}..{iso_dates[1].isoformat()}",
                kind="absolute_range",
                granularity="day",
                start_date=iso_dates[0],
                end_date=iso_dates[1],
            )
        chinese_dates = [
            date(int(year), int(month), int(day))
            for year, month, day in re.findall(r"(\d{4})年(\d{1,2})月(\d{1,2})日", question)
        ]
        if len(chinese_dates) >= 2:
            return ResolvedTimeExpression(
                original_text=f"{chinese_dates[0].isoformat()}..{chinese_dates[1].isoformat()}",
                kind="absolute_range",
                granularity="day",
                start_date=chinese_dates[0],
                end_date=chinese_dates[1],
            )
        complete = COMPLETE_PERIOD_PATTERN.search(question)
        if complete:
            raw_count = complete.group("count")
            quantity = (
                int(raw_count)
                if raw_count and raw_count.isdigit()
                else CHINESE_QUANTITIES[raw_count]
            )
            unit = complete.group("unit")
            trading = bool(complete.group("trading"))
            start_date, end_date, granularity = self._complete_period(
                unit, quantity
            )
            return ResolvedTimeExpression(
                original_text=complete.group(0),
                kind="complete_period",
                granularity=granularity,
                quantity=quantity,
                start_date=start_date,
                end_date=end_date,
                complete_period=True,
                calendar=("trading" if trading or granularity == "day" else "calendar"),
            )
        if "今年" in question:
            return ResolvedTimeExpression(
                original_text="今年",
                kind="calendar_period",
                granularity="year",
                quantity=1,
                start_date=date(self.today.year, 1, 1),
                end_date=self.today,
            )
        if "去年" in question:
            return ResolvedTimeExpression(
                original_text="去年",
                kind="calendar_period",
                granularity="year",
                quantity=1,
                start_date=date(self.today.year - 1, 1, 1),
                end_date=date(self.today.year - 1, 12, 31),
                complete_period=True,
            )
        relative_patterns = (
            (
                r"(?:最近|近)(\d+)天",
                "day",
                lambda value: self.today - timedelta(days=value),
            ),
            (
                r"(?:最近|近)(\d+)个?月",
                "month",
                lambda value: _subtract_months(self.today, value),
            ),
            (
                r"(?:最近|近)(\d+)年",
                "year",
                lambda value: _subtract_months(self.today, value * 12),
            ),
        )
        aliases = {
            "一个月": ("month", 1, 1),
            "两个月": ("month", 2, 2),
            "三个月": ("month", 3, 3),
            "六个月": ("month", 6, 6),
            "半年": ("month", 6, 6),
            "一年": ("year", 1, 12),
            "两年": ("year", 2, 24),
            "三年": ("year", 3, 36),
            "五年": ("year", 5, 60),
        }
        for label, (granularity, quantity, months) in aliases.items():
            if f"最近{label}" in question or f"近{label}" in question:
                return ResolvedTimeExpression(
                    original_text=(f"最近{label}" if f"最近{label}" in question else f"近{label}"),
                    kind="relative_rolling",
                    granularity=granularity,
                    quantity=quantity,
                    start_date=_subtract_months(self.today, months),
                    end_date=self.today,
                )
        for pattern, granularity, calculate in relative_patterns:
            match = re.search(pattern, question)
            if match:
                quantity = int(match.group(1))
                return ResolvedTimeExpression(
                    original_text=match.group(0),
                    kind="relative_rolling",
                    granularity=granularity,
                    quantity=quantity,
                    start_date=calculate(quantity),
                    end_date=self.today,
                )
        if "最新" in question and intent == Intent.REPORT:
            return ResolvedTimeExpression(
                original_text="最新",
                kind="latest_available",
                granularity="unspecified",
                calendar="not_applicable",
            )
        if intent in {
            Intent.MARKET, Intent.TECHNICAL, Intent.FINANCIAL, Intent.FUNDAMENTAL,
            Intent.SCREENING, Intent.FACTOR, Intent.EVENT, Intent.COMPREHENSIVE,
        }:
            return ResolvedTimeExpression(
                kind="default_window",
                granularity="year",
                quantity=1,
                start_date=_subtract_months(self.today, 12),
                end_date=self.today,
            )
        return ResolvedTimeExpression(
            kind="not_applicable",
            granularity="unspecified",
            calendar="not_applicable",
        )

    def _complete_period(
        self, unit: str, quantity: int
    ) -> tuple[date, date, str]:
        if unit in {"日", "天"}:
            end = _previous_business_day(self.today)
            return _business_day_start(end, quantity), end, "day"
        if unit == "月":
            end = _first_day_of_month(self.today) - timedelta(days=1)
            start = _subtract_months(_first_day_of_month(end), quantity - 1)
            return start, end, "month"
        if unit in {"季", "季度"}:
            end = _first_day_of_quarter(self.today) - timedelta(days=1)
            start = _subtract_months(_first_day_of_quarter(end), 3 * (quantity - 1))
            return start, end, "quarter"
        if unit == "年":
            return (
                date(self.today.year - quantity, 1, 1),
                date(self.today.year - 1, 12, 31),
                "year",
            )
        raise ValueError(f"unsupported complete period unit: {unit}")

    def _dates(self, question: str, intent: Intent) -> tuple[date | None, date | None]:
        resolved = self.resolve_time_expression(question, intent)
        return resolved.start_date, resolved.end_date
