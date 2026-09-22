from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


SECRET_TOKENS = ("password", "api_key", "secret", "credential")


def _build(root: Path, overlay: Path) -> list[dict[str, Any]]:
    result = subprocess.run(
        ["kubectl", "kustomize", str(overlay)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def _containers(resource: dict[str, Any]) -> list[dict[str, Any]]:
    kind = resource["kind"]
    if kind == "CronJob":
        return resource["spec"]["jobTemplate"]["spec"]["template"]["spec"][
            "containers"
        ]
    if kind == "Job":
        return resource["spec"]["template"]["spec"]["containers"]
    if kind == "Deployment":
        return resource["spec"]["template"]["spec"]["containers"]
    return []


def _pod_spec(resource: dict[str, Any]) -> dict[str, Any] | None:
    if resource["kind"] == "CronJob":
        return resource["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    if resource["kind"] in {"Job", "Deployment"}:
        return resource["spec"]["template"]["spec"]
    return None


def _workload_security_failures(resources: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for resource in resources:
        if resource["kind"] not in {"Deployment", "Job", "CronJob"}:
            continue
        name = resource["metadata"]["name"]
        spec = _pod_spec(resource) or {}
        pod_security = spec.get("securityContext", {})
        if name not in {"postgres", "redis"} and not pod_security.get("runAsNonRoot"):
            failures.append(f"{resource['kind']}/{name}:runAsNonRoot")
        for container in _containers(resource):
            security = container.get("securityContext", {})
            if name not in {"postgres", "redis"}:
                if not security.get("readOnlyRootFilesystem"):
                    failures.append(f"{resource['kind']}/{name}:readOnlyRootFilesystem")
                if security.get("allowPrivilegeEscalation") is not False:
                    failures.append(f"{resource['kind']}/{name}:allowPrivilegeEscalation")
                if "ALL" not in security.get("capabilities", {}).get("drop", []):
                    failures.append(f"{resource['kind']}/{name}:capabilities")
            resources_block = container.get("resources", {})
            if not resources_block.get("requests") or not resources_block.get("limits"):
                failures.append(f"{resource['kind']}/{name}:resources")
    return failures


def _config_secret_leaks(resources: list[dict[str, Any]]) -> list[str]:
    leaks: list[str] = []
    for resource in resources:
        if resource["kind"] != "ConfigMap":
            continue
        for key, value in resource.get("data", {}).items():
            lowered = key.lower()
            sensitive = any(token in lowered for token in SECRET_TOKENS) or lowered in {
                "token",
                "access_token",
                "refresh_token",
            }
            if sensitive and str(value).strip():
                leaks.append(f"{resource['metadata']['name']}:{key}")
    return leaks


def _lake_claims(resources: list[dict[str, Any]]) -> dict[str, str | None]:
    claims: dict[str, str | None] = {}
    for resource in resources:
        if resource["kind"] not in {"Deployment", "CronJob"}:
            continue
        name = resource["metadata"]["name"]
        if name not in {"job-api", "job-worker", "lake-bootstrap"}:
            continue
        pod_spec = _pod_spec(resource) or {}
        lake = next(
            (volume for volume in pod_spec.get("volumes", []) if volume["name"] == "lake"),
            {},
        )
        claims[name] = lake.get("persistentVolumeClaim", {}).get("claimName")
    return claims


def _hpa_bounds(resources: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    return {
        resource["metadata"]["name"]: (
            resource["spec"]["minReplicas"],
            resource["spec"]["maxReplicas"],
        )
        for resource in resources
        if resource["kind"] == "HorizontalPodAutoscaler"
    }


def run_validation(root: Path, output_root: Path) -> dict[str, Any]:
    base = _build(root, root / "deploy/k8s/base")
    kind = _build(root, root / "deploy/k8s/kind")
    counts = Counter(item["kind"] for item in kind)
    names = {(item["kind"], item["metadata"]["name"]) for item in kind}
    security_failures = _workload_security_failures(kind)
    config_leaks = _config_secret_leaks(kind)
    lake_claims = _lake_claims(kind)
    hpa_bounds = _hpa_bounds(kind)
    cluster = yaml.safe_load(
        (root / "deploy/k8s/kind/cluster.yaml").read_text(encoding="utf-8")
    )
    deployment_names = {
        name for resource_kind, name in names if resource_kind == "Deployment"
    }
    probe_failures: list[str] = []
    for resource in kind:
        if resource["kind"] != "Deployment" or resource["metadata"]["name"] not in {
            "job-api",
            "backend-gateway",
        }:
            continue
        container = _containers(resource)[0]
        if not container.get("readinessProbe") or not container.get("livenessProbe"):
            probe_failures.append(resource["metadata"]["name"])
    checks = {
        "kustomize_base_and_kind_render": bool(base) and bool(kind),
        "three_logical_kind_nodes": len(cluster.get("nodes", [])) == 3,
        "required_runtime_deployments": {
            "job-api",
            "job-worker",
            "backend-gateway",
            "postgres",
            "redis",
        }.issubset(deployment_names),
        "job_and_cronjob_present": ("Job", "db-migrate") in names
        and ("CronJob", "lake-bootstrap") in names,
        "hpa_pdb_networkpolicy_present": counts["HorizontalPodAutoscaler"] >= 2
        and counts["PodDisruptionBudget"] >= 2
        and counts["NetworkPolicy"] >= 4,
        "business_workload_security_contexts_complete": not security_failures,
        "api_worker_bootstrap_share_lake_pvc": lake_claims
        == {
            "job-api": "agent-lake",
            "job-worker": "agent-lake",
            "lake-bootstrap": "agent-lake",
        },
        "kind_hpa_uses_local_bounds": hpa_bounds
        == {"job-api": (1, 2), "backend-gateway": (1, 2)},
        "api_gateway_probes_complete": not probe_failures,
        "configmap_contains_no_secret_values": not config_leaks,
        "secret_not_rendered_from_repository": counts["Secret"] == 0,
    }
    report = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "validation": "k8s_manifest",
        "scope": "static_render_and_policy_validation",
        "cluster_runtime_claimed": False,
        "resource_counts": dict(sorted(counts.items())),
        "security_failures": security_failures,
        "probe_failures": probe_failures,
        "config_secret_leaks": config_leaks,
        "lake_claims": lake_claims,
        "hpa_bounds": hpa_bounds,
        "checks": checks,
        "runtime_report": (
            "artifacts/runtime_validation/k8s_runtime_v1/report.json"
        ),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest-validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Kubernetes Manifest验证",
        "",
        f"- 状态：`{report['status']}`；",
        "- 范围：Kustomize渲染、资源完整性、探针、资源限制、安全上下文和Secret边界；",
        "- 运行声明：本文件仅验证静态清单；集群实测结果由独立运行验证覆盖；",
        "",
        "## 资源",
        "",
        *[f"- `{name}`：{count}" for name, count in sorted(counts.items())],
        "",
        "## 检查",
        "",
        *[
            f"- [{'x' if passed else ' '}] `{name}`"
            for name, passed in checks.items()
        ],
        "",
        "## 运行报告",
        "",
        report["runtime_report"],
        "",
    ]
    (output_root / "manifest-validation.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Kubernetes manifests and policies")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    report = run_validation(args.root.resolve(), args.output_root.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
