from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel


class ProgramExecution(BaseModel):
    valid: bool
    value: float | str | None = None
    error: str | None = None
    steps_executed: int = 0


_BINARY_OPERATORS = {
    "add": lambda left, right: left + right,
    "subtract": lambda left, right: left - right,
    "multiply": lambda left, right: left * right,
    "divide": lambda left, right: left / right,
    "exp": lambda left, right: left**right,
    "greater": lambda left, right: "yes" if left > right else "no",
}
_TABLE_OPERATORS = {"table_max", "table_min", "table_sum", "table_average"}
_STEP_PATTERN = re.compile(r"([a-z_]+)\(([^()]*)\)")
_OFFICIAL_CONSTANTS = {1, 2, 3, 4, 5, 7, 8, 9, 10, 100, 1000, 1_000_000}


def _flatten_nested_program(program: str) -> str:
    """Compile a nested allowed expression into FinQA's sequential #n form."""
    stripped = program.strip()
    matches = list(_STEP_PATTERN.finditer(stripped))
    residual = _STEP_PATTERN.sub("", stripped).replace(",", "").strip()
    if matches and not residual:
        return stripped

    working = stripped
    steps: list[str] = []
    while match := _STEP_PATTERN.search(working):
        steps.append(match.group(0))
        reference = f"#{len(steps) - 1}"
        working = f"{working[:match.start()]}{reference}{working[match.end():]}"
    if steps and working.strip() == f"#{len(steps) - 1}":
        return ", ".join(steps)
    return stripped


def canonicalize_finqa_program(program: str) -> str:
    """Normalize constants and compile nested expressions to official sequential form."""
    program = _flatten_nested_program(program)

    def normalize_argument(raw: str) -> str:
        token = raw.strip()
        try:
            value = float(token)
        except ValueError:
            return token
        integer = int(value)
        if value != integer:
            return token
        if integer == -1:
            return "const_m1"
        if integer in _OFFICIAL_CONSTANTS:
            return f"const_{integer}"
        return token

    def replace_step(match: re.Match[str]) -> str:
        arguments = match.group(2).split(",", maxsplit=1)
        if len(arguments) != 2:
            return match.group(0)
        return (
            f"{match.group(1)}("
            f"{normalize_argument(arguments[0])}, "
            f"{normalize_argument(arguments[1])})"
        )

    return _STEP_PATTERN.sub(replace_step, program)


def _number(value: str, previous: list[float | str]) -> float | str:
    token = value.strip()
    if token.startswith("#"):
        index = int(token[1:])
        return previous[index]
    token = token.replace("$", "").replace(",", "")
    if token.startswith("const_"):
        token = token.removeprefix("const_").replace("m1", "-1")
    if token.endswith("%"):
        return float(token[:-1]) / 100
    return float(token)


def _table_values(table: list[list[Any]], row_name: str) -> list[float]:
    normalized_name = row_name.strip().strip('"\'').lower()
    for row in table:
        if row and str(row[0]).strip().lower() == normalized_name:
            values: list[float] = []
            for cell in row[1:]:
                raw = str(cell).replace("$", "").replace(",", "").strip()
                raw = raw.split("(")[0].strip()
                if raw:
                    values.append(float(raw.rstrip("%")) / (100 if raw.endswith("%") else 1))
            if values:
                return values
    raise ValueError(f"table row not found: {row_name}")


def execute_finqa_program(program: str, table: list[list[Any]]) -> ProgramExecution:
    """Execute the public FinQA operator subset without eval or arbitrary code."""
    try:
        matches = list(_STEP_PATTERN.finditer(program.strip()))
        if not matches:
            raise ValueError("program contains no executable operation")
        residual = _STEP_PATTERN.sub("", program).replace(",", "").strip()
        if residual:
            raise ValueError(f"unexpected program syntax: {residual}")
        results: list[float | str] = []
        for match in matches:
            operation = match.group(1)
            arguments = [item.strip() for item in match.group(2).split(",", maxsplit=1)]
            if len(arguments) != 2:
                raise ValueError(f"{operation} requires two arguments")
            if operation in _BINARY_OPERATORS:
                left = _number(arguments[0], results)
                right = _number(arguments[1], results)
                if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
                    raise ValueError(f"{operation} requires numeric arguments")
                value = _BINARY_OPERATORS[operation](float(left), float(right))
            elif operation in _TABLE_OPERATORS:
                values = _table_values(table, arguments[0])
                if operation == "table_max":
                    value = max(values)
                elif operation == "table_min":
                    value = min(values)
                elif operation == "table_sum":
                    value = sum(values)
                else:
                    value = sum(values) / len(values)
            else:
                raise ValueError(f"operator is not allowed: {operation}")
            results.append(value)
        final = results[-1]
        if isinstance(final, float):
            final = round(final, 5)
        return ProgramExecution(valid=True, value=final, steps_executed=len(results))
    except (IndexError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        return ProgramExecution(valid=False, error=str(exc), steps_executed=0)
