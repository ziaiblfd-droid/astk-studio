from __future__ import annotations

import csv
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .planner import native_comparison_label


EVENT_TYPES = ("A3", "A5", "AF", "AL", "MX", "RI", "SE")
HEATMAP_TOP_EVENTS = 60


def run_plot(command: list[str], log: list[str]) -> None:
    astk_command = os.getenv("ASTK_COMMAND", "astk")
    if command and command[0] == "astk":
        command = [astk_command, *command[1:]]
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    log.append(f"$ {' '.join(command)}")
    if process.stdout.strip():
        log.append(process.stdout.strip())
    if process.stderr.strip():
        log.append(process.stderr.strip())
    if process.returncode != 0:
        log.append(f"[warning] plot command exited with code {process.returncode}")


def plan_threshold(plan: dict[str, Any], key: str, default: float) -> float:
    if plan.get(key) is not None:
        return float(plan[key])
    command = [str(item) for item in plan.get("command", [])]
    flag = "-p" if key == "p_value" else "-adpsi"
    try:
        return float(command[command.index(flag) + 1])
    except (ValueError, IndexError):
        return default


def filter_significant_dpsi(
    source: Path,
    destination: Path,
    p_value: float,
    abs_dpsi: float,
) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader, None)
        filtered: list[list[str]] = []
        for row in reader:
            if len(row) < 3:
                continue
            try:
                dpsi = float(row[1])
                pval = float(row[2])
            except ValueError:
                continue
            if pval < p_value and abs(dpsi) > abs_dpsi:
                filtered.append(row)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        if header:
            writer.writerow(header)
        writer.writerows(filtered)
    return len(filtered)


def read_table(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader, [])
        rows = [row for row in reader if row and row[0]]
    return header, rows


def write_table(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        if header:
            writer.writerow(header)
        writer.writerows(rows)


def dpsi_rank(analysis: Path, comparisons: list[dict[str, str]], kind: str) -> dict[str, float]:
    rank: dict[str, float] = {}
    for comparison in comparisons:
        path = analysis / "dpsi" / f"{comparison['group']}_{kind}.dpsi"
        if not path.exists():
            continue
        _, rows = read_table(path)
        for row in rows:
            if len(row) < 2:
                continue
            try:
                value = abs(float(row[1]))
            except ValueError:
                continue
            rank[row[0]] = max(rank.get(row[0], 0.0), value)
    return rank


def prepare_heatmap_inputs(
    analysis: Path,
    comparisons: list[dict[str, str]],
    kind: str,
) -> list[Path]:
    if not comparisons:
        return []
    psi_files = [analysis / "psi" / f"{comparisons[0]['group']}_{kind}_c1.psi"]
    psi_files.extend(
        analysis / "psi" / f"{comparison['group']}_{kind}_c2.psi"
        for comparison in comparisons
    )
    psi_files = list(dict.fromkeys(path for path in psi_files if path.exists()))
    if len(psi_files) < 2:
        return []

    tables = [read_table(path) for path in psi_files]
    common = set(row[0] for row in tables[0][1])
    for _, rows in tables[1:]:
        common.intersection_update(row[0] for row in rows)
    if len(common) < 2:
        return []

    rank = dpsi_rank(analysis, comparisons, kind)
    selected = sorted(common, key=lambda event_id: rank.get(event_id, 0.0), reverse=True)
    selected = selected[:HEATMAP_TOP_EVENTS]

    output_dir = analysis / "heatmap_input"
    outputs: list[Path] = []
    for index, ((header, rows), source) in enumerate(zip(tables, psi_files), 1):
        row_map = {row[0]: row for row in rows}
        filtered = [row_map[event_id] for event_id in selected if event_id in row_map]
        output = output_dir / f"{kind}_{index}_{source.name}"
        write_table(output, header, filtered)
        outputs.append(output)
    return outputs


def comparison_label(comparison: dict[str, str]) -> str:
    control = comparison.get("control", "ctrl")
    treatment = comparison.get("treatment", "case")
    return comparison.get("label") or f"{control} → {treatment}"


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


def generate_visualizations(job_dir: Path, plan: dict[str, Any]) -> str:
    analysis = job_dir / "output" / "analysis"
    image_root = analysis / "img"
    for name in ("bar", "PCA", "heatmap", "volcano", "upset"):
        (image_root / name).mkdir(parents=True, exist_ok=True)

    log: list[str] = []
    comparisons = load_comparisons(job_dir, plan)
    p_value = plan_threshold(plan, "p_value", 0.05)
    abs_dpsi = plan_threshold(plan, "abs_dpsi", 0.1)
    significant_dir = analysis / "sig01" / "dpsi"
    significant: dict[tuple[str, str], tuple[Path, int]] = {}

    for comparison in comparisons:
        group = comparison["group"]
        for kind in EVENT_TYPES:
            source = analysis / "dpsi" / f"{group}_{kind}.dpsi"
            if not source.exists():
                continue
            destination = significant_dir / f"{group}_{kind}.sig.dpsi"
            count = filter_significant_dpsi(source, destination, p_value, abs_dpsi)
            significant[(group, kind)] = (destination, count)

    for comparison in comparisons:
        group = comparison["group"]
        entries = [
            (kind, significant[(group, kind)][0])
            for kind in EVENT_TYPES
            if significant.get((group, kind), (None, 0))[1] > 0
        ]
        if entries:
            run_plot(
                [
                    "astk", "barplot",
                    "-i", *map(str, (path for _, path in entries)),
                    "-o", str(image_root / "bar" / f"{group}.png"),
                    "-dg",
                    "-xl", *[kind for kind, _ in entries],
                    "-fw", "7",
                    "-fh", "5",
                ],
                log,
            )

    for kind in EVENT_TYPES:
        entries = [
            (comparison, significant[(comparison["group"], kind)][0])
            for comparison in comparisons
            if significant.get((comparison["group"], kind), (None, 0))[1] > 0
        ]
        if len(entries) >= 2:
            run_plot(
                [
                    "astk", "upset",
                    "-i", *map(str, (path for _, path in entries)),
                    "-o", str(image_root / "upset" / f"{kind}.png"),
                    "-xl", *[comparison_label(comparison) for comparison, _ in entries],
                    "-dg",
                    "-fw", "7",
                    "-fh", "6",
                ],
                log,
            )

    for kind in EVENT_TYPES:
        for comparison in comparisons:
            dpsi = analysis / "dpsi" / f"{comparison['group']}_{kind}.dpsi"
            if dpsi.exists():
                run_plot(
                    [
                        "astk", "volcano",
                        "-i", str(dpsi),
                        "-o", str(image_root / "volcano" / f"{comparison['group']}_{kind}.png"),
                        "-adpsi", str(abs_dpsi),
                        "-pval", str(p_value),
                        "-fw", "6",
                        "-fh", "5",
                    ],
                    log,
                )

    if comparisons:
        first = comparisons[0]
        for kind in EVENT_TYPES:
            psi_files = [analysis / "psi" / f"{first['group']}_{kind}_c1.psi"]
            psi_files.extend(
                analysis / "psi" / f"{item['group']}_{kind}_c2.psi"
                for item in comparisons
            )
            psi_files = [path for path in psi_files if path.exists()]
            labels = [first["control"], *[item["treatment"] for item in comparisons]]
            if len(psi_files) == len(labels):
                run_plot(
                    [
                        "astk", "pca",
                        "-i", *map(str, psi_files),
                        "-o", str(image_root / "PCA" / f"{kind}.png"),
                        "-ff", "png",
                        "-gb", "col",
                        "-gl", *labels,
                        "-fw", "8",
                        "-fh", "6",
                    ],
                    log,
                )

            heatmap_inputs = prepare_heatmap_inputs(analysis, comparisons, kind)
            if heatmap_inputs:
                run_plot(
                    [
                        "astk", "hm",
                        "-i", *map(str, heatmap_inputs),
                        "-o", str(image_root / "heatmap" / f"{kind}.png"),
                        "-ff", "png",
                        "-fw", "8",
                        "-fh", "10",
                    ],
                    log,
                )

    return "\n".join(log)
