from __future__ import annotations

import csv
import json
import math
import os
import shlex
import subprocess
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
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


def _render_feature(feature: str, table: Path, figure: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    data = pd.read_csv(table, index_col=0)
    if data.empty:
        raise ValueError(f"Empty cached feature table: {table}")
    if feature == "splice_score":
        ax = data.plot.box()
        ax.get_figure().savefig(figure)
        plt.close(ax.get_figure())
    elif feature in {"gc", "gc_comparison"}:
        sites: dict[str, list[str]] = defaultdict(list)
        for column in data.columns:
            sites["_".join(column.split("_", 2)[:2])].append(column)
        fig, axes = plt.subplots(1, len(sites), figsize=(10, 5))
        for ax, columns in zip(axes if len(sites) > 1 else [axes], sites.values()):
            means = data[columns].mean(axis=0)
            up_width = len(columns) // 2
            ax.plot(range(-up_width, len(columns) - up_width), means)
            ax.set_ylim([min(0.35, means.min()), max(0.65, means.max())])
        fig.tight_layout()
        fig.savefig(figure)
        plt.close(fig)
    else:
        fig, axes = plt.subplots(1, data.shape[1], sharey=True)
        for ax, column in zip(axes if data.shape[1] > 1 else [axes], data.columns):
            ax.boxplot(data[column].dropna())
            ax.set_ylabel("log2(length)")
        fig.tight_layout()
        fig.savefig(figure)
        plt.close(fig)


def _split_cached_feature(
    feature: str,
    catalog: Path,
    output_root: Path,
    job_dir: Path,
    members: list[dict[str, Any]],
) -> None:
    filenames = {
        "splice_score": ("splice_scores.csv", "splice_scores_box.png"),
        "gc": ("gcc.csv", "gcc.png"),
        "gc_comparison": ("gcc.csv", "gcc.png"),
        "element_length": ("element_len.csv", "element_len.png"),
    }
    name, figure_name = filenames[feature]
    with ExitStack() as stack, (catalog / name).open("r", encoding="utf-8", newline="") as source:
        reader = csv.reader(source)
        header = next(reader)
        writers: list[tuple[set[str], Any, dict[str, Any], Path]] = []
        for item in members:
            destination = output_root / feature / f"{filename_token(item['group'])}_{item['kind']}_{item['stratum']}"
            destination.mkdir(parents=True, exist_ok=True)
            handle = stack.enter_context((destination / name).open("w", encoding="utf-8", newline=""))
            writer = csv.writer(handle)
            writer.writerow(header)
            with (output_root / "psi" / f"{filename_token(item['group'])}_{item['kind']}_{item['stratum']}.psi").open(
                "r", encoding="utf-8", newline=""
            ) as psi_handle:
                ids = {row[0] for row in list(csv.reader(psi_handle, delimiter="\t"))[1:]}
            writers.append((ids, writer, item, destination))
        counts = [0] * len(writers)
        for row in reader:
            if not row:
                continue
            for index, (ids, writer, _, _) in enumerate(writers):
                if row[0] in ids:
                    writer.writerow(row)
                    counts[index] += 1
    for count, (_, _, item, destination) in zip(counts, writers):
        if count != item["selected_events"]:
            raise ValueError(f"Cached {feature} row count mismatch for {item['group']}/{item['kind']}/{item['stratum']}")
        _render_feature(feature, destination / name, destination / figure_name)
        item["outputs"][feature] = [
            (destination / filename).relative_to(job_dir).as_posix() for filename in (name, figure_name)
        ]


def _progress(job_dir: Path, stage: str, progress: int) -> None:
    if not (job_dir / "job.json").is_file():
        return
    from .store import JobStore
    JobStore(job_dir.parent).update(job_dir.name, stage=stage, progress=progress)


def _timed_feature(feature: str, psi: Path, destination: Path, fasta: Path, job_dir: Path) -> tuple[list[str], float]:
    started = time.monotonic()
    lines: list[str] = []
    _run_feature(feature, psi, destination, fasta, job_dir, lines)
    return lines, time.monotonic() - started


def _timed_comparison(
    job_dir: Path, output_root: Path, group: str, kind: str,
    high: dict[str, Any], low: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str], float]:
    started = time.monotonic()
    lines: list[str] = []
    comparisons = _compare_features(job_dir, output_root, group, kind, high, low, lines)
    return comparisons, lines, time.monotonic() - started


def _merge_splice_shards(catalog_psi: Path, shard_dirs: list[Path], destination: Path) -> None:
    _, source_rows = _read_table(catalog_psi)
    expected_ids = [row[0] for row in source_rows]
    values: dict[str, list[str]] = {}
    header: list[str] | None = None
    for shard in shard_dirs:
        with (shard / "splice_scores.csv").open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            columns = next(reader)
            if header is not None and columns != header:
                raise ValueError("Splice-score shard columns do not match")
            header = columns
            for row in reader:
                if not row or len(row) != len(columns) or row[0] in values:
                    raise ValueError("Invalid or duplicate splice-score shard row")
                values[row[0]] = row
    if len(values) != len(expected_ids) or set(values) != set(expected_ids):
        raise ValueError("Splice-score shards did not cover the catalog event IDs")
    destination.mkdir(parents=True, exist_ok=True)
    table = destination / "splice_scores.csv"
    with table.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(values[event_id] for event_id in expected_ids)
    _render_feature("splice_score", table, destination / "splice_scores_box.png")


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

    started = time.monotonic()
    log: list[str] = ["=== SEQUENCE FEATURES ===", f"FASTA: {fasta}"]
    high_threshold = float(plan.get("psi_high_threshold", 0.8))
    low_threshold = float(plan.get("psi_low_threshold", 0.2))
    groups: list[dict[str, Any]] = []
    feature_comparisons: list[dict[str, Any]] = []
    timings: dict[str, Any] = {"extraction_seconds": {}, "comparison_seconds": {}}
    workers = max(1, min(8, int(os.getenv("ASTK_SEQUENCE_WORKERS", "8"))))
    splice_shards = max(1, min(workers, int(os.getenv("ASTK_SPLICE_SHARDS", "8"))))
    features = ("splice_score", "gc", "gc_comparison", "element_length")
    conditions = _condition_sources(analysis_dir, plan.get("comparisons", []))
    members_by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    catalog_rows: dict[str, dict[str, list[str]]] = defaultdict(dict)
    _progress(job_dir, "Sequence features: selecting events", 72)
    for group, sources in conditions.items():
        stage_key = filename_token(group)
        for kind, source in sources.items():
            header, source_rows = _read_table(source)
            selected_rows: dict[str, list[list[str]]] = {"high": [], "low": []}
            for row in source_rows:
                if len(row) != len(header) or not all(_is_number(value) for value in row[1:]):
                    continue
                mean_psi = sum(float(value) for value in row[1:]) / (len(row) - 1)
                if mean_psi >= high_threshold:
                    selected_rows["high"].append(row)
                if mean_psi <= low_threshold:
                    selected_rows["low"].append(row)
            for stratum in STRATA:
                psi_path = psi_root / f"{stage_key}_{kind}_{stratum}.psi"
                rows = selected_rows[stratum]
                selected = len(rows)
                if selected:
                    psi_root.mkdir(parents=True, exist_ok=True)
                    with psi_path.open("w", encoding="utf-8", newline="") as handle:
                        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
                        writer.writerow(header)
                        writer.writerows(rows)
                item: dict[str, Any] = {
                    "group": group,
                    "kind": kind,
                    "stratum": stratum,
                    "selected_events": selected,
                    "status": "skipped" if selected == 0 else "completed",
                    "outputs": {},
                }
                if selected:
                    members_by_kind[kind].append(item)
                    for row in rows:
                        catalog_rows[kind].setdefault(row[0], row)
                groups.append(item)

    def write_log(lines: list[str]) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    write_log(log)
    tasks: list[tuple[str, str, int | None]] = []
    with tempfile.TemporaryDirectory(prefix=".sequence-cache-", dir=job_dir) as temporary:
        cache_root = Path(temporary)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {}
            for kind, rows in catalog_rows.items():
                catalog = cache_root / kind
                catalog.mkdir()
                psi = catalog / f"{kind}.psi"
                with psi.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
                    writer.writerow(["event_id", "sample"])
                    writer.writerows([row[0], row[1]] for row in rows.values())
                for feature in features:
                    count = min(splice_shards, len(rows)) if feature == "splice_score" and kind in {"AF", "SE"} else 1
                    if count > 1:
                        shard_rows: list[list[list[str]]] = [[] for _ in range(count)]
                        for index, row in enumerate(rows.values()):
                            shard_rows[index % count].append([row[0], row[1]])
                        for index, part in enumerate(shard_rows):
                            shard_psi = catalog / f"splice-shard-{index}.psi"
                            with shard_psi.open("w", encoding="utf-8", newline="") as handle:
                                writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
                                writer.writerow(["event_id", "sample"])
                                writer.writerows(part)
                            destination = catalog / "splice_shards" / f"part-{index}"
                            tasks.append((kind, feature, index))
                            pending[pool.submit(_timed_feature, feature, shard_psi, destination, fasta, job_dir)] = (kind, feature, index)
                    else:
                        tasks.append((kind, feature, None))
                        destination = catalog / feature
                        pending[pool.submit(_timed_feature, feature, psi, destination, fasta, job_dir)] = (kind, feature, None)
            failed: set[tuple[str, str]] = set()
            for done, future in enumerate(as_completed(pending), 1):
                kind, feature, shard = pending[future]
                label = f"{kind}/{feature}" + (f"/shard-{shard}" if shard is not None else "")
                try:
                    lines, seconds = future.result()
                    timings["extraction_seconds"][label] = round(seconds, 3)
                    write_log([*lines, f"TIMING extraction {label}: {seconds:.3f}s"])
                except Exception as error:
                    failed.add((kind, feature))
                    write_log([f"Extraction failed for {label}: {error}"])
                _progress(job_dir, f"Sequence features: extracting {done}/{len(tasks)}", 72 + int(13 * done / len(tasks)))

        for kind_index, (kind, members) in enumerate(members_by_kind.items(), 1):
            for feature in features:
                if (kind, feature) in failed:
                    error = f"Shared {feature} extraction failed for {kind}"
                else:
                    try:
                        shard_dirs = sorted((cache_root / kind / "splice_shards").glob("part-*"))
                        if feature == "splice_score" and shard_dirs:
                            _merge_splice_shards(
                                cache_root / kind / f"{kind}.psi", shard_dirs,
                                cache_root / kind / feature,
                            )
                        _split_cached_feature(feature, cache_root / kind / feature, output_root, job_dir, members)
                        continue
                    except Exception as exc:
                        error = str(exc)
                for item in members:
                    item["status"] = "failed"
                    item.setdefault("errors", {})[feature] = error
                write_log([f"Cached feature failed for {kind}/{feature}: {error}"])
            _progress(job_dir, f"Sequence features: figures {kind}", 85 + int(5 * kind_index / len(members_by_kind)))

    by_group_kind: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for item in groups:
        by_group_kind[(item["group"], item["kind"])][item["stratum"]] = item
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {
            pool.submit(_timed_comparison, job_dir, output_root, group, kind, strata["high"], strata["low"]): (group, kind)
            for (group, kind), strata in by_group_kind.items()
        }
        for index, future in enumerate(as_completed(pending), 1):
            group, kind = pending[future]
            try:
                results, lines, seconds = future.result()
                feature_comparisons.extend(results)
                timings["comparison_seconds"][f"{group}/{kind}"] = round(seconds, 3)
                write_log([*lines, f"TIMING comparison {group}/{kind}: {seconds:.3f}s"])
            except Exception as error:
                write_log([f"Comparison failed for {group}/{kind}: {error}"])
            _progress(job_dir, f"Sequence features: comparisons {index}/{len(pending)}", 90 + int(5 * index / len(pending)))
    feature_comparisons.sort(key=lambda item: (item["group"], EVENT_TYPES.index(item["kind"]), item["feature"]))

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
        "execution": {
            "parallel_limit": workers,
            "splice_shards": splice_shards,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            **timings,
        },
    }
    (output_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_log([f"TIMING sequence features total: {summary['execution']['elapsed_seconds']}s"])
    return summary
