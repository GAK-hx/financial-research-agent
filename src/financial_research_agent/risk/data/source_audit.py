from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa

from financial_research_agent.data_management.storage import RawBatchStore


@dataclass(frozen=True)
class Probe:
    name: str
    endpoint: str
    parameters: dict[str, Any]


def _market_symbol(stock_code: str, *, uppercase: bool = False) -> str:
    prefix = "SH" if stock_code.startswith("6") else "SZ"
    value = f"{prefix}{stock_code}"
    return value if uppercase else value.lower()


def default_probes(stock_code: str, start_date: str, end_date: str) -> list[Probe]:
    return [
        Probe(
            name="sina_income",
            endpoint="stock_financial_report_sina",
            parameters={"stock": _market_symbol(stock_code), "symbol": "利润表"},
        ),
        Probe(
            name="eastmoney_income",
            endpoint="stock_profit_sheet_by_report_em",
            parameters={"symbol": _market_symbol(stock_code, uppercase=True)},
        ),
        Probe(
            name="eastmoney_balance",
            endpoint="stock_balance_sheet_by_report_em",
            parameters={"symbol": _market_symbol(stock_code, uppercase=True)},
        ),
        Probe(
            name="eastmoney_cash_flow",
            endpoint="stock_cash_flow_sheet_by_report_em",
            parameters={"symbol": _market_symbol(stock_code, uppercase=True)},
        ),
        Probe(
            name="cninfo_annual_reports",
            endpoint="stock_zh_a_disclosure_report_cninfo",
            parameters={
                "symbol": stock_code,
                "market": "沪深京",
                "category": "年报",
                "start_date": start_date,
                "end_date": end_date,
            },
        ),
        Probe(
            name="cninfo_corrections",
            endpoint="stock_zh_a_disclosure_report_cninfo",
            parameters={
                "symbol": stock_code,
                "market": "沪深京",
                "category": "补充更正",
                "start_date": start_date,
                "end_date": end_date,
            },
        ),
    ]


def _frame_digest(frame: pd.DataFrame) -> str:
    payload = frame.to_json(
        orient="split",
        date_format="iso",
        date_unit="us",
        force_ascii=False,
        default_handler=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _probe_worker(endpoint_name: str, parameters: dict[str, Any], connection) -> None:
    try:
        import akshare as ak

        endpoint = getattr(ak, endpoint_name)
        frame = endpoint(**parameters)
        connection.send(("success", frame))
    except Exception as exc:
        connection.send(("error", type(exc).__name__, str(exc)))
    finally:
        connection.close()


def _call_once(
    endpoint_name: str,
    parameters: dict[str, Any],
    timeout_seconds: float,
) -> pd.DataFrame:
    context = multiprocessing.get_context("spawn")
    receive_connection, send_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_probe_worker,
        args=(endpoint_name, parameters, send_connection),
        daemon=True,
    )
    process.start()
    send_connection.close()
    if not receive_connection.poll(timeout_seconds):
        if process.is_alive():
            process.terminate()
        process.join(5)
        receive_connection.close()
        raise TimeoutError(f"endpoint exceeded hard timeout of {timeout_seconds:g}s")
    result = receive_connection.recv()
    receive_connection.close()
    process.join(5)
    if process.is_alive():
        process.terminate()
        process.join(5)
    if result[0] == "error":
        raise RuntimeError(f"{result[1]}:{result[2]}")
    frame = result[1]
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"endpoint returned {type(frame).__name__}, expected DataFrame")
    return frame


def _call_with_retry(
    endpoint_name: str,
    parameters: dict[str, Any],
    *,
    retries: int,
    initial_backoff_seconds: float,
    call_timeout_seconds: float,
) -> tuple[pd.DataFrame | None, list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    for attempt in range(retries + 1):
        try:
            frame = _call_once(endpoint_name, parameters, call_timeout_seconds)
            return frame, errors
        except Exception as exc:
            errors.append(
                {
                    "attempt": attempt + 1,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            )
            if attempt >= retries:
                break
            delay = min(initial_backoff_seconds * (2**attempt), 90.0)
            time.sleep(delay + random.uniform(0.0, min(2.0, delay * 0.1)))
    return None, errors


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 数据源探测报告",
        "",
        f"- Run：`{report['run_id']}`",
        f"- 股票：`{report['stock_code']}`",
        f"- AkShare：`{report['akshare_version']}`",
        f"- 状态：`{report['status']}`",
        "",
        "## 结果",
        "",
        "| Probe | Endpoint | 状态 | 行数 | 列数 | 重复抓取哈希一致 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in report["probes"]:
        lines.append(
            "| {name} | {endpoint} | {status} | {rows} | {columns} | {consistent} |".format(
                name=item["name"],
                endpoint=item["endpoint"],
                status=item["status"],
                rows=item.get("rows", "-"),
                columns=item.get("column_count", "-"),
                consistent=item.get("repeat_hash_consistent", "-"),
            )
        )
    failures = [item for item in report["probes"] if item["status"] != "success"]
    lines.extend(["", "## 失败明细", ""])
    if not failures:
        lines.append("无。")
    for item in failures:
        lines.extend(
            [
                f"### {item['name']}",
                "",
                "```json",
                json.dumps(item.get("errors", []), ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "",
            "## 判定说明",
            "",
            "本报告只证明当前版本和当前网络下的接口行为。成功不等于历史版本可复现，也不等于原始内容可公开再分发。",
        ]
    )
    return "\n".join(lines)


def run_audit(
    *,
    stock_code: str,
    output_root: Path,
    start_date: str,
    end_date: str,
    selected_probes: set[str] | None,
    repeats: int,
    retries: int,
    initial_backoff_seconds: float,
    call_timeout_seconds: float,
) -> tuple[Path, Path]:
    if len(stock_code) != 6 or not stock_code.isdigit():
        raise ValueError("stock_code must contain exactly six digits")
    if repeats not in {1, 2}:
        raise ValueError("repeats must be 1 or 2")
    import akshare as ak

    run_id = f"source-audit-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{stock_code}"
    run_root = output_root / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    raw_store = RawBatchStore(run_root)
    results: list[dict[str, Any]] = []
    probes = default_probes(stock_code, start_date, end_date)
    if selected_probes:
        probes = [probe for probe in probes if probe.name in selected_probes]
        missing = selected_probes - {probe.name for probe in probes}
        if missing:
            raise ValueError(f"unknown probes: {sorted(missing)}")

    for probe in probes:
        endpoint = getattr(ak, probe.endpoint, None)
        item: dict[str, Any] = {
            "name": probe.name,
            "endpoint": probe.endpoint,
            "parameters": probe.parameters,
            "status": "failed",
            "errors": [],
            "samples": [],
        }
        if endpoint is None:
            item["errors"].append(
                {"attempt": 0, "error_type": "MissingEndpoint", "message": "not installed"}
            )
            results.append(item)
            continue
        for repetition in range(1, repeats + 1):
            frame, errors = _call_with_retry(
                probe.endpoint,
                probe.parameters,
                retries=retries,
                initial_backoff_seconds=initial_backoff_seconds,
                call_timeout_seconds=call_timeout_seconds,
            )
            item["errors"].extend(errors)
            if frame is None:
                break
            digest = _frame_digest(frame)
            batch_id = f"{run_id}-{probe.name}-r{repetition}"
            raw_path = raw_store.write(
                f"risk_source_{probe.name}",
                batch_id,
                pa.Table.from_pandas(frame, preserve_index=False),
            )
            item["samples"].append(
                {
                    "repetition": repetition,
                    "rows": len(frame),
                    "columns": [str(value) for value in frame.columns],
                    "content_sha256": digest,
                    "raw_path": str(raw_path.relative_to(run_root)),
                }
            )
        if len(item["samples"]) == repeats:
            digests = {sample["content_sha256"] for sample in item["samples"]}
            item.update(
                {
                    "status": "success",
                    "rows": item["samples"][0]["rows"],
                    "column_count": len(item["samples"][0]["columns"]),
                    "columns": item["samples"][0]["columns"],
                    "repeat_hash_consistent": len(digests) == 1 if repeats == 2 else None,
                }
            )
        results.append(item)

    report = {
        "run_id": run_id,
        "stock_code": stock_code,
        "akshare_version": getattr(ak, "__version__", "unknown"),
        "started_with_repeats": repeats,
        "retry_policy": {
            "retries": retries,
            "initial_backoff_seconds": initial_backoff_seconds,
            "maximum_backoff_seconds": 90,
            "jitter_seconds": "0..min(2, 10% delay)",
            "call_timeout_seconds": call_timeout_seconds,
        },
        "probes": results,
        "status": "success" if all(item["status"] == "success" for item in results) else "warning",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    json_path = run_root / "report.json"
    markdown_path = run_root / "report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit candidate risk-data endpoints")
    parser.add_argument("--stock-code", default="600519")
    parser.add_argument("--output-root", default="artifacts/risk_data/source_audit")
    parser.add_argument("--start-date", default="20240101")
    parser.add_argument("--end-date", default="20260907")
    parser.add_argument("--probes", default="")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--retries", type=int, default=6)
    parser.add_argument("--initial-backoff-seconds", type=float, default=5.0)
    parser.add_argument("--call-timeout-seconds", type=float, default=45.0)
    args = parser.parse_args()
    selected = {item.strip() for item in args.probes.split(",") if item.strip()} or None
    json_path, markdown_path = run_audit(
        stock_code=args.stock_code,
        output_root=Path(args.output_root),
        start_date=args.start_date,
        end_date=args.end_date,
        selected_probes=selected,
        repeats=args.repeats,
        retries=args.retries,
        initial_backoff_seconds=args.initial_backoff_seconds,
        call_timeout_seconds=args.call_timeout_seconds,
    )
    print(json.dumps({"json": str(json_path), "markdown": str(markdown_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
