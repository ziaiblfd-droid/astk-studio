from __future__ import annotations

import csv
import json
import math
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any


FEATURES = ("splice_score", "gc", "element_length")
STRATA = ("high", "low")
GC_REGION = re.compile(r"^(A\d+_[35]SS)_(exon|intron)_")


def _command() -> list[str]:
    configured = os.getenv("ASTK_COMMAND", "astk")
    return shlex.split(configured, posix=os.name != "nt")


def _read_table(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader, [])
        rows = [row for row in reader if row and row[0]]
    return header, rows


def _event_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    if not path.exists():
        return ids
    _, rows = _read_table(path)
    for row in rows:
        ids.add(row[0])
    return ids


def _significant_ids(analysis_dir: Path, group: str, kind: str) -> set[str]:
    candidates = [
        analysis_dir / "sig01" / "dpsi" / f"{group}_{kind}.sig.dpsi",
        analysis_dir / "sig01" / f"{group}_{kind}.sig.dpsi",
    ]
    for path in candidates:
        values = _event_ids(path)
        if values:
            return values
    return set()


def _is_number(value: str) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _filter_psi(
    source_paths: list[Path],
    event_ids: set[str],
    destination: Path,
    high: bool,
    threshold: float | None = None,
) -> int:
    tables = [_read_table(path) for path in source_paths if path.exists()]
    if not tables:
        return 0
    header = tables[0][0]
    if not header:
        return 0
    rows_by_id: dict[str, list[str]] = {}
    for table_header, rows in tables:
        if table_header and table_header != header:
            # PSI headers can carry source-specific sample names. Keep the first
            # header but still combine the event rows for feature scoring.
            pass
        for row in rows:
            if len(row) > 1:
                rows_by_id.setdefault(row[0], []).extend(row[1:])
    selected: list[list[str]] = []
    for event_id in sorted(event_ids):
        values = rows_by_id.get(event_id, [])
        numeric = [float(value) for value in values if _is_number(value)]
        if not numeric or len(numeric) != len(values):
            continue
        cutoff = threshold if threshold is not None else (0.8 if high else 0.2)
        if (min(numeric) >= cutoff) if high else (max(numeric) <= cutoff):
            selected.append([event_id, *values])
    if not selected:
        return 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        combined_header = [header[0], *[value for table, _ in tables for value in table[1:]]]
        writer.writerow(combined_header)
        writer.writerows(selected)
    return len(selected)


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
    elif feature == "gc":
        command = [*astk, "gcc", "-e", str(psi_path), "-od", str(output_dir), "-ef", "150", "-if", "150", "-bs", "75", "-fi", str(fasta), "-app", "SUPPA2", "-p", process_count]
        expected = []
    else:
        command = [*astk, "getlen", "-e", str(psi_path), "-od", str(output_dir), "--scale", "log", "-app", "SUPPA2"]
        expected = [output_dir / "element_len.csv"]
    _run_astk(command, cwd, log)
    files = [path.relative_to(cwd).as_posix() for path in output_dir.rglob("*") if path.is_file()]
    if expected and not any(path.exists() for path in expected):
        raise RuntimeError(f"ASTK did not create the expected {feature} output")
    return files


def _gc_region_means(source: Path, destination: Path) -> None:
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns: dict[str, list[str]] = {}
        for name in reader.fieldnames or []:
            match = GC_REGION.match(name)
            if match:
                columns.setdefault(f"{match[1]}_{match[2]}", []).append(name)
        if not columns:
            raise ValueError(f"No splice-site GC regions in {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(["event_id", *columns])
            for row in reader:
                values = []
                for names in columns.values():
                    numeric = [float(row[name]) for name in names if _is_number(row.get(name, ""))]
                    values.append(sum(numeric) / len(numeric) if numeric else "")
                writer.writerow([row.get("event_id", ""), *values])


def _compare_features(
    job_dir: Path,
    output_root: Path,
    group: str,
    kind: str,
    high: dict[str, Any],
    low: dict[str, Any],
    log: list[str],
) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    if not high["selected_events"] or not low["selected_events"]:
        return comparisons
    for feature, filename in (("splice_score", "splice_scores.csv"), ("gc", "gcc.csv"), ("element_length", "element_len.csv")):
        destination = output_root / "comparisons" / f"{group}_{kind}"
        destination.mkdir(parents=True, exist_ok=True)
        figure = destination / f"{feature}_high_vs_low.png"
        statistics = destination / f"{feature}_high_vs_low.txt"
        item: dict[str, Any] = {
            "group": group, "kind": kind, "feature": feature,
            "high_events": high["selected_events"], "low_events": low["selected_events"],
            "status": "completed",
        }
        try:
            source_dir = output_root / feature
            sources = [source_dir / f"{group}_{kind}_{stratum}" / filename for stratum in STRATA]
            if not all(source.is_file() for source in sources):
                raise FileNotFoundError(f"Missing {feature} high/low feature table")
            if feature == "gc":
                normalized = []
                for stratum, source in zip(STRATA, sources):
                    summary = destination / f"gc_regions_{stratum}.csv"
                    _gc_region_means(source, summary)
                    normalized.append(summary)
                sources = normalized
            command = [
                *_command(), "vcmp", "-e", *(str(source) for source in sources),
                "-gn", "High", "Low", "-o", str(figure), "-ff", "png",
                "-test", "Mann-Whitney", "-mc", "BH", "-ft", "box",
            ]
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
                item["method"] = "Mean GC per splice-site exon/intron region"
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
    comparisons = plan.get("comparisons", [])
    for comparison in comparisons:
        group = str(comparison.get("group", ""))
        if not group:
            continue
        for kind in ("A3", "A5", "AF", "AL", "MX", "RI", "SE"):
            event_ids = _significant_ids(analysis_dir, group, kind)
            if not event_ids:
                continue
            strata: dict[str, dict[str, Any]] = {}
            source_paths = [
                analysis_dir / "psi" / f"{group}_{kind}_c1.psi",
                analysis_dir / "psi" / f"{group}_{kind}_c2.psi",
            ]
            for stratum, high in (("high", True), ("low", False)):
                psi_path = psi_root / f"{group}_{kind}_{stratum}.psi"
                selected = _filter_psi(
                    source_paths,
                    event_ids,
                    psi_path,
                    high,
                    high_threshold if high else low_threshold,
                )
                item: dict[str, Any] = {
                    "group": group,
                    "kind": kind,
                    "stratum": stratum,
                    "significant_events": len(event_ids),
                    "selected_events": selected,
                    "status": "skipped" if selected == 0 else "completed",
                    "outputs": {},
                }
                if selected:
                    for feature, directory in (("splice_score", "splice_score"), ("gc", "gc"), ("element_length", "element_length")):
                        try:
                            files = _run_feature(feature, psi_path, output_root / directory / f"{group}_{kind}_{stratum}", fasta, job_dir, log)
                            item["outputs"][feature] = files
                        except Exception as error:
                            item["status"] = "failed"
                            item.setdefault("errors", {})[feature] = str(error)
                            log.append(f"{feature} failed for {group}/{kind}/{stratum}: {error}")
                groups.append(item)
                strata[stratum] = item
            feature_comparisons.extend(
                _compare_features(job_dir, output_root, group, kind, strata["high"], strata["low"], log)
            )

    summary = {
        "enabled": True,
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
