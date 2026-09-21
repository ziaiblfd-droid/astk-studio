from __future__ import annotations

import csv
import json
import math
from itertools import combinations
from pathlib import Path
from typing import Any

from .planner import native_comparison_label


EVENT_TYPES = ("A3", "A5", "AF", "AL", "MX", "RI", "SE")
HEATMAP_TOP_EVENTS = 60
UPSET_MAX_COMPARISONS = 6
VOLCANO_PVALUE_FLOOR = 1e-16


def _numpy():
    import numpy as np

    return np


def _pyplot():
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    return plt


def plan_threshold(plan: dict[str, Any], key: str, default: float) -> float:
    if plan.get(key) is not None:
        return float(plan[key])
    return default


def uses_native_astk(plan: dict[str, Any]) -> bool:
    return "astk" in str(plan.get("engine", "")).lower()


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
            if math.isfinite(dpsi) and math.isfinite(pval):
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


def read_dpsi(path: Path) -> list[tuple[str, float, float]]:
    if not str(path) or not path.is_file():
        return []
    _, rows = read_table(path)
    values: list[tuple[str, float, float]] = []
    for row in rows:
        if len(row) < 3:
            continue
        try:
            dpsi = float(row[1])
            p_value = float(row[2])
        except ValueError:
            continue
        if math.isfinite(dpsi) and math.isfinite(p_value):
            values.append((row[0], dpsi, p_value))
    return values


def read_psi(path: Path) -> tuple[list[str], dict[str, list[float | None]]]:
    header, rows = read_table(path)
    samples = header[1:] if len(header) > 1 else []
    values: dict[str, list[float | None]] = {}
    for row in rows:
        parsed: list[float | None] = []
        for raw in row[1:]:
            try:
                number = float(raw)
            except ValueError:
                parsed.append(None)
                continue
            parsed.append(number if math.isfinite(number) else None)
        values[row[0]] = parsed
    return samples, values


def dpsi_rank(analysis: Path, comparisons: list[dict[str, str]], kind: str) -> dict[str, float]:
    rank: dict[str, float] = {}
    for comparison in comparisons:
        path = analysis / "dpsi" / f"{comparison['group']}_{kind}.dpsi"
        for event_id, dpsi, _ in read_dpsi(path):
            rank[event_id] = max(rank.get(event_id, 0.0), abs(dpsi))
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
    return comparison.get("label") or f"{control} -> {treatment}"


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


def condition_psi_files(
    analysis: Path,
    comparisons: list[dict[str, str]],
    kind: str,
) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for comparison in comparisons:
        for role, suffix in (("control", "c1"), ("treatment", "c2")):
            label = comparison.get(role) or role
            if label in seen:
                continue
            path = analysis / "psi" / f"{comparison['group']}_{kind}_{suffix}.psi"
            if path.exists():
                files.append((label, path))
                seen.add(label)
    return files


def psi_matrix(
    analysis: Path,
    comparisons: list[dict[str, str]],
    kind: str,
) -> tuple[list[str], list[str], Any]:
    np = _numpy()
    files = condition_psi_files(analysis, comparisons, kind)
    if len(files) < 2:
        return [], [], np.empty((0, 0), dtype=float)

    samples: list[str] = []
    parsed: list[tuple[dict[str, list[float | None]], int]] = []
    event_sets: list[set[str]] = []
    for _, path in files:
        sample_names, values = read_psi(path)
        samples.extend(sample_names)
        parsed.append((values, len(sample_names)))
        event_sets.append(set(values))

    common = set.intersection(*event_sets)
    events = sorted(common) if common else sorted(set().union(*event_sets))
    if not events:
        return samples, [], np.empty((0, 0), dtype=float)

    matrix = np.full((len(events), len(samples)), np.nan, dtype=float)
    column_offset = 0
    for values, sample_count in parsed:
        for event_index, event_id in enumerate(events):
            row = values.get(event_id)
            if row is None:
                continue
            for local_index, value in enumerate(row[:sample_count]):
                if value is not None:
                    matrix[event_index, column_offset + local_index] = value
        column_offset += sample_count

    for column in range(matrix.shape[1]):
        values = matrix[:, column]
        finite = np.isfinite(values)
        if finite.any():
            values[~finite] = float(np.mean(values[finite]))
    for row in range(matrix.shape[0]):
        values = matrix[row, :]
        finite = np.isfinite(values)
        if finite.any():
            values[~finite] = float(np.mean(values[finite]))
    return samples, events, np.nan_to_num(matrix, nan=0.0)


def save_figure(path: Path) -> None:
    plt = _pyplot()
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()


def plot_bar(
    path: Path,
    label: str,
    sources: dict[str, Path],
    p_value: float,
    abs_dpsi: float,
    prefiltered: bool = False,
) -> None:
    plt = _pyplot()
    np = _numpy()
    up: list[int] = []
    down: list[int] = []
    for kind in EVENT_TYPES:
        if prefiltered:
            rows = [(dpsi, pval) for _, dpsi, pval in read_dpsi(sources.get(kind, Path("")))]
        else:
            rows = [
                (dpsi, pval)
                for _, dpsi, pval in read_dpsi(sources.get(kind, Path("")))
                if pval < p_value and abs(dpsi) > abs_dpsi
            ]
        up.append(sum(dpsi > 0 for dpsi, _ in rows))
        down.append(sum(dpsi < 0 for dpsi, _ in rows))

    x = np.arange(len(EVENT_TYPES))
    figure, axis = plt.subplots(figsize=(8, 4.8))
    axis.bar(x - 0.2, up, width=0.38, label="Up", color="#ef786c")
    axis.bar(x + 0.2, down, width=0.38, label="Down", color="#6d9fe8")
    axis.set_xticks(x, EVENT_TYPES)
    axis.set_ylabel("Significant events")
    axis.set_title(f"Significant splicing events: {label}")
    axis.legend(frameon=False)
    axis.grid(axis="y", alpha=0.18)
    save_figure(path)


def plot_volcano(
    path: Path,
    label: str,
    source: Path,
    p_value: float,
    abs_dpsi: float,
) -> None:
    rows = read_dpsi(source)
    if not rows:
        return
    plt = _pyplot()
    np = _numpy()
    dpsi = np.array([row[1] for row in rows], dtype=float)
    raw_pvalues = np.array([row[2] for row in rows], dtype=float)
    # SUPPA2/ASTK can emit exact zeros. Plotting against float.tiny creates a
    # ~308 y-axis and hides the nonzero points in an otherwise valid plot.
    plot_pvalues = np.maximum(raw_pvalues, VOLCANO_PVALUE_FLOOR)
    minus_log = -np.log10(plot_pvalues)
    significant = (raw_pvalues < p_value) & (np.abs(dpsi) > abs_dpsi)

    figure, axis = plt.subplots(figsize=(6.8, 5.2))
    axis.scatter(dpsi[~significant], minus_log[~significant], s=9, c="#95a7a0", alpha=0.45, linewidths=0)
    axis.scatter(dpsi[significant], minus_log[significant], s=14, c="#ef786c", alpha=0.72, linewidths=0)
    axis.axvline(abs_dpsi, color="#b5c2bc", linestyle="--", linewidth=0.8)
    axis.axvline(-abs_dpsi, color="#b5c2bc", linestyle="--", linewidth=0.8)
    axis.axhline(-math.log10(p_value), color="#b5c2bc", linestyle="--", linewidth=0.8)
    axis.set_xlabel("dPSI")
    axis.set_ylabel("-log10(p-value)")
    axis.set_title(label)
    axis.grid(alpha=0.16)
    save_figure(path)


def plot_pca(path: Path, samples: list[str], events: list[str], matrix: Any) -> None:
    if len(samples) < 2 or len(events) < 2 or matrix.shape[1] < 2:
        return
    plt = _pyplot()
    np = _numpy()
    centered = matrix.T - np.mean(matrix.T, axis=0)
    try:
        u, singular, _ = np.linalg.svd(centered, full_matrices=False)
    except np.linalg.LinAlgError:
        return
    scores = u[:, :2] * singular[:2]
    if scores.shape[1] < 2:
        scores = np.column_stack((scores[:, 0], np.zeros(len(samples))))
    explained = singular**2
    explained = explained / explained.sum() if explained.sum() else np.zeros_like(explained)
    if len(explained) < 2:
        explained = np.pad(explained, (0, 2 - len(explained)))

    figure, axis = plt.subplots(figsize=(7.2, 5.4))
    colors = ["#3f9b72", "#d89b38", "#638fd1", "#d96c70", "#8b79c6", "#61aeb9"]
    for index, label in enumerate(samples):
        axis.scatter(scores[index, 0], scores[index, 1], color=colors[index % len(colors)], s=35)
        axis.annotate(label, (scores[index, 0], scores[index, 1]), xytext=(5, 4), textcoords="offset points", fontsize=8)
    axis.axhline(0, color="#d5ddd9", linewidth=0.8)
    axis.axvline(0, color="#d5ddd9", linewidth=0.8)
    axis.set_xlabel(f"PC1 ({explained[0] * 100:.1f}%)")
    axis.set_ylabel(f"PC2 ({explained[1] * 100:.1f}%)")
    axis.set_title("PSI principal component analysis")
    axis.grid(alpha=0.15)
    save_figure(path)


def plot_heatmap(path: Path, events: list[str], samples: list[str], matrix: Any) -> None:
    if not events or not samples or matrix.size == 0:
        return
    plt = _pyplot()
    height = max(5.0, min(12.0, 0.22 * len(events) + 2.0))
    width = max(7.0, 0.38 * len(samples) + 2.0)
    figure, axis = plt.subplots(figsize=(width, height))
    image = axis.imshow(matrix, aspect="auto", cmap="coolwarm", vmin=0, vmax=1, interpolation="nearest")
    axis.set_xticks(range(len(samples)), samples, rotation=60, ha="right")
    labels = [event.split(";", 1)[0] for event in events]
    axis.set_yticks(range(len(labels)), labels)
    axis.tick_params(axis="y", labelsize=max(5, min(8, 130 // max(1, len(events)))))
    axis.set_title("Top significant events across samples")
    figure.colorbar(image, ax=axis, fraction=0.035, pad=0.02, label="PSI")
    save_figure(path)


def plot_upset(path: Path, labels: list[str], sets: list[set[str]]) -> None:
    if len(sets) < 2:
        return
    plt = _pyplot()
    np = _numpy()
    selected = list(zip(labels, sets))[:UPSET_MAX_COMPARISONS]
    combinations_to_plot: list[tuple[tuple[int, ...], int]] = []
    for size in range(1, len(selected) + 1):
        for combination in combinations(range(len(selected)), size):
            intersection = set.intersection(*(selected[index][1] for index in combination))
            if intersection:
                combinations_to_plot.append((combination, len(intersection)))
    combinations_to_plot.sort(key=lambda item: item[1], reverse=True)
    combinations_to_plot = combinations_to_plot[:12]
    if not combinations_to_plot:
        return

    figure, (bars, dots) = plt.subplots(
        2,
        1,
        figsize=(max(7.0, len(combinations_to_plot) * 0.7 + 2.0), 5.5),
        gridspec_kw={"height_ratios": [2.4, 1.3]},
        sharex=True,
    )
    x = np.arange(len(combinations_to_plot))
    bars.bar(x, [count for _, count in combinations_to_plot], color="#4aa27b")
    bars.set_ylabel("Events")
    bars.set_title("Significant-event overlap across comparisons")
    bars.grid(axis="y", alpha=0.16)

    dots.set_ylim(-0.6, len(selected) - 0.4)
    dots.set_yticks(range(len(selected)), [label for label, _ in selected])
    dots.set_xticks([])
    for column, (combination, _) in enumerate(combinations_to_plot):
        active = set(combination)
        for row in range(len(selected)):
            dots.scatter(column, row, color="#4aa27b" if row in active else "#d5ded9", s=28)
        if combination:
            dots.plot([column, column], [min(active), max(active)], color="#4aa27b", linewidth=1.2)
    dots.grid(axis="x", alpha=0.08)
    save_figure(path)


def generate_visualizations(job_dir: Path, plan: dict[str, Any]) -> str:
    analysis = job_dir / "output" / "analysis"
    image_root = analysis / "img"
    for name in ("bar", "PCA", "heatmap", "volcano", "upset"):
        (image_root / name).mkdir(parents=True, exist_ok=True)

    comparisons = load_comparisons(job_dir, plan)
    p_value = plan_threshold(plan, "p_value", 0.05)
    abs_dpsi = plan_threshold(plan, "abs_dpsi", 0.0)
    significant: dict[tuple[str, str], Path] = {}
    log: list[str] = []
    native_significant = uses_native_astk(plan)

    for comparison in comparisons:
        group = comparison["group"]
        for kind in EVENT_TYPES:
            source = analysis / "dpsi" / f"{group}_{kind}.dpsi"
            if not source.exists():
                continue
            destination = analysis / "sig01" / "dpsi" / f"{group}_{kind}.sig.dpsi"
            if not native_significant or not destination.exists():
                filter_significant_dpsi(source, destination, p_value, abs_dpsi)
            significant[(group, kind)] = destination

    for comparison in comparisons:
        group = comparison["group"]
        if native_significant:
            sources = {kind: significant[(group, kind)] for kind in EVENT_TYPES if (group, kind) in significant}
        else:
            sources = {kind: analysis / "dpsi" / f"{group}_{kind}.dpsi" for kind in EVENT_TYPES}
        try:
            plot_bar(
                image_root / "bar" / f"{group}.png",
                comparison_label(comparison),
                sources,
                p_value,
                abs_dpsi,
                prefiltered=native_significant,
            )
            log.append(f"Generated bar plot for {group}")
        except Exception as error:
            log.append(f"[warning] bar plot failed for {group}: {error}")

    for kind in EVENT_TYPES:
        for comparison in comparisons:
            source = analysis / "dpsi" / f"{comparison['group']}_{kind}.dpsi"
            try:
                plot_volcano(
                    image_root / "volcano" / f"{comparison['group']}_{kind}.png",
                    f"{comparison_label(comparison)} / {kind}",
                    source,
                    p_value,
                    abs_dpsi,
                )
                if source.exists():
                    log.append(f"Generated volcano plot for {comparison['group']} / {kind}")
            except Exception as error:
                log.append(f"[warning] volcano plot failed for {comparison['group']} / {kind}: {error}")

        try:
            samples, events, matrix = psi_matrix(analysis, comparisons, kind)
            plot_pca(image_root / "PCA" / f"{kind}.png", samples, events, matrix)
            if samples and events and matrix.size:
                log.append(f"Generated PCA plot for {kind}")
        except Exception as error:
            log.append(f"[warning] PCA plot failed for {kind}: {error}")

        try:
            samples, events, matrix = psi_matrix(analysis, comparisons, kind)
            rank = dpsi_rank(analysis, comparisons, kind)
            order = sorted(range(len(events)), key=lambda index: rank.get(events[index], 0.0), reverse=True)
            order = order[:HEATMAP_TOP_EVENTS]
            if order:
                plot_heatmap(
                    image_root / "heatmap" / f"{kind}.png",
                    [events[index] for index in order],
                    samples,
                    matrix[order, :],
                )
                log.append(f"Generated heatmap for {kind}")
        except Exception as error:
            log.append(f"[warning] heatmap failed for {kind}: {error}")

        entries = [
            (comparison_label(comparison), significant[(comparison["group"], kind)])
            for comparison in comparisons
            if (comparison["group"], kind) in significant
        ]
        try:
            plot_upset(
                image_root / "upset" / f"{kind}.png",
                [label for label, _ in entries],
                [set(row[0] for row in read_table(path)[1]) for _, path in entries],
            )
            if len(entries) >= 2:
                log.append(f"Generated UpSet plot for {kind}")
        except Exception as error:
            log.append(f"[warning] UpSet plot failed for {kind}: {error}")

    return "\n".join(log)
