from __future__ import annotations

import csv
import json
import math
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .planner import filename_token

STRATA = ("high", "low")
EVENT_TYPES = ("A3", "A5", "AF", "AL", "MX", "RI", "SE")


def _command() -> list[str]:
    configured = os.getenv("ASTK_COMMAND", "astk")
    return shlex.split(configured, posix=os.name != "nt")


def _read_table(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader, [])
        rows = [row for row in reader if row and row[0]]
    return header, rows


def _is_number(value: str) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _filter_psi(
    source: Path,
    destination: Path,
    high: bool,
    threshold: float,
) -> int:
    if not source.is_file():
        return 0
    header, rows = _read_table(source)
    if len(header) < 2:
        return 0
    selected: list[list[str]] = []
    for row in rows:
        if len(row) != len(header) or not all(_is_number(value) for value in row[1:]):
            continue
        mean_psi = sum(float(value) for value in row[1:]) / (len(row) - 1)
        if (mean_psi >= threshold) if high else (mean_psi <= threshold):
            selected.append(row)
    if not selected:
        return 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(selected)
    return len(selected)


def _condition_sources(analysis_dir: Path, comparisons: list[dict[str, Any]]) -> dict[str, dict[str, Path]]:
    conditions: dict[str, dict[str, Path]] = {}
    for comparison in comparisons:
        comparison_group = str(comparison.get("group", ""))
        if not comparison_group:
            continue
        for role, label in (("c1", comparison.get("control")), ("c2", comparison.get("treatment"))):
            condition = str(label or "").strip()
            if not condition:
                continue
            for kind in EVENT_TYPES:
                source = analysis_dir / "psi" / f"{comparison_group}_{kind}_{role}.psi"
                if not source.is_file():
                    continue
                existing = conditions.setdefault(condition, {}).get(kind)
                if existing:
                    with existing.open("r", encoding="utf-8-sig") as first, source.open("r", encoding="utf-8-sig") as second:
                        if first.readline() != second.readline():
                            raise ValueError(f"Condition {condition} has inconsistent PSI samples across comparisons")
                else:
                    conditions[condition][kind] = source
    return conditions


def _run_astk(command: list[str], cwd: Path, log: list[str]) -> None:
    log.append("$ " + shlex.join(command))
    process = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=int(os.getenv("ASTK_FEATURE_TIMEOUT", "7200")),
        check=False,
    )
    output = "\n".join(part.strip() for part in (process.stdout, process.stderr) if part and part.strip())
    if output:
        log.append(output)
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise RuntimeError(f"ASTK sequence feature command failed with code {process.returncode}{suffix}")


def _run_feature(
    feature: str,
    psi_path: Path,
    output_dir: Path,
    fasta: Path,
    cwd: Path,
    log: list[str],
) -> list[str]:
    astk = _command()
    output_dir.mkdir(parents=True, exist_ok=True)
    process_count = str(max(1, min(4, int(os.getenv("ASTK_FEATURE_PROCESSES", "2")))))
    if feature == "splice_score":
        command = [*astk, "spliceScore", "-e", str(psi_path), "-od", str(output_dir), "-fi", str(fasta), "-app", "SUPPA2", "-p", process_count]
        expected = [output_dir / "splice_scores.csv"]
    elif feature in {"gc", "gc_comparison"}:
        bin_size = "75" if feature == "gc" else "150"
        command = [*astk, "gcc", "-e", str(psi_path), "-od", str(output_dir), "-ef", "150", "-if", "150", "-bs", bin_size, "-fi", str(fasta), "-app", "SUPPA2", "-p", process_count]
        expected = [output_dir / "gcc.csv"]
    else:
        command = [*astk, "getlen", "-e", str(psi_path), "-od", str(output_dir), "--scale", "log", "-app", "SUPPA2"]
        expected = [output_dir / "element_len.csv"]
    _run_astk(command, cwd, log)
    files = [path.relative_to(cwd).as_posix() for path in output_dir.rglob("*") if path.is_file()]
    if expected and not any(path.exists() for path in expected):
        raise RuntimeError(f"ASTK did not create the expected {feature} output")
    return files


def _compare_features(
    job_dir: Path,
    output_root: Path,
    group: str,
    kind: str,
    high: dict[str, Any],
    low: dict[str, Any],
    log: list[str],
    stage_key: str | None = None,
) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    if not high["selected_events"] or not low["selected_events"]:
        return comparisons
    key = stage_key or filename_token(group)
    for feature, filename in (("splice_score", "splice_scores.csv"), ("gc", "gcc.csv"), ("element_length", "element_len.csv")):
        destination = output_root / "comparisons" / f"{key}_{kind}"
        destination.mkdir(parents=True, exist_ok=True)
        figure = destination / f"{feature}_high_vs_low.png"
        statistics = destination / f"{feature}_high_vs_low.txt"
        item: dict[str, Any] = {
            "group": group, "kind": kind, "feature": feature,
            "high_events": high["selected_events"], "low_events": low["selected_events"],
            "status": "completed",
        }
        try:
            source_dir = output_root / ("gc_comparison" if feature == "gc" else feature)
            sources = [source_dir / f"{key}_{kind}_{stratum}" / filename for stratum in STRATA]
            if not all(source.is_file() for source in sources):
                raise FileNotFoundError(f"Missing {feature} high/low feature table")
            command = [
                *_command(), "vcmp", "-e", *(str(source) for source in sources),
                "-gn", "High", "Low", "-o", str(figure), "-ff", "png",
                "-test", "Mann-Whitney", "-ft", "box",
            ]
            if feature == "gc":
                command.extend(["--facet", "--xtitle", "splice_site", "--ytitle", "GCC"])
            elif feature == "splice_score":
                command.extend(["--xtitle", "splice_site", "--ytitle", "score"])
            else:
                command.extend(["--xtitle", "element", "--ytitle", "log2(length)"])
            log.append("$ " + shlex.join(command))
            process = subprocess.run(
                command, cwd=job_dir, capture_output=True, text=True,
                timeout=int(os.getenv("ASTK_FEATURE_TIMEOUT", "7200")), check=False,
            )
            statistics.write_text(
                "\n".join(part for part in (process.stdout, process.stderr) if part),
                encoding="utf-8",
            )
            if process.returncode or not figure.is_file():
                raise RuntimeError(f"ASTK vcmp exited with code {process.returncode}; see {statistics.name}")
            item["image"] = figure.relative_to(job_dir).as_posix()
            item["statistics"] = statistics.relative_to(job_dir).as_posix()
            if feature == "gc":
                item["method"] = "150 bp GC windows, faceted by splice site"
        except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError) as error:
            item["status"] = "failed"
            item["error"] = str(error)
            log.append(f"{group}/{kind}/{feature} comparison failed: {error}")
        comparisons.append(item)
    return comparisons


def run_sequence_features(job_dir: Path, plan: dict[str, Any], log_path: Path) -> dict[str, Any]:
    output_root = job_dir / "output" / "sequence_features"
    psi_root = output_root / "psi"
    if output_root.exists():
        for path in output_root.rglob("*"):
            if path.is_file():
                path.unlink()
    output_root.mkdir(parents=True, exist_ok=True)
    analysis_dir = job_dir / "output" / "analysis"
    fasta = Path(str(plan.get("reference", {}).get("fasta", "")))
    if not fasta.exists():
        raise RuntimeError(f"Sequence feature FASTA does not exist: {fasta}")

    log: list[str] = ["=== SEQUENCE FEATURES ===", f"FASTA: {fasta}"]
    high_threshold = float(plan.get("psi_high_threshold", 0.8))
    low_threshold = float(plan.get("psi_low_threshold", 0.2))
    groups: list[dict[str, Any]] = []
    feature_comparisons: list[dict[str, Any]] = []
    conditions = _condition_sources(analysis_dir, plan.get("comparisons", []))
    for group, sources in conditions.items():
        stage_key = filename_token(group)
        for kind, source in sources.items():
            strata: dict[str, dict[str, Any]] = {}
            for stratum, high in (("high", True), ("low", False)):
                psi_path = psi_root / f"{stage_key}_{kind}_{stratum}.psi"
                selected = _filter_psi(
                    source,
                    psi_path,
                    high,
                    high_threshold if high else low_threshold,
                )
                item: dict[str, Any] = {
                    "group": group,
                    "kind": kind,
                    "stratum": stratum,
                    "selected_events": selected,
                    "status": "skipped" if selected == 0 else "completed",
                    "outputs": {},
                }
                if selected:
                    for feature in ("splice_score", "gc", "gc_comparison", "element_length"):
                        try:
                            files = _run_feature(feature, psi_path, output_root / feature / f"{stage_key}_{kind}_{stratum}", fasta, job_dir, log)
                            item["outputs"][feature] = files
                        except Exception as error:
                            item["status"] = "failed"
                            item.setdefault("errors", {})[feature] = str(error)
                            log.append(f"{feature} failed for {group}/{kind}/{stratum}: {error}")
                groups.append(item)
                strata[stratum] = item
            feature_comparisons.extend(
                _compare_features(job_dir, output_root, group, kind, strata["high"], strata["low"], log, stage_key)
            )

    summary = {
        "enabled": True,
        "selection_mode": "condition_mean_all_events",
        "fasta": str(fasta),
        "high_threshold": high_threshold,
        "low_threshold": low_threshold,
        "groups": groups,
        "comparisons": feature_comparisons,
        "completed": sum(item["status"] == "completed" for item in groups),
        "selected_events": sum(int(item["selected_events"]) for item in groups),
        "failed": sum(item["status"] == "failed" for item in groups)
        + sum(item["status"] == "failed" for item in feature_comparisons),
    }
    (output_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + "\n".join(log) + "\n")
    return summary
