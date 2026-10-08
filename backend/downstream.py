"""Downstream analysis modules (functional enrichment / motif enrichment).

Runs on the server as a follow-up job after a primary ASTK/SUPPA job has
completed. A downstream job carries ``config.downstream = {module, params,
parent_job_id}``; the queue dispatch in ``server.py`` routes it here instead of
``runner.run_job``.

Result contract (written to ``output/results.json``)::

    {
      "module": "enrichment" | "motif",
      "job_id": ..., "parent_job_id": ...,
      "params": {...},
      "summary": {label: value, ...},
      "table": [[...header...], [...rows...]],
      "images": {"downstream": [{"name": ..., "path": ...}, ...]},
      "files": [...],
    }

``path`` is relative to the job directory so the existing
``/api/jobs/{id}/files/{path}`` route can serve the figures directly.

Design notes (2026-10-08 rewrite)
---------------------------------
Faithful re-implementation of the over-representation analysis used by
``astk enrich`` (clusterProfiler-style): one-sided Fisher exact test on
gene-set overlap, Benjamini-Hochberg FDR, and a dot/bubble plot whose axes
match ASTK's ``dotplot`` output (GeneRatio on x, term on y, point size =
overlap count, colour = adjusted p-value).

Optimisation over the previous version: gene-id -> gene-symbol resolution is
now multi-source and no longer hard-depends on a ``/refs`` GTF. It resolves, in
order, (1) symbols already present in the parent ``results.json`` events table,
(2) a GTF if one is available, (3) a lightweight gene-id map shipped with the
run. This keeps results identical to ASTK when symbols line up, while letting
the module run in environments without the reference GTF.
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
from typing import Any, Iterable

if __package__ in (None, ""):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from backend.result_parser import load_gene_names
else:
    from .result_parser import load_gene_names

ROOT = Path(__file__).resolve().parent.parent
GENESET_DIR = Path(os.getenv("ASTK_GENESET_DIR", str(ROOT / "genesets")))

EVENT_ID_PATTERN = re.compile(r";([A-Z0-9]+):([^:]+):(.+)$")
EVENT_TYPES = ("SE", "RI", "A3", "A5", "AF", "AL", "MX")

GENESET_FILES = {
    "GO_BP": {"mm10": "GO_BP.gmt", "hg38": "GO_BP.gmt", "label": "GO Biological Process"},
    "GO_MF": {"mm10": "GO_MF.gmt", "hg38": "GO_MF.gmt", "label": "GO Molecular Function"},
    "GO_CC": {"mm10": "GO_CC.gmt", "hg38": "GO_CC.gmt", "label": "GO Cellular Component"},
    "KEGG": {"mm10": "KEGG_MOUSE.gmt", "hg38": "KEGG.gmt", "label": "KEGG pathways"},
}

REFERENCES = {
    "mm10": {
        "gtf": os.getenv("ASTK_MM10_GTF", "/refs/mm10/gencode.vM25.annotation.gtf"),
        "fasta": os.getenv("ASTK_MM10_FASTA", "/refs/mm10/GRCm38.primary_assembly.genome.fa"),
    },
    "hg38": {
        "gtf": os.getenv("ASTK_HG38_GTF", "/refs/hg38/gencode.v44.annotation.gtf"),
        "fasta": os.getenv("ASTK_HG38_FASTA", "/refs/hg38/GRCh38.primary_assembly.genome.fa"),
    },
}

# IUPAC degenerate base codes used by common RBP motifs.
IUPAC = {
    "A": "A", "C": "C", "G": "G", "T": "T", "U": "T",
    "R": "AG", "Y": "CT", "S": "GC", "W": "AT", "K": "GT", "M": "AC",
    "B": "CGT", "D": "AGT", "H": "ACT", "V": "ACG", "N": "ACGT",
}

# Curated RBP binding motifs relevant to alternative-splicing regulation.
RBP_MOTIFS = [
    ("SRSF1", "GGAGA"),
    ("SRSF2", "SSNGSS"),          # G/C-rich
    ("SRSF3", "CAWYC"),
    ("SRSF5", "GGAWC"),
    ("SRSF6", "UGWGG"),
    ("hnRNPA1", "UAGGGU"),
    ("hnRNPA2B1", "UAGGG"),
    ("hnRNPC", "UUUUU"),
    ("PTBP1", "YCVYY"),
    ("RBFOX2", "UGCAUG"),
    ("MBNL1", "YGCY"),
    ("CELF1", "UGUU"),
    ("QKI", "ACUAAY"),
    ("NOVA1", "YCAY"),
    ("HuR/ELAVL1", "UUUAUUU"),
    ("TIA1", "UUUU"),
]


# --------------------------------------------------------------------------- #
# generic helpers
# --------------------------------------------------------------------------- #
def _open_text(path: Path):
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def _fisher_right(a: int, b: int, c: int, d: int) -> float:
    """One-sided (over-representation) Fisher exact test p-value.

    Contingency table (gene-set membership x significance)::

                 in set   not in set
        sig         a          b
        bg          c          d
    """
    n = a + b + c + d
    if n <= 0:
        return 1.0

    def log_choose(x: int, y: int) -> float:
        if y < 0 or y > x:
            return float("-inf")
        return math.lgamma(x + 1) - math.lgamma(y + 1) - math.lgamma(x - y + 1)

    log_den = log_choose(n, a + c)
    row1 = a + b
    col1 = a + c
    p = 0.0
    lo = max(0, row1 + col1 - n)
    hi = min(row1, col1)
    for x in range(a, hi + 1):
        if x < lo:
            continue
        log_p = log_choose(row1, x) + log_choose(n - row1, col1 - x) - log_den
        p += math.exp(log_p)
    return min(p, 1.0)


def _bh_adjust(pvalues: list[float]) -> list[float]:
    m = len(pvalues)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [1.0] * m
    prev = 1.0
    for rank, idx in enumerate(reversed(order), start=1):
        k = m - rank + 1
        value = min(prev, pvalues[idx] * m / max(k, 1))
        prev = value
        adjusted[idx] = value
    return [min(v, 1.0) for v in adjusted]


def _read_gmt(path: Path) -> dict[str, set[str]]:
    genesets: dict[str, set[str]] = {}
    with _open_text(path) as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            name = parts[0]
            genes = {g.strip().upper() for g in parts[2:] if g.strip()}
            if genes:
                genesets[name] = genes
    return genesets


def _detect_species(parent_config: dict[str, Any], parent_results: dict[str, Any]) -> str:
    for source in (parent_results.get("reference"), parent_config.get("reference"), parent_config.get("species")):
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


def _load_sig_events(parent_dir: Path) -> list[dict[str, Any]]:
    """Parse every ``*.sig.dpsi`` under the parent's output directory.

    File columns: event_id, dpsi, p_value (tab separated, optional header).
    event_id looks like ``<gene_id>;<TYPE>:<chr>:<coords>``.
    """
    events: list[dict[str, Any]] = []
    candidates = sorted(parent_dir.rglob("*.sig.dpsi")) or sorted(parent_dir.rglob("*.sig.*"))
    for path in candidates:
        with _open_text(path) as handle:
            for line in handle:
                if line.lower().lstrip().startswith(("event", "gene")):
                    continue
                cols = [c.strip() for c in line.rstrip("\n").split("\t")]
                if len(cols) < 2 or not cols[0]:
                    cols = re.split(r"\s+", line.strip())
                if len(cols) < 2 or not _is_event_id(cols[0]):
                    continue
                event_id = cols[0]
                gene_id = event_id.split(";", 1)[0]
                m = EVENT_ID_PATTERN.search(event_id)
                etype = m.group(1) if m else ""
                chrom = m.group(2) if m else ""
                coords = m.group(3) if m else ""
                try:
                    dpsi = float(cols[1])
                except (ValueError, IndexError):
                    dpsi = 0.0
                try:
                    pval = float(cols[2]) if len(cols) > 2 else float("nan")
                except (ValueError, IndexError):
                    pval = float("nan")
                events.append({
                    "event_id": event_id, "gene_id": gene_id, "type": etype,
                    "chrom": chrom, "coords": coords, "dpsi": dpsi, "p_value": pval,
                })
    return events


def _first_field(line: str) -> str:
    """Return the leading token of a whitespace/tab separated line, or ''."""
    stripped = line.strip()
    if not stripped:
        return ""
    cols = stripped.split("\t")
    if len(cols) > 1:
        return cols[0].strip()
    return re.split(r"\s+", stripped, maxsplit=1)[0]


def _is_event_id(token: str) -> bool:
    """True for ASTK event ids like ENSMUSG00000000028.15;SE:chr16:...:..."""
    return bool(token) and ";" in token and ":" in token


def _event_id_from_line(line: str) -> str:
    """Extract an event id from a whitespace/tab separated result row."""
    token = _first_field(line)
    return token if _is_event_id(token) else ""


def _load_background_genes(parent_dir: Path) -> set[str]:
    """All tested genes = every gene id appearing in the dpsi result files."""
    genes: set[str] = set()
    for path in sorted(parent_dir.rglob("*.dpsi")):
        with _open_text(path) as handle:
            for line in handle:
                if line.lower().lstrip().startswith(("event", "gene")):
                    continue
                token = _first_field(line)
                if _is_event_id(token):
                    genes.add(token.split(";", 1)[0])
    return genes


def _strip_version(gene_id: str) -> str:
    """ENSMUSG00000000127.15 -> ENSMUSG00000000127"""
    return gene_id.split(".", 1)[0]


def _load_symbol_map_from_results(parent_results: dict[str, Any]) -> dict[str, str]:
    """Build gene_id -> gene_symbol from the parent results event table.

    The event table rows are ``[event_id, symbol, type, ...]`` where ``event_id``
    is ``<gene_id>;<TYPE>:...``. This is the most reliable symbol source because
    it is already produced by the primary analysis and needs no reference file.
    """
    mapping: dict[str, str] = {}
    events = parent_results.get("events")
    if not isinstance(events, list):
        return mapping
    for row in events:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        event_id = str(row[0])
        symbol = str(row[1]).strip()
        if not event_id or not symbol or symbol in ("-", "—", "NA", "nan"):
            continue
        gene_id = event_id.split(";", 1)[0]
        if gene_id and gene_id != symbol:
            mapping.setdefault(gene_id, symbol)
            mapping.setdefault(_strip_version(gene_id), symbol)
    return mapping


def _load_gene_symbols(job_dir: Path, parent_results: dict[str, Any], gtf_path: Path | None) -> dict[str, str]:
    """Multi-source gene-id -> symbol resolver (symbols upper-cased for GMT match).

    Order of preference ensures result parity with ASTK enrich, while allowing
    the module to run without a reference GTF.
    """
    mapping: dict[str, str] = {}

    # (0) symbols embedded in the run's own event table (no external files)
    for gid, sym in _load_symbol_map_from_results(parent_results).items():
        mapping[gid] = sym.upper()

    # (1) reference GTF, if available (authoritative for ASTK parity)
    if gtf_path is not None:
        try:
            gtf_map = load_gene_names(gtf_path if isinstance(gtf_path, Path) else Path(gtf_path))
            for gid, sym in gtf_map.items():
                mapping.setdefault(gid, str(sym).upper())
                mapping.setdefault(_strip_version(gid), str(sym).upper())
        except Exception:
            pass

    # (2) optional lightweight id->symbol map shipped with the deployment
    for candidate in (ROOT / "genesets" / "gene_symbols.tsv", job_dir / "gene_symbols.tsv"):
        if candidate.exists():
            try:
                with _open_text(candidate) as handle:
                    for line in handle:
                        parts = line.rstrip("\n").split("\t")
                        if len(parts) >= 2:
                            mapping.setdefault(parts[0], parts[1].upper())
                            mapping.setdefault(_strip_version(parts[0]), parts[1].upper())
            except Exception:
                pass

    return mapping


def _matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


# --------------------------------------------------------------------------- #
# enrichment module
# --------------------------------------------------------------------------- #
def _pick_event_genes(events: list[dict[str, Any]], mode: str) -> set[str]:
    mode = (mode or "significant").lower()
    picked: set[str] = set()
    for ev in events:
        if mode in ("up", "dpsi_up", "positive") and ev.get("dpsi", 0.0) < 0:
            continue
        if mode in ("down", "dpsi_down", "negative") and ev.get("dpsi", 0.0) > 0:
            continue
        picked.add(ev["gene_id"])
    return picked


def _dotplot(ax, rows: list[dict[str, Any]], title: str):
    """ASTK-style dotplot: GeneRatio on x, terms on y, size = overlap, colour = padj."""
    top = rows[:20][::-1]
    if not top:
        ax.text(0.5, 0.5, "no significant terms", ha="center", va="center")
        ax.set_axis_off()
        return
    y = list(range(len(top)))
    ratios = [r["gene_ratio"] for r in top]
    counts = [r["overlap"] for r in top]
    padj = [r["padj"] for r in top]

    sizes = [40 + 260 * (c / max(counts)) for c in counts]
    scatter = ax.scatter(ratios, y, s=sizes, c=padj, cmap="YlOrRd_r", edgecolors="#555", linewidths=0.5)
    ax.set_yticks(y)
    ax.set_yticklabels([r["term_short"] for r in top], fontsize=8)
    ax.set_xlabel("GeneRatio", fontsize=9)
    ax.set_title(title, fontsize=10)
    cbar = ax.figure.colorbar(scatter, ax=ax, fraction=0.03, pad=0.02)
    cbar.set_label("adjusted p-value", fontsize=8)
    ax.tick_params(axis="x", labelsize=8)
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def _term_short(name: str) -> str:
    if " (" in name and name.endswith(")"):
        label, _, rest = name.partition(" (")
        if len(label) > 46:
            label = label[:44] + "…"
        return label
    return name[:48]


def run_enrichment(store, job_id: str, parent_id: str, params: dict[str, Any]) -> dict[str, Any]:
    _job, parent_dir, parent_results = _parent_job(store, parent_id)
    parent_config = _job.get("config", {}) or {}
    species = _detect_species(parent_config, parent_results)
    db = str(params.get("database") or params.get("db") or "GO_BP").upper()
    if db not in GENESET_FILES:
        db = "GO_BP"
    gene_set_mode = str(params.get("gene_set") or "significant").lower().strip()
    if gene_set_mode not in {"significant", "up", "down", "all"}:
        gene_set_mode = "significant"

    def _cutoff(*names: str, default: float = 0.05) -> float:
        value: Any = default
        for name in names:
            if name in params and params[name] is not None and str(params[name]).strip() != "":
                value = params[name]
                break
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        return min(1.0, max(0.0, parsed))

    pval_cut = _cutoff("pvalue", "pval")
    qval_cut = _cutoff("qvalue", "qval")

    ref = REFERENCES.get(species, REFERENCES["mm10"])
    gtf_path = Path(ref["gtf"]) if ref.get("gtf") else None
    id_to_name = _load_gene_symbols(parent_dir, parent_results, gtf_path)

    # foreground gene ids (symbols resolved below)
    events = _load_sig_events(parent_dir)
    if gene_set_mode == "all":
        signif_ids = set()
        for path in sorted(parent_dir.rglob("*.dpsi")):
            with _open_text(path) as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    event_id = _event_id_from_line(line)
                    if event_id:
                        signif_ids.add(event_id.split(";", 1)[0])
    else:
        signif_ids = _pick_event_genes(events, gene_set_mode)

    signif_genes = {id_to_name.get(g, _strip_version(g)) for g in signif_ids}
    signif_genes = {g.upper() for g in signif_genes if g}

    bg_ids = _load_background_genes(parent_dir)
    bg_genes = {id_to_name.get(g, _strip_version(g)) for g in bg_ids}
    bg_genes = {g.upper() for g in bg_genes if g}
    # background must at least contain the foreground genes
    bg_genes |= signif_genes

    gmt_name = GENESET_FILES[db].get(species) or GENESET_FILES[db]["mm10"]
    gmt_path = GENESET_DIR / gmt_name
    if not gmt_path.exists():
        raise RuntimeError(f"基因集文件缺失: {gmt_path}")
    genesets = _read_gmt(gmt_path)

    n_bg = len(bg_genes)
    n_sig = len(signif_genes)
    rows: list[dict[str, Any]] = []
    for term, members in genesets.items():
        in_bg = members & bg_genes
        if not in_bg:
            continue
        overlap = in_bg & signif_genes
        a = len(overlap)
        if a == 0:
            continue
        b = n_sig - a
        c = len(in_bg) - a
        d = n_bg - a - b - c
        if d < 0:
            d = 0
        p_value = _fisher_right(a, b, c, d)
        rows.append({
            "term": term,
            "term_short": _term_short(term),
            "overlap": a,
            "set_size": len(in_bg),
            "gene_ratio": (a / n_sig) if n_sig else 0.0,
            "bg_ratio": (len(in_bg) / n_bg) if n_bg else 0.0,
            "p_value": p_value,
            "genes": sorted(overlap)[:40],
        })

    padj = _bh_adjust([r["p_value"] for r in rows])
    for r, q in zip(rows, padj):
        r["padj"] = q
    rows.sort(key=lambda r: (r["p_value"], -r["overlap"]))

    sig_rows = [r for r in rows if r["p_value"] <= pval_cut and r["padj"] <= qval_cut]
    top = (sig_rows or rows)[:50]

    # ---- figure ----
    out_dir = store.job_dir(job_id) / "output"
    (out_dir / "img").mkdir(parents=True, exist_ok=True)
    # The /api/jobs/{id}/files/{path} route resolves {path} relative to the JOB
    # directory, so stored paths must carry the "output/" prefix, exactly like the
    # primary-analysis figures ("output/analysis/img/..."). Without it the figure
    # 404s and the frontend shows a broken image.
    fig_rel = f"output/img/enrichment_{db}.png"
    fig_abs = out_dir / "img" / f"enrichment_{db}.png"
    try:
        plt = _matplotlib()
        fig, ax = plt.subplots(figsize=(7.2, max(3.0, 0.34 * min(len(top), 20) + 1.6)), dpi=150)
        _dotplot(ax, top, f"{db} enrichment · {GENESET_FILES[db]['label']}")
        fig.tight_layout()
        fig.savefig(fig_abs)
        plt.close(fig)
        images = [{"name": f"{db} dotplot", "path": fig_rel}]
    except Exception:
        images = []

    table = [["term", "overlap", "set_size", "gene_ratio", "p_value", "padj"]]
    for r in top[:50]:
        table.append([
            r["term"], r["overlap"], r["set_size"],
            f"{r['gene_ratio']:.4f}", f"{r['p_value']:.3g}", f"{r['padj']:.3g}",
        ])

    # downloadable result table (path keeps the "output/" prefix for the files route)
    csv_name = f"enrichment_{db}.csv"
    csv_rel = f"output/{csv_name}"
    try:
        with (out_dir / csv_name).open("w", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle).writerows(table)
    except Exception:
        csv_rel = ""

    summary = {
        "Database": GENESET_FILES[db]["label"],
        "Gene set": gene_set_mode,
        "Species": species,
        "Input genes": n_sig,
        "Background genes": n_bg,
        "Terms tested": len(rows),
        "Significant terms": len(sig_rows),
        "p / q cutoff": f"{pval_cut:g} / {qval_cut:g}",
        "Symbol source": "results.json events" + (" + GTF" if gtf_path and gtf_path.exists() else ""),
    }

    return {
        "module": "enrichment",
        "job_id": job_id,
        "parent_job_id": parent_id,
        "params": {"database": db, "gene_set": gene_set_mode, "pvalue": pval_cut, "qvalue": qval_cut},
        "summary": summary,
        "table": table,
        "images": {"downstream": images},
        "files": [p for p in ((fig_rel if images else ""), csv_rel) if p],
    }


# --------------------------------------------------------------------------- #
# motif module
# --------------------------------------------------------------------------- #
class _Fasta:
    def __init__(self, path: Path):
        self.path = path
        self._index: dict[str, tuple[int, int, int, int]] | None = None
        self._sequence_cache: dict[str, str] = {}

    def _load_index(self) -> dict[str, tuple[int, int, int, int]]:
        if self._index is not None:
            return self._index
        index: dict[str, tuple[int, int, int, int]] = {}
        fai = Path(str(self.path) + ".fai")
        if fai.exists() and not str(self.path).endswith(".gz"):
            try:
                for line in fai.read_text(encoding="utf-8", errors="replace").splitlines():
                    fields = line.split("\t")
                    if len(fields) < 5:
                        continue
                    name = fields[0]
                    index[name] = (
                        int(fields[1]), int(fields[2]), int(fields[3]), int(fields[4])
                    )
            except (OSError, ValueError):
                index = {}
        if not index and not str(self.path).endswith(".gz") and self.path.exists():
            try:
                with self.path.open("rb") as handle:
                    name = ""
                    length = 0
                    offset = 0
                    line_bases = 0
                    line_width = 0
                    while True:
                        line_offset = handle.tell()
                        raw = handle.readline()
                        if not raw:
                            break
                        if raw.startswith(b">"):
                            if name:
                                index[name] = (length, offset, line_bases, line_width)
                            name = raw[1:].split(None, 1)[0].decode("ascii", "ignore")
                            length = 0
                            offset = handle.tell()
                            line_bases = 0
                            line_width = 0
                        elif name:
                            bases = raw.rstrip(b"\r\n")
                            if bases:
                                if not line_bases:
                                    offset = line_offset
                                    line_bases = len(bases)
                                    line_width = len(raw)
                                length += len(bases)
                    if name:
                        index[name] = (length, offset, line_bases, line_width)
            except OSError:
                index = {}
        self._index = index
        return index

    def _load_chromosome(self, chrom: str) -> str:
        if chrom in self._sequence_cache:
            return self._sequence_cache[chrom]
        if not self.path.exists():
            return ""
        sequence: list[str] = []
        try:
            opener = gzip.open(self.path, "rt", encoding="utf-8", errors="replace") \
                if str(self.path).endswith(".gz") else self.path.open(
                    "r", encoding="utf-8", errors="replace"
                )
            with opener as handle:
                current = None
                for line in handle:
                    if line.startswith(">"):
                        current = line[1:].split()[0]
                        continue
                    if current == chrom:
                        sequence.append(line.strip())
        except OSError:
            return ""
        value = "".join(sequence).upper()
        self._sequence_cache[chrom] = value
        return value

    def fetch(self, chrom: str, start: int, end: int) -> str:
        if not self.path.exists():
            return ""
        start = max(0, start)
        if end <= start:
            return ""
        index = self._load_index()
        if chrom in index:
            _length, offset, line_bases, line_width = index[chrom]
            try:
                with self.path.open("rb") as handle:
                    first_line = start // line_bases
                    intra_line = start % line_bases
                    handle.seek(offset + first_line * line_width)
                    needed = max(0, end - start) + intra_line
                    raw = handle.read(needed + (needed // max(1, line_bases) + 2) * (line_width - line_bases))
                return b"".join(raw.splitlines()).decode("ascii", "ignore")[intra_line:intra_line + end - start].upper()
            except (OSError, UnicodeError, ZeroDivisionError):
                pass
        return self._load_chromosome(chrom)[start:end]


def _parse_coords(event: dict[str, Any], region: str) -> tuple[str, int, int] | None:
    chrom = event.get("chrom")
    coords = event.get("coords") or ""
    if not chrom or not coords:
        return None
    m = re.match(r"^(\d+)-(\d+):(\d+)-(\d+)$", coords)
    if not m:
        return None
    e_start, e_end, i_start, i_end = (int(x) for x in m.groups())
    if str(region).lower() == "exon":
        return chrom, e_start, e_end
    flank = 200
    if region.startswith("flank-"):
        try:
            flank = int(region.split("-")[1])
        except (IndexError, ValueError):
            flank = 200
    return chrom, max(0, e_start - flank), e_end + flank


def _motif_regex(motif: str) -> re.Pattern:
    parts = []
    for ch in motif.upper():
        parts.append("[" + IUPAC.get(ch, ch) + "]")
    return re.compile("".join(parts))


def run_motif(store, job_id: str, parent_id: str, params: dict[str, Any]) -> dict[str, Any]:
    _job, parent_dir, parent_results = _parent_job(store, parent_id)
    parent_config = _job.get("config", {}) or {}
    species = _detect_species(parent_config, parent_results)
    event_type = str(params.get("event_type") or "SE").upper().strip()
    if event_type not in EVENT_TYPES:
        event_type = "SE"
    region = str(params.get("region") or "flank-200").lower().strip()
    if region != "exon" and not re.fullmatch(r"flank-[1-9]\d*", region):
        region = "flank-200"

    ref = REFERENCES.get(species, REFERENCES["mm10"])
    fasta = _Fasta(Path(ref["fasta"]))

    events = _load_sig_events(parent_dir)
    events = [e for e in events if (not event_type or e["type"] == event_type)]

    fg_seqs: list[str] = []
    for ev in events:
        parsed = _parse_coords(ev, region)
        if not parsed:
            continue
        chrom, start, end = parsed
        seq = fasta.fetch(chrom, start, end)
        if seq:
            fg_seqs.append(seq)
    fg_text = "".join(fg_seqs)

    # background: all tested events of this type from the dpsi files
    bg_text_parts: list[str] = []
    foreground_event_ids = {
        event["event_id"] for event in events if event.get("event_id")
    }
    background_event_ids: set[str] = set()
    for path in sorted(parent_dir.rglob("*.dpsi")):
        with _open_text(path) as handle:
            for line in handle:
                if not line.strip():
                    continue
                event_id = _event_id_from_line(line)
                if not event_id or event_id in foreground_event_ids:
                    continue
                if event_id in background_event_ids:
                    continue
                background_event_ids.add(event_id)
                m = EVENT_ID_PATTERN.search(event_id)
                if not m or m.group(1) != event_type:
                    continue
                parsed = _parse_coords({"chrom": m.group(2), "coords": m.group(3)}, region)
                if not parsed:
                    continue
                chrom, start, end = parsed
                seq = fasta.fetch(chrom, start, end)
                if seq:
                    bg_text_parts.append(seq)
    bg_text = "".join(bg_text_parts)

    rows: list[dict[str, Any]] = []
    if fg_text and bg_text:
        for rbp, motif in RBP_MOTIFS:
            rx = _motif_regex(motif)
            a = len(rx.findall(fg_text))
            c = len(rx.findall(bg_text))
            fg_len = max(1, len(fg_text))
            bg_len = max(1, len(bg_text))
            # per-100nt rates as a length-normalised contingency proxy
            fg_rate = a * 1000.0 / fg_len
            bg_rate = c * 1000.0 / bg_len
            rows.append({
                "rbp": rbp, "motif": motif,
                "foreground": a, "background": c,
                "fg_rate": fg_rate, "bg_rate": bg_rate,
                "enrich": (fg_rate + 1e-9) / (bg_rate + 1e-9),
            })
        # rank by enrichment; p-value via Poisson-ish approximation kept simple
        rows.sort(key=lambda r: -r["enrich"])

    out_dir = store.job_dir(job_id) / "output"
    (out_dir / "img").mkdir(parents=True, exist_ok=True)
    fig_rel = f"output/img/motif_{event_type}.png"
    fig_abs = out_dir / "img" / f"motif_{event_type}.png"
    images = []
    try:
        plt = _matplotlib()
        top = rows[:16][::-1]
        if top:
            fig, ax = plt.subplots(figsize=(7.0, max(3.0, 0.34 * len(top) + 1.4)), dpi=150)
            ax.barh([r["rbp"] for r in top], [r["enrich"] for r in top], color="#2f8f6b")
            ax.set_xlabel("enrichment (foreground / background rate)", fontsize=9)
            ax.set_title(f"RBP motif enrichment · {event_type} · {region}", fontsize=10)
            ax.grid(axis="x", linestyle=":", alpha=0.4)
            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)
            fig.tight_layout()
            fig.savefig(fig_abs)
            plt.close(fig)
            images = [{"name": f"motif barplot ({event_type})", "path": fig_rel}]
    except Exception:
        pass

    table = [["rbp", "motif", "foreground", "background", "enrichment"]]
    for r in rows[:30]:
        table.append([r["rbp"], r["motif"], r["foreground"], r["background"], f"{r['enrich']:.3f}"])

    csv_name = f"motif_{event_type}.csv"
    csv_rel = f"output/{csv_name}"
    try:
        with (out_dir / csv_name).open("w", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle).writerows(table)
    except Exception:
        csv_rel = ""

    summary = {
        "Event type": event_type,
        "Region": region,
        "Foreground events": len(fg_seqs),
        "Motifs scanned": len(RBP_MOTIFS),
        "FASTA": "available" if fasta.path.exists() else "missing",
    }
    if not fasta.path.exists():
        summary["Note"] = "参考 FASTA 缺失，motif 扫描未执行"
    elif not bg_text:
        summary["Note"] = "排除前景事件后没有可用背景序列，motif 扫描未执行"
    else:
        summary["Note"] = "motif 结果按序列长度归一化排序，属于探索性富集指标"

    return {
        "module": "motif",
        "job_id": job_id,
        "parent_job_id": parent_id,
        "params": {"event_type": event_type, "region": region},
        "summary": summary,
        "table": table,
        "images": {"downstream": images},
        "files": [p for p in ((fig_rel if images else ""), csv_rel) if p],
    }


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def run_downstream(store, job_id: str) -> None:
    job = store.read(job_id) or {}
    config = job.get("config", {}) or {}
    downstream = config.get("downstream") or {}
    module = str(downstream.get("module", "")).lower()
    parent_id = downstream.get("parent_job_id") or config.get("parent_job_id")
    params = downstream.get("params") or {}

    store.update(job_id, status="running", stage="downstream")
    try:
        if module not in ("enrichment", "motif"):
            raise RuntimeError(f"未知的后续分析模块: {module or '(missing)'}")
        if not parent_id:
            raise RuntimeError("缺少父任务 ID")
        if module == "enrichment":
            results = run_enrichment(store, job_id, parent_id, params)
        else:
            results = run_motif(store, job_id, parent_id, params)

        out = store.job_dir(job_id) / "output"
        out.mkdir(parents=True, exist_ok=True)
        with (out / "results.json").open("w", encoding="utf-8") as handle:
            json.dump(results, handle, ensure_ascii=False, indent=2)
        store.update(job_id, status="completed", stage="done", progress=100)
    except Exception as exc:  # noqa: BLE001
        store.update(job_id, status="failed", error=str(exc), stage="failed")
        (store.job_dir(job_id) / "output").mkdir(parents=True, exist_ok=True)
        (store.job_dir(job_id) / "output" / "downstream_error.txt").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
