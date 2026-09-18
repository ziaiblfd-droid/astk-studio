from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from .planner import native_comparison_label


EVENT_TYPES = ("A3", "A5", "AF", "AL", "MX", "RI", "SE")
EVENT_PATTERN = re.compile(r";(A3|A5|AF|AL|MX|RI|SE):")
IMAGE_CATEGORIES = ("bar", "PCA", "heatmap", "volcano", "upset")


def event_type(event_id: str, fallback: str = "") -> str:
    match = EVENT_PATTERN.search(event_id)
    if match:
        return match.group(1)
    for value in EVENT_TYPES:
        if re.search(rf"(?:^|_){value}(?:_|\.|$)", fallback):
            return value
    return "UNKNOWN"


def load_gene_names(gtf_path: Path | None) -> dict[str, str]:
    if gtf_path is None or not gtf_path.exists():
        return {}
    mapping: dict[str, str] = {}
    gene_id_pattern = re.compile(r'gene_id "([^"]+)"')
    gene_name_pattern = re.compile(r'gene_name "([^"]+)"')
    with gtf_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("#") or "gene_id" not in line or "gene_name" not in line:
                continue
            gene_id_match = gene_id_pattern.search(line)
            gene_name_match = gene_name_pattern.search(line)
            if gene_id_match and gene_name_match:
                mapping.setdefault(gene_id_match.group(1), gene_name_match.group(1))
    return mapping


def read_event_ids(path: Path) -> set[str]:
    values: set[str] = set()
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.reader(handle, delimiter="\t")
        next(reader, None)
        for row in reader:
            if row and row[0]:
                values.add(row[0])
    return values


def parse_significant(path: Path, gene_names: dict[str, str]) -> list[list[str]]:
    rows: list[list[str]] = []
    fallback_type = event_type("", path.name)
    comparison = path.name
    comparison = re.sub(r"\.sig(?:[+-])?\.dpsi$", "", comparison)
    comparison = re.sub(rf"_{fallback_type}$", "", comparison) if fallback_type != "UNKNOWN" else comparison
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.reader(handle, delimiter="\t")
        next(reader, None)
        for row in reader:
            if len(row) < 3:
                continue
            event_id = row[0]
            kind = event_type(event_id, path.name)
            gene_id = event_id.split(";", 1)[0]
            try:
                dpsi = float(row[1])
                p_value = float(row[2])
            except ValueError:
                continue
            rows.append(
                [
                    event_id,
                    gene_names.get(gene_id, gene_id),
                    kind,
                    comparison,
                    "—",
                    f"{dpsi:+.4f}",
                    f"{p_value:.4g}",
                ]
            )
    return rows


def count_samples(metadata_path: Path) -> int:
    if not metadata_path.exists():
        return 0
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    names = {
        sample["name"]
        for comparison in payload.values()
        for condition in comparison.values()
        for sample in condition.get("samples", [])
    }
    return len(names)


def collect_images(job_dir: Path) -> dict[str, list[dict[str, str]]]:
    analysis_dir = job_dir / "output" / "analysis"
    images: dict[str, list[dict[str, str]]] = {}
    for category in IMAGE_CATEGORIES:
        directory = analysis_dir / "img" / category
        if not directory.exists():
            continue
        items = []
        for path in sorted(directory.glob("*.png")):
            items.append(
                {
                    "name": path.stem,
                    "path": path.relative_to(job_dir).as_posix(),
                }
            )
        if items:
            images[category.lower()] = items
    return images


def load_plan(job_dir: Path) -> dict[str, Any]:
    path = job_dir / "plan.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_comparisons(job_dir: Path, plan: dict[str, Any]) -> list[dict[str, str]]:
    comparisons = [
        dict(item)
        for item in plan.get("comparisons", [])
        if item.get("group")
    ]
    metadata_path = job_dir / "metadata" / "astk_metadata.json"
    metadata: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            metadata = {}
    if not comparisons and metadata:
        comparisons = [{"group": group} for group in metadata]
    for item in comparisons:
        roles = metadata.get(item["group"])
        if roles and "_vs_" not in item["group"]:
            control, treatment, label = native_comparison_label(item["group"], roles)
            item.update({"control": control, "treatment": treatment, "label": label})
    return comparisons


def parse_results(job_dir: Path, gtf_path: Path | None = None, preview_limit: int = 5000) -> dict[str, Any]:
    analysis_dir = job_dir / "output" / "analysis"
    plan = load_plan(job_dir)
    comparisons = load_comparisons(job_dir, plan)
    comparison_labels = {
        item["group"]: item.get("label") or f'{item["control"]} → {item["treatment"]}'
        for item in comparisons
        if item.get("group") and (item.get("label") or all(item.get(key) for key in ("control", "treatment")))
    }
    gene_names = load_gene_names(gtf_path)
    events_by_type: dict[str, set[str]] = defaultdict(set)
    for path in (analysis_dir / "psi").glob("*.psi"):
        for event_id in read_event_ids(path):
            events_by_type[event_type(event_id, path.name)].add(event_id)
    significant_rows: list[list[str]] = []
    seen_significant: set[tuple[str, str]] = set()
    significant_dir = analysis_dir / "sig01" / "dpsi"
    if not significant_dir.exists():
        significant_dir = analysis_dir / "sig01"
    for path in sorted(significant_dir.glob("*.sig.dpsi")):
        for row in parse_significant(path, gene_names):
            row[3] = comparison_labels.get(row[3], row[3].replace("_vs_", " → "))
            key = (row[0], row[3])
            if key not in seen_significant:
                seen_significant.add(key)
                significant_rows.append(row)
    dpsi_values = [abs(float(row[5])) for row in significant_rows]
    event_counts = {kind: len(events_by_type.get(kind, set())) for kind in EVENT_TYPES}
    significant_event_counts = {
        kind: len({row[0] for row in significant_rows if row[2] == kind})
        for kind in EVENT_TYPES
    }
    if not any(event_counts.values()):
        for path in (analysis_dir / "ref").glob("*_strict.ioe"):
            for event_id in read_event_ids(path):
                events_by_type[event_type(event_id, path.name)].add(event_id)
        event_counts = {kind: len(events_by_type.get(kind, set())) for kind in EVENT_TYPES}
    results = {
        "metrics": {
            "total_events": sum(event_counts.values()),
            "significant_events": len(significant_rows),
            "sample_count": count_samples(job_dir / "metadata" / "astk_metadata.json"),
            "median_abs_dpsi": round(statistics.median(dpsi_values), 4) if dpsi_values else 0,
        },
        "event_counts": event_counts,
        "significant_event_counts": significant_event_counts,
        "direction_counts": {
            "up": sum(float(row[5]) > 0 for row in significant_rows),
            "down": sum(float(row[5]) < 0 for row in significant_rows),
        },
        "events": significant_rows[:preview_limit],
        "events_truncated": len(significant_rows) > preview_limit,
        "images": collect_images(job_dir),
        "comparisons": comparisons,
        "reference": plan.get("reference", {}),
        "engine": plan.get("engine", "suppa2"),
        "mode": "suppa2",
    }
    output = job_dir / "output" / "results.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse SUPPA2 output for ASTK Studio")
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--gtf", type=Path)
    args = parser.parse_args()
    print(json.dumps(parse_results(args.job_dir.resolve(), args.gtf), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
