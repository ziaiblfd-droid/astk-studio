"""Functional enrichment follow-up analysis for completed ASTK jobs.

The module deliberately keeps the downstream contract small:

* ``mode=ora`` runs one over-representation analysis for every
  comparison-group x AS-event-type pair.
* ``mode=compare`` reuses those independent ORA results to make a
  compareCluster-style bubble plot and heatmap.

Result figure paths are relative to the child job directory and therefore
include the ``output/`` prefix required by the existing files API.
"""
from __future__ import annotations

import csv
import gzip
import json
import math
import os
import re
import traceback
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from backend.result_parser import load_comparisons, load_gene_names, load_plan
    from backend.planner import filename_token
else:
    from .result_parser import load_comparisons, load_gene_names, load_plan
    from .planner import filename_token

ROOT = Path(__file__).resolve().parent.parent
GENESET_DIR = Path(os.getenv("ASTK_GENESET_DIR", str(ROOT / "genesets")))

EVENT_ID_PATTERN = re.compile(r";([A-Z0-9]+):([^:]+):(.+)$")
EVENT_TYPES = ("A3", "A5", "AF", "AL", "MX", "RI", "SE")
COMPARE_PAGE_SIZE = 14
EVENT_TYPE_PATTERN = re.compile(r"_(A3|A5|AF|AL|MX|RI|SE)(?:\.|_|$)", re.IGNORECASE)

GENESET_FILES = {
    "GO_BP": {"mm10": "GO_BP.gmt", "hg38": "GO_BP.gmt", "label": "GO Biological Process"},
    "GO_MF": {"mm10": "GO_MF.gmt", "hg38": "GO_MF.gmt", "label": "GO Molecular Function"},
    "GO_CC": {"mm10": "GO_CC.gmt", "hg38": "GO_CC.gmt", "label": "GO Cellular Component"},
    "KEGG": {"mm10": "KEGG_MOUSE.gmt", "hg38": "KEGG.gmt", "label": "KEGG pathways"},
}

REFERENCES = {
    "mm10": {"gtf": os.getenv("ASTK_MM10_GTF", "/refs/mm10/gencode.vM25.annotation.gtf")},
    "hg38": {"gtf": os.getenv("ASTK_HG38_GTF", "/refs/hg38/gencode.v44.annotation.gtf")},
}


def _open_text(path: Path):
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8-sig", errors="replace")


def _fisher_right(a: int, b: int, c: int, d: int) -> float:
    """One-sided Fisher exact test for over-representation."""
    from scipy.stats import hypergeom

    total = a + b + c + d
    return float(hypergeom.sf(a - 1, total, a + c, a + b)) if total else 1.0


def _bh_adjust(pvalues: list[float]) -> list[float]:
    if not pvalues:
        return []
    count = len(pvalues)
    order = sorted(range(count), key=lambda index: pvalues[index])
    adjusted = [1.0] * count
    previous = 1.0
    for reverse_rank, index in enumerate(reversed(order), start=1):
        rank = count - reverse_rank + 1
        value = min(previous, pvalues[index] * count / max(rank, 1))
        previous = value
        adjusted[index] = value
    return [min(value, 1.0) for value in adjusted]


def _read_gmt(path: Path) -> dict[str, set[str]]:
    genesets: dict[str, set[str]] = {}
    with _open_text(path) as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            genes = {gene.strip().upper() for gene in parts[2:] if gene.strip()}
            if genes:
                genesets[parts[0]] = genes
    return genesets


def _detect_species(parent_config: dict[str, Any], parent_results: dict[str, Any]) -> str:
    for source in (
        parent_results.get("reference"),
        parent_config.get("reference"),
        parent_config.get("species"),
    ):
        text = str(source or "").lower()
        if "hg38" in text or "homo" in text or "human" in text:
            return "hg38"
        if "mm10" in text or "mus " in text or "mouse" in text:
            return "mm10"
    return "mm10"


def _parent_job(store, parent_id: str) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    job = store.read(parent_id)
    if not job:
        raise RuntimeError(f"父任务不存在: {parent_id}")
    if job.get("status") != "completed":
        raise RuntimeError(f"父任务 {parent_id} 尚未完成（当前状态: {job.get('status')}）")
    job_dir = store.job_dir(parent_id)
    results_path = job_dir / "output" / "results.json"
    if not results_path.exists():
        raise RuntimeError(f"父任务 {parent_id} 缺少 results.json")
    with results_path.open("r", encoding="utf-8") as handle:
        results = json.load(handle)
    return job, job_dir, results


def _first_field(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    columns = stripped.split("\t")
    return columns[0].strip() if len(columns) > 1 else re.split(r"\s+", stripped, maxsplit=1)[0]


def _is_event_id(token: str) -> bool:
    return bool(token) and ";" in token and ":" in token


def _event_id_from_line(line: str) -> str:
    token = _first_field(line)
    return token if _is_event_id(token) else ""


def _event_type(event_id: str, fallback: str = "") -> str:
    match = EVENT_ID_PATTERN.search(event_id)
    if match and match.group(1) in EVENT_TYPES:
        return match.group(1)
    match = EVENT_TYPE_PATTERN.search(fallback)
    return match.group(1).upper() if match else ""


def _load_events_file(path: Path | None, expected_type: str = "") -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with _open_text(path) as handle:
        for line in handle:
            columns = [column.strip() for column in line.rstrip("\n").split("\t")]
            if len(columns) < 2 or not columns[0]:
                columns = re.split(r"\s+", line.strip())
            if len(columns) < 2 or not _is_event_id(columns[0]):
                continue
            event_id = columns[0]
            event_type = _event_type(event_id, path.name) or expected_type
            if expected_type and event_type != expected_type:
                continue
            try:
                dpsi = float(columns[1])
            except (ValueError, IndexError):
                continue
            try:
                pvalue = float(columns[2]) if len(columns) > 2 else float("nan")
            except (ValueError, IndexError):
                pvalue = float("nan")
            if not math.isfinite(dpsi) or not math.isfinite(pvalue) or not 0 <= pvalue <= 1:
                continue
            events.append(
                {
                    "event_id": event_id,
                    "gene_id": event_id.split(";", 1)[0],
                    "type": event_type,
                    "dpsi": dpsi,
                    "p_value": pvalue,
                }
            )
    return events


def _strip_version(gene_id: str) -> str:
    return gene_id.split(".", 1)[0]


def _load_symbol_map_from_results(parent_results: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in parent_results.get("events", []) or []:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        event_id = str(row[0])
        symbol = str(row[1]).strip()
        if not event_id or not symbol or symbol in ("-", "—", "NA", "nan"):
            continue
        gene_id = event_id.split(";", 1)[0]
        mapping.setdefault(gene_id, symbol)
        mapping.setdefault(_strip_version(gene_id), symbol)
    return mapping


def _load_gene_symbols(
    job_dir: Path,
    parent_results: dict[str, Any],
    gtf_path: Path | None,
) -> dict[str, str]:
    mapping = {
        gene_id: symbol.upper()
        for gene_id, symbol in _load_symbol_map_from_results(parent_results).items()
    }
    if gtf_path is not None:
        try:
            for gene_id, symbol in load_gene_names(gtf_path).items():
                mapping.setdefault(gene_id, str(symbol).upper())
                mapping.setdefault(_strip_version(gene_id), str(symbol).upper())
        except Exception:
            pass
    for candidate in (GENESET_DIR / "gene_symbols.tsv", job_dir / "gene_symbols.tsv"):
        if not candidate.exists():
            continue
        try:
            with _open_text(candidate) as handle:
                for line in handle:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) >= 2:
                        mapping.setdefault(parts[0], parts[1].upper())
                        mapping.setdefault(_strip_version(parts[0]), parts[1].upper())
        except OSError:
            pass
    return mapping


def _pick_event_genes(events: list[dict[str, Any]], mode: str) -> set[str]:
    picked: set[str] = set()
    for event in events:
        dpsi = event.get("dpsi", 0.0)
        if mode in {"up", "dpsi_up", "positive"} and dpsi <= 0:
            continue
        if mode in {"down", "dpsi_down", "negative"} and dpsi >= 0:
            continue
        picked.add(event["gene_id"])
    return picked


def _term_short(name: str) -> str:
    return name if len(name) <= 48 else name[:45] + "..."


def _run_ora(
    events: list[dict[str, Any]],
    background_events: list[dict[str, Any]],
    id_to_name: dict[str, str],
    genesets: dict[str, set[str]],
    gene_set_mode: str,
    pval_cut: float,
    qval_cut: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, int]:
    foreground_ids = _pick_event_genes(events, gene_set_mode)
    background_ids = {event["gene_id"] for event in background_events}
    foreground = {
        id_to_name.get(gene_id, id_to_name.get(_strip_version(gene_id), _strip_version(gene_id))).upper()
        for gene_id in foreground_ids
    }
    background = {
        id_to_name.get(gene_id, id_to_name.get(_strip_version(gene_id), _strip_version(gene_id))).upper()
        for gene_id in background_ids
    }
    annotated = set().union(*genesets.values()) if genesets else set()
    background &= annotated
    foreground &= background
    rows: list[dict[str, Any]] = []
    for term, members in genesets.items():
        in_background = members & background
        overlap_genes = in_background & foreground
        overlap = len(overlap_genes)
        if not in_background or not overlap:
            continue
        n_background = len(background)
        n_foreground = len(foreground)
        a = overlap
        b = n_foreground - a
        c = len(in_background) - a
        d = max(0, n_background - a - b - c)
        pvalue = _fisher_right(a, b, c, d)
        rows.append(
            {
                "term": term,
                "term_short": _term_short(term),
                "overlap": overlap,
                "set_size": len(in_background),
                "gene_ratio": (overlap / n_foreground) if n_foreground else 0.0,
                "bg_ratio": (len(in_background) / n_background) if n_background else 0.0,
                "p_value": pvalue,
                "genes": sorted(overlap_genes),
            }
        )
    for row, adjusted in zip(rows, _bh_adjust([row["p_value"] for row in rows])):
        row["padj"] = adjusted
        row["significant"] = row["p_value"] <= pval_cut and adjusted <= qval_cut
    rows.sort(key=lambda row: (row["p_value"], -row["overlap"], row["term"]))
    significant = [
        row for row in rows if row["p_value"] <= pval_cut and row["padj"] <= qval_cut
    ]
    return rows, significant, len(foreground), len(background)


def _matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _dotplot(ax, rows: list[dict[str, Any]], title: str) -> None:
    top = rows[:20][::-1]
    if not top:
        ax.text(0.5, 0.5, "No significant terms at the selected cutoffs", ha="center", va="center")
        ax.set_title(title, fontsize=10)
        ax.set_axis_off()
        return
    y = list(range(len(top)))
    counts = [row["overlap"] for row in top]
    scatter = ax.scatter(
        [row["gene_ratio"] for row in top],
        y,
        s=[40 + 260 * (count / max(counts)) for count in counts],
        c=[row["padj"] for row in top],
        cmap="YlOrRd_r",
        edgecolors="#555",
        linewidths=0.5,
    )
    ax.set_yticks(y)
    ax.set_yticklabels([row["term_short"] for row in top], fontsize=8)
    ax.set_xlabel("GeneRatio", fontsize=9)
    ax.set_title(title, fontsize=10)
    colorbar = ax.figure.colorbar(scatter, ax=ax, fraction=0.03, pad=0.02)
    colorbar.set_label("adjusted p-value", fontsize=8)
    ax.tick_params(axis="x", labelsize=8)
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def _safe_token(value: str) -> str:
    return filename_token(str(value))


def _write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["term", "overlap", "set_size", "gene_ratio", "p_value", "padj", "significant", "genes"])
        for row in rows:
            writer.writerow(
                [
                    row["term"],
                    row["overlap"],
                    row["set_size"],
                    f'{row["gene_ratio"]:.6f}',
                    f'{row["p_value"]:.6g}',
                    f'{row["padj"]:.6g}',
                    row["significant"],
                    ";".join(row.get("genes", [])),
                ]
            )


def _comparison_page(
    output_dir: Path,
    database: str,
    cells: list[dict[str, Any]],
    page: int = 0,
) -> tuple[list[dict[str, str]], list[str]]:
    comparison_dir = output_dir / "enrichment_compare" / database
    if page:
        comparison_dir /= f"page_{page:03d}"
    comparison_dir.mkdir(parents=True, exist_ok=True)
    usable_rows = [
        {**row, "unit_key": cell["unit_key"], "unit_label": cell["unit_key"], "event_type": cell["event_type"]}
        for cell in cells
        for row in cell["significant_rows"]
    ]
    terms = sorted(
        {row["term"] for row in usable_rows},
        key=lambda term: (min(row["padj"] for row in usable_rows if row["term"] == term), term),
    )[:25]
    units = [cell["unit_key"] for cell in cells]
    images: list[dict[str, str]] = []
    figures = []
    try:
        plt = _matplotlib()
        if terms and units:
            y_by_term = {term: index for index, term in enumerate(terms)}
            x_by_unit = {label: index for index, label in enumerate(units)}
            bubble_rows = [row for row in usable_rows if row["term"] in y_by_term]
            max_overlap = max(1, max(item["overlap"] for item in bubble_rows))
            fig, ax = plt.subplots(
                figsize=(max(7.0, 0.75 * len(units)), max(4.5, 0.28 * len(terms) + 1.8)),
                dpi=150,
            )
            figures.append(fig)
            scatter = ax.scatter(
                [x_by_unit[row["unit_label"]] for row in bubble_rows],
                [y_by_term[row["term"]] for row in bubble_rows],
                s=[40 + 220 * row["overlap"] / max_overlap for row in bubble_rows],
                c=[-math.log10(max(row["padj"], 1e-300)) for row in bubble_rows],
                cmap="YlGnBu",
                edgecolors="#4a5b55",
                linewidths=0.35,
            )
            ax.set_xticks(range(len(units)))
            ax.set_xticklabels(units, rotation=45, ha="right", fontsize=7)
            ax.set_yticks(range(len(terms)))
            ax.set_yticklabels([_term_short(term) for term in terms], fontsize=7)
            ax.set_xlabel("Comparison x AS event type", fontsize=9)
            ax.set_title(f"{database} enrichment comparison", fontsize=10)
            fig.colorbar(scatter, ax=ax, fraction=0.025, pad=0.02, label="-log10(adjusted p-value)")
            ax.grid(axis="y", linestyle=":", alpha=0.25)
            counts = sorted({1, max_overlap})
            handles = [ax.scatter([], [], s=40 + 220 * count / max_overlap, c="#789888") for count in counts]
            ax.legend(handles, [str(count) for count in counts], title="Gene count", loc="upper left", bbox_to_anchor=(1.15, 1), fontsize=7)
            fig.tight_layout()
            bubble_path = comparison_dir / "comparison_bubble.png"
            fig.savefig(bubble_path)
            plt.close(fig)
            bubble_rel = f"output/{bubble_path.relative_to(output_dir)}".replace("\\", "/")
            images.append({"name": f"{database} comparison bubble", "path": bubble_rel})

            matrix = []
            for term in terms:
                matrix.append(
                    [
                        -math.log10(
                            max(
                                next(
                                    (
                                        row["padj"]
                                        for row in bubble_rows
                                        if row["term"] == term and row["unit_label"] == unit
                                    ),
                                float("nan"),
                                ),
                                1e-300,
                            )
                        )
                        for unit in units
                    ]
                )
            fig, ax = plt.subplots(
                figsize=(max(7.0, 0.75 * len(units)), max(4.5, 0.28 * len(terms) + 1.8)),
                dpi=150,
            )
            figures.append(fig)
            import numpy as np

            cmap = plt.get_cmap("YlGnBu").with_extremes(bad="#eeeeee")
            image = ax.imshow(np.ma.masked_invalid(matrix), aspect="auto", cmap=cmap)
            ax.set_xticks(range(len(units)))
            ax.set_xticklabels(units, rotation=45, ha="right", fontsize=7)
            ax.set_yticks(range(len(terms)))
            ax.set_yticklabels([_term_short(term) for term in terms], fontsize=7)
            ax.set_xlabel("Comparison x AS event type", fontsize=9)
            ax.set_title(f"{database} adjusted-p enrichment heatmap", fontsize=10)
            fig.colorbar(image, ax=ax, fraction=0.025, pad=0.02, label="-log10(adjusted p-value)")
            fig.tight_layout()
            heatmap_path = comparison_dir / "comparison_heatmap.png"
            fig.savefig(heatmap_path)
            plt.close(fig)
            heatmap_rel = f"output/{heatmap_path.relative_to(output_dir)}".replace("\\", "/")
            images.append({"name": f"{database} comparison heatmap", "path": heatmap_rel})
        else:
            fig, ax = plt.subplots(figsize=(7.0, 3.5), dpi=150)
            figures.append(fig)
            ax.text(0.5, 0.5, "No enrichment terms available for comparison", ha="center", va="center")
            ax.set_axis_off()
            fig.tight_layout()
            for kind in ("bubble", "heatmap"):
                empty_path = comparison_dir / f"comparison_{kind}.png"
                fig.savefig(empty_path)
                images.append({"name": f"{database} comparison {kind}", "path": f"output/{empty_path.relative_to(output_dir).as_posix()}"})
            plt.close(fig)
    except Exception:
        raise RuntimeError("富集比较绘图失败，请检查 downstream_error.txt")
    finally:
        for figure in figures:
            plt.close(figure)

    files = [item["path"] for item in images]
    return images, files


def _comparison_figures(output_dir: Path, database: str, cells: list[dict[str, Any]]) -> tuple[list[dict[str, str]], list[str]]:
    images, files = [], []
    pages = math.ceil(len(cells) / COMPARE_PAGE_SIZE)
    for index in range(pages):
        start = index * COMPARE_PAGE_SIZE
        page_images, page_files = _comparison_page(
            output_dir, database, cells[start:start + COMPARE_PAGE_SIZE],
            index + 1 if pages > 1 else 0,
        )
        if pages > 1:
            for image in page_images:
                image["name"] += f" ({index + 1}/{pages})"
        images.extend(page_images)
        files.extend(page_files)
    csv_path = output_dir / "enrichment_compare" / database / "comparison.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["unit", "comparison", "event_type", "term", "overlap", "set_size", "gene_ratio", "p_value", "padj", "significant", "genes"])
        for cell in cells:
            for row in cell["rows"]:
                writer.writerow([
                    cell["unit_key"], cell["group"], cell["event_type"], row["term"],
                    row["overlap"], row["set_size"], row["gene_ratio"], row["p_value"],
                    row["padj"], row["significant"], ";".join(row["genes"]),
                ])
    files.append(f"output/{csv_path.relative_to(output_dir).as_posix()}")
    return images, files


def _comparison_units(parent_dir: Path) -> list[dict[str, str]]:
    plan = load_plan(parent_dir)
    comparisons = load_comparisons(parent_dir, plan)
    if not comparisons:
        result_path = parent_dir / "output" / "results.json"
        comparisons = json.loads(result_path.read_text(encoding="utf-8")).get("comparisons", [])
    if not comparisons:
        pattern = re.compile(r"^(.+)_(A3|A5|AF|AL|MX|RI|SE)(?:\.sig)?\.dpsi$")
        groups = set()
        for directory in (parent_dir / "output/analysis/dpsi", parent_dir / "output/analysis/sig01/dpsi"):
            for path in directory.glob("*.dpsi"):
                match = pattern.fullmatch(path.name)
                if match:
                    groups.add(match.group(1))
        comparisons = [{"group": group} for group in sorted(groups)]
    for item in comparisons:
        group = str(item["group"])
        if "/" in group or "\\" in group or group in {".", ".."}:
            raise ValueError("Invalid comparison identifier")
    if comparisons:
        return [
            {
                "group": str(item["group"]),
                "label": str(item.get("label") or item.get("group")),
            }
            for item in {str(item["group"]): item for item in comparisons}.values()
        ]
    raise RuntimeError("无法识别比较组，父任务需要 plan.json 或按比较组命名的 dPSI 文件")


def _find_event_file(
    parent_dir: Path,
    group: str,
    event_type: str,
    significant: bool,
) -> Path | None:
    analysis = parent_dir / "output" / "analysis"
    directory = analysis / "sig01" / "dpsi" if significant else analysis / "dpsi"
    suffix = ".sig.dpsi" if significant else ".dpsi"
    directories = (directory, analysis / "sig01") if significant else (directory,)
    for directory in directories:
        for token in dict.fromkeys((group, _safe_token(group))):
            candidate = directory / f"{token}_{event_type}{suffix}"
            if candidate.is_file():
                return candidate
        if significant:
            aggregate = directory / f"{group}.sig.dpsi"
            if aggregate.is_file():
                return aggregate
    return None


def run_enrichment(store, job_id: str, parent_id: str, params: dict[str, Any]) -> dict[str, Any]:
    parent_job, parent_dir, parent_results = _parent_job(store, parent_id)
    parent_config = parent_job.get("config", {}) or {}
    species = _detect_species(parent_config, parent_results)
    database = str(params.get("database") or params.get("db") or "GO_BP").upper()
    if database not in GENESET_FILES:
        database = "GO_BP"
    mode = str(params.get("mode") or "ora").lower().strip()
    if mode not in {"ora", "compare"}:
        mode = "ora"
    gene_set_mode = str(params.get("gene_set") or "significant").lower().strip()
    if gene_set_mode not in {"significant", "up", "down"}:
        gene_set_mode = "significant"

    def cutoff(*names: str, default: float = 0.05) -> float:
        value: Any = default
        for name in names:
            if name in params and params[name] is not None and str(params[name]).strip():
                value = params[name]
                break
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = default
        if not math.isfinite(value):
            value = default
        return min(1.0, max(0.0, value))

    pval_cut = cutoff("pvalue", "pval")
    qval_cut = cutoff("qvalue", "qval")
    gtf_config = REFERENCES.get(species, REFERENCES["mm10"]).get("gtf")
    plan = load_plan(parent_dir)
    reference = plan.get("reference") or parent_results.get("reference") or {}
    if isinstance(reference, dict) and reference.get("gtf"):
        gtf_config = reference["gtf"]
    gtf_path = Path(gtf_config) if gtf_config else None
    id_to_name = _load_gene_symbols(parent_dir, parent_results, gtf_path)
    gmt_name = GENESET_FILES[database].get(species) or GENESET_FILES[database]["mm10"]
    gmt_path = GENESET_DIR / gmt_name
    if not gmt_path.exists():
        raise RuntimeError(f"基因集文件缺失: {gmt_path}")
    genesets = _read_gmt(gmt_path)
    if not genesets:
        raise RuntimeError("基因集文件为空")

    units = _comparison_units(parent_dir)
    cells: list[dict[str, Any]] = []
    for unit in units:
        store.update(job_id, stage="enrichment_statistics", progress=5 + int(40 * len(cells) / (len(units) * len(EVENT_TYPES))))
        group = unit["group"]
        for event_type in EVENT_TYPES:
            significant_path = _find_event_file(parent_dir, group, event_type, True)
            background_path = _find_event_file(parent_dir, group, event_type, False)
            significant_events = _load_events_file(significant_path, event_type)
            background_events = _load_events_file(background_path, event_type)
            if background_path is None:
                significant_events = []
            elif significant_path is None:
                plan = load_plan(parent_dir)
                base_p = float(plan.get("p_value", parent_config.get("p_value", 0.05)))
                base_dpsi = float(plan.get("abs_dpsi", parent_config.get("abs_dpsi", 0.1)))
                significant_events = [e for e in background_events if e["p_value"] < base_p and abs(e["dpsi"]) > base_dpsi]
            rows, significant_rows, input_genes, background_genes = _run_ora(
                significant_events,
                background_events,
                id_to_name,
                genesets,
                gene_set_mode,
                pval_cut,
                qval_cut,
            )
            cells.append(
                {
                    "group": group,
                    "comparison": unit["label"],
                    "event_type": event_type,
                    "unit_key": f"{_safe_token(group)}_{event_type}",
                    "unit_label": f"{unit['label']} · {event_type}",
                    "rows": rows,
                    "significant_rows": significant_rows,
                    "input_genes": input_genes,
                    "background_genes": background_genes,
                    "missing": background_path is None,
                    "source": "significant_file" if significant_path else "derived_from_dpsi",
                    "status": "missing_background" if background_path is None else "no_tested_events" if not background_events else "no_mapped_genes" if significant_events and not input_genes else "completed",
                }
            )

    output_dir = store.job_dir(job_id) / "output"
    if all(cell["missing"] for cell in cells):
        raise RuntimeError("缺少背景 dPSI 文件，无法运行富集分析")
    images: list[dict[str, str]] = []
    files: list[str] = []
    if mode == "ora":
        for index, cell in enumerate(cells):
            store.update(job_id, stage="enrichment_figures", progress=45 + int(50 * index / len(cells)))
            unit_dir = output_dir / "enrichment" / cell["unit_key"]
            figure_path = unit_dir / f"{database}.png"
            unit_dir.mkdir(parents=True, exist_ok=True)
            display_rows = cell["significant_rows"]
            fig = None
            try:
                plt = _matplotlib()
                fig, ax = plt.subplots(
                    figsize=(7.2, max(3.0, 0.34 * min(len(display_rows), 20) + 1.6)),
                    dpi=150,
                )
                _dotplot(
                    ax,
                    display_rows,
                    f"{cell['group']} | {cell['event_type']} | {database}",
                )
                if not display_rows and cell["status"] != "completed":
                    ax.texts[0].set_text(cell["status"].replace("_", " "))
                fig.tight_layout()
                fig.savefig(figure_path)
                plt.close(fig)
                figure_rel = f"output/{figure_path.relative_to(output_dir)}".replace("\\", "/")
                images.append(
                    {
                        "name": f"{cell['comparison']} · {cell['event_type']}",
                        "path": figure_rel,
                        "comparison": cell["group"],
                        "event_type": cell["event_type"],
                    }
                )
                files.append(figure_rel)
            except Exception:
                raise RuntimeError(f"富集绘图失败: {cell['unit_key']}")
            finally:
                if fig is not None:
                    plt.close(fig)
            csv_path = unit_dir / "results.csv"
            _write_rows_csv(csv_path, cell["rows"])
            files.append(f"output/{csv_path.relative_to(output_dir)}".replace("\\", "/"))
        # Keep one aggregate download for clients that used the initial API.
        aggregate_rows: list[dict[str, Any]] = []
        for cell in cells:
            aggregate_rows.extend(
                {**row, "comparison": cell["comparison"], "event_type": cell["event_type"]}
                for row in cell["rows"]
            )
        aggregate_path = output_dir / f"enrichment_{database}.csv"
        aggregate_path.parent.mkdir(parents=True, exist_ok=True)
        with aggregate_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["comparison", "event_type", "term", "overlap", "set_size", "gene_ratio", "p_value", "padj", "significant", "genes"])
            for row in aggregate_rows:
                writer.writerow([
                    row["comparison"], row["event_type"], row["term"], row["overlap"],
                    row["set_size"], f'{row["gene_ratio"]:.6f}', f'{row["p_value"]:.6g}',
                    f'{row["padj"]:.6g}', row["significant"], ";".join(row.get("genes", [])),
                ])
        files.append(f"output/{aggregate_path.name}")
    else:
        store.update(job_id, stage="enrichment_comparison_figures", progress=50)
        compare_images, compare_files = _comparison_figures(output_dir, database, cells)
        images.extend(compare_images)
        files.extend(compare_files)

    expected_plots = len(cells) if mode == "ora" else 2 * math.ceil(len(cells) / COMPARE_PAGE_SIZE)
    summary = {
        "Database": GENESET_FILES[database]["label"],
        "Mode": "Over-representation analysis" if mode == "ora" else "Enrichment comparison",
        "Gene set": gene_set_mode,
        "Species": species,
        "Comparisons": len(units),
        "AS event types": len(EVENT_TYPES),
        "Expected plots": expected_plots,
        "Generated plots": len(images),
        "Missing input pairs": sum(cell["missing"] for cell in cells),
        "p / q cutoff": f"{pval_cut:g} / {qval_cut:g}",
    }
    return {
        "module": "enrichment",
        "mode": mode,
        "job_id": job_id,
        "parent_job_id": parent_id,
        "params": {
            "mode": mode,
            "database": database,
            "gene_set": gene_set_mode,
            "pvalue": pval_cut,
            "qvalue": qval_cut,
        },
        "summary": summary,
        "table": [],
        "images": {mode: images},
        "files": files,
        "units": [
            {
                "comparison": cell["comparison"],
                "event_type": cell["event_type"],
                "input_genes": cell["input_genes"],
                "background_genes": cell["background_genes"],
                "terms": len(cell["rows"]),
                "significant_terms": len(cell["significant_rows"]),
                "missing": cell["missing"],
                "group": cell["group"],
                "status": cell["status"],
                "source": cell["source"],
            }
            for cell in cells
        ],
    }


def run_downstream(store, job_id: str) -> None:
    job = store.read(job_id) or {}
    config = job.get("config", {}) or {}
    downstream = config.get("downstream") or {}
    module = str(downstream.get("module", "")).lower()
    parent_id = downstream.get("parent_job_id") or config.get("parent_job_id")
    params = downstream.get("params") or {}

    store.update(job_id, status="running", stage="downstream")
    try:
        if module != "enrichment":
            raise RuntimeError(f"未知的后续分析模块: {module or '(missing)'}")
        if not parent_id:
            raise RuntimeError("缺少父任务 ID")
        results = run_enrichment(store, job_id, parent_id, params)
        output = store.job_dir(job_id) / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / "results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        store.update(job_id, status="completed", stage="done", progress=100)
    except Exception as exc:  # noqa: BLE001
        store.update(job_id, status="failed", error=str(exc), stage="failed")
        output = store.job_dir(job_id) / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / "downstream_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
