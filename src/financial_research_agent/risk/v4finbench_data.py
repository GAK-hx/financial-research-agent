from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import httpx


DATASET_OWNER = "sebastiantomczak10"
DATASET_SLUG = "v4-group-corporate-bankruptcy"
DATASET_REF = f"{DATASET_OWNER}/{DATASET_SLUG}"
TARGET_FILE = "company_years_h2.parquet"
FILES_URL = f"https://www.kaggle.com/api/v1/datasets/list/{DATASET_REF}"
DOWNLOAD_URL = (
    "https://www.kaggle.com/api/v1/"
    "datasets.DatasetApiService/DownloadDataset"
)
DEFAULT_MAX_BYTES = 3 * 1024**3


def _target_metadata(client: httpx.Client) -> dict[str, Any]:
    response = client.get(FILES_URL)
    response.raise_for_status()
    payload = response.json()
    for item in payload.get("datasetFiles", []):
        if item.get("name") == TARGET_FILE:
            return item
    raise ValueError(f"{TARGET_FILE} not found in the first official file listing page")


def _is_complete_parquet(path: Path, expected_bytes: int) -> bool:
    if not path.exists() or path.stat().st_size != expected_bytes:
        return False
    with path.open("rb") as handle:
        if handle.read(4) != b"PAR1":
            return False
        handle.seek(-4, 2)
        return handle.read(4) == b"PAR1"


def _signed_download_url(client: httpx.Client) -> str:
    response = client.post(
        DOWNLOAD_URL,
        json={
            "ownerSlug": DATASET_OWNER,
            "datasetSlug": DATASET_SLUG,
            "fileName": TARGET_FILE,
        },
    )
    if response.status_code not in {301, 302, 303, 307, 308}:
        response.raise_for_status()
        raise RuntimeError("Kaggle download API did not return a signed-file redirect")
    location = response.headers.get("location", "")
    if not location:
        raise RuntimeError("Kaggle download redirect is missing Location")
    return location


def _download_attempt(
    client: httpx.Client,
    *,
    partial_path: Path,
    expected_bytes: int,
) -> None:
    offset = partial_path.stat().st_size if partial_path.exists() else 0
    if offset > expected_bytes:
        partial_path.unlink()
        offset = 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    signed_url = _signed_download_url(client)
    with client.stream("GET", signed_url, headers=headers) as response:
        response.raise_for_status()
        append = offset > 0 and response.status_code == 206
        mode = "ab" if append else "wb"
        with partial_path.open(mode) as handle:
            for chunk in response.iter_bytes(chunk_size=8 * 1024 * 1024):
                handle.write(chunk)


def prepare_v4finbench_data(
    *,
    output_root: Path,
    max_bytes: int = DEFAULT_MAX_BYTES,
    retries: int = 8,
    metadata_only: bool = False,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    target_path = output_root / TARGET_FILE
    partial_path = output_root / f"{TARGET_FILE}.partial"
    errors: list[str] = []
    timeout = httpx.Timeout(connect=60, read=180, write=60, pool=60)
    with httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        headers={"User-Agent": "financial-agent-v4finbench/1.0"},
    ) as client:
        metadata = _target_metadata(client)
        expected_bytes = int(metadata["totalBytes"])
        if expected_bytes > max_bytes:
            raise ValueError(
                f"{TARGET_FILE} is {expected_bytes} bytes, above limit {max_bytes}"
            )
        if not metadata_only and not _is_complete_parquet(target_path, expected_bytes):
            for attempt in range(1, retries + 1):
                try:
                    _download_attempt(
                        client,
                        partial_path=partial_path,
                        expected_bytes=expected_bytes,
                    )
                    if partial_path.stat().st_size != expected_bytes:
                        raise ValueError(
                            "incomplete file: "
                            f"{partial_path.stat().st_size}/{expected_bytes} bytes"
                        )
                    if not _is_complete_parquet(partial_path, expected_bytes):
                        raise ValueError("downloaded file does not have Parquet boundary markers")
                    partial_path.replace(target_path)
                    break
                except Exception as exc:  # noqa: BLE001 - preserve resumable failure history
                    errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
                    if attempt == retries:
                        raise RuntimeError("; ".join(errors)) from exc
                    time.sleep(min(60, 3 * attempt))

    ready = _is_complete_parquet(target_path, expected_bytes)
    report = {
        "status": "READY" if ready else "METADATA_READY",
        "dataset": DATASET_REF,
        "source": "Kaggle public dataset API",
        "license": "CC BY 4.0",
        "file": TARGET_FILE,
        "expected_bytes": expected_bytes,
        "actual_bytes": target_path.stat().st_size if target_path.exists() else 0,
        "max_bytes": max_bytes,
        "download_path": str(target_path),
        "partial_path": str(partial_path),
        "metadata_only": metadata_only,
        "parquet_boundary_markers_valid": ready,
        "retry_errors": errors,
    }
    (output_root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_root / "report.md").write_text(
        "\n".join(
            [
                "# V4FinBench 单文件准备",
                "",
                f"- 状态：`{report['status']}`；",
                f"- 文件：`{TARGET_FILE}`；",
                f"- 官方大小：{expected_bytes / 1024**2:.2f} MiB；",
                f"- 本地大小：{report['actual_bytes'] / 1024**2:.2f} MiB；",
                f"- Parquet 边界检查：{ready}；",
                "- 来源：Kaggle 公开数据集 API，许可 CC BY 4.0；",
                "- 下载支持断点续传，未下载其余数据文件和新闻语料。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the V4FinBench h=1 public file")
    parser.add_argument(
        "--output-root", default="/artifacts/phase5_step02/v4finbench_h1_v1"
    )
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--retries", type=int, default=8)
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()
    report = prepare_v4finbench_data(
        output_root=Path(args.output_root),
        max_bytes=args.max_bytes,
        retries=args.retries,
        metadata_only=args.metadata_only,
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
