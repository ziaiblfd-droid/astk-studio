"""GO-BP follow-up jobs using ASTK's native clusterProfiler workflow."""
from __future__ import annotations

import csv
import gzip
import json
import math
import os
import re
import signal
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

from .planner import filename_token
from .result_parser import load_comparisons, load_plan

ROOT = Path(__file__).resolve().parent.parent
EVENT_TYPES = ("A3", "A5", "AF", "AL", "MX", "RI", "SE")
EVENT_ID_PATTERN = re.compile(r";(A3|A5|AF|AL|MX|RI|SE):")
LENGTH_BREAKS = (1, 51, 251, 1001)


def _open_text(path: Path):
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8-sig", errors="replace")


def _event_id_from_line(line: str) -> str:
    tokens = line.strip().split()
    return tokens[0] if tokens and ";" in tokens[0] and ":" in tokens[0] else ""


def _load_events_file(path: Path | None, expected_type: str = "") -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    events = []
    with _open_text(path) as handle:
        for line in handle:
            columns = line.strip().split()
            event_id = _event_id_from_line(line)
            match = EVENT_ID_PATTERN.search(event_id)
            if not match or (expected_type and match.group(1) != expected_type) or len(columns) < 3:
                continue
            try:
                dpsi, pvalue = float(columns[1]), float(columns[2])
            except ValueError:
                continue
            if not math.isfinite(dpsi) or not math.isfinite(pvalue) or not 0 <= pvalue <= 1:
                continue
            events.append({
                "event_id": event_id, "gene_id": event_id.split(";", 1)[0],
                "type": match.group(1), "dpsi": dpsi, "p_value": pvalue,
            })
    return events


def _safe_token(value: str) -> str:
    return filename_token(str(value))


def _detect_species(config: dict[str, Any], results: dict[str, Any]) -> str:
    for source in (results.get("reference"), config.get("reference"), config.get("species")):
        text = str(source or "").lower()
        if any(token in text for token in ("hg38", "human", "homo")):
            return "hg38"
        if any(token in text for token in ("mm10", "mouse", "mus ")):
            return "mm10"
    raise ValueError("无法识别父任务物种，不能选择正确的 OrgDb")


def _parent_job(store, parent_id: str):
    job = store.read(parent_id)
    if not job or job.get("status") != "completed":
        raise RuntimeError(f"父任务不存在或未完成: {parent_id}")
    directory = store.job_dir(parent_id)
    return job, directory, json.loads((directory / "output/results.json").read_text(encoding="utf-8"))


def _comparison_units(parent_dir: Path) -> list[dict[str, str]]:
    comparisons = load_comparisons(parent_dir, load_plan(parent_dir))
    if not comparisons:
        comparisons = json.loads((parent_dir / "output/results.json").read_text(encoding="utf-8")).get("comparisons", [])
    if not comparisons:
        pattern = re.compile(r"^(.+)_(A3|A5|AF|AL|MX|RI|SE)(?:\.sig)?\.dpsi$")
        groups = set()
        for directory in (parent_dir / "output/analysis/dpsi", parent_dir / "output/analysis/sig01/dpsi", parent_dir / "output/analysis/sig01"):
            for path in directory.glob("*.dpsi"):
                match = pattern.fullmatch(path.name)
                if match:
                    groups.add(match.group(1))
        comparisons = [{"group": group} for group in sorted(groups)]
    units = {}
    for item in comparisons:
        group = str(item["group"])
        if "/" in group or "\\" in group or group in {".", ".."}:
            raise ValueError("Invalid comparison identifier")
        units[group] = {"group": group, "label": str(item.get("label") or group)}
    if not units:
        raise RuntimeError("无法识别父任务比较组")
    return list(units.values())


def _find_event_file(parent_dir: Path, group: str, event_type: str, significant: bool) -> Path | None:
    analysis = parent_dir / "output/analysis"
    directories = (analysis / "sig01/dpsi", analysis / "sig01") if significant else (analysis / "dpsi",)
    suffix = ".sig.dpsi" if significant else ".dpsi"
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


def _cutoff(params: dict[str, Any], *names: str) -> float:
    value = next((params[n] for n in names if params.get(n) not in (None, "")), 0.1)
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError("富集阈值必须是 0 到 1 之间的数值") from None
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("富集阈值必须是 0 到 1 之间的数值")
    return value


def _write_events(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["event_id", "dpsi", "p_value"])
        writer.writerows((e["event_id"], e["dpsi"], e["p_value"]) for e in events)


def _run_native(manifest_path: Path, store, job_id: str) -> dict[str, Any]:
    """Isolate ASTK/R, retaining logs and terminating the entire child tree on timeout."""
    output = manifest_path.parent
    command = [sys.executable, str(ROOT / "backend/native_enrichment.py"), str(manifest_path)]
    timeout = int(os.getenv("ASTK_ENRICHMENT_TIMEOUT", "21600"))
    with (output / "native_enrichment.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, start_new_session=os.name != "nt")
        try:
            elapsed = 0
            while True:
                try:
                    code = process.wait(timeout=2)
                    break
                except subprocess.TimeoutExpired:
                    elapsed += 2
                    try:
                        progress = json.loads((output / "native_progress.json").read_text(encoding="utf-8"))
                        store.update(job_id, stage="astk_enrichment", progress=min(95, 10 + int(85 * progress["done"] / max(1, progress["total"]))))
                    except (OSError, ValueError, KeyError):
                        pass
                    if elapsed >= timeout:
                        raise TimeoutError("ASTK 富集分析超时")
        except BaseException:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait()
            raise
    if code:
        detail = (output / "native_enrichment.log").read_text(encoding="utf-8", errors="replace")[-2000:]
        raise RuntimeError(f"ASTK 富集分析失败，请检查 native_enrichment.log\n{detail}")
    return json.loads((output / "native_results.json").read_text(encoding="utf-8"))


def run_enrichment(store, job_id: str, parent_id: str, params: dict[str, Any]) -> dict[str, Any]:
    database = str(params.get("database") or params.get("db") or "GO_BP").upper()
    if database != "GO_BP":
        raise ValueError("当前仅支持 GO Biological Process (BP)")
    mode = str(params.get("mode") or "ora").strip().lower()
    if mode not in {"ora", "compare"}:
        raise ValueError("Unsupported enrichment mode")
    gene_set = str(params.get("gene_set") or "significant").strip().lower()
    if gene_set not in {"significant", "up", "down"}:
        raise ValueError("Unsupported enrichment gene set")
    pvalue, qvalue = _cutoff(params, "pvalue", "pval"), _cutoff(params, "qvalue", "qval")
    job, parent, results = _parent_job(store, parent_id)
    config = job.get("config") or {}
    species = _detect_species(config, results)
    plan = load_plan(parent)
    units = _comparison_units(parent)
    output = store.job_dir(job_id) / "output"
    output.mkdir(parents=True, exist_ok=True)
    cells = []
    for unit in units:
        for kind in EVENT_TYPES:
            significant = _find_event_file(parent, unit["group"], kind, True)
            background = _find_event_file(parent, unit["group"], kind, False)
            missing = significant is None and background is None
            if significant is not None:
                events = _load_events_file(significant, kind)
            else:
                base_p = float(plan.get("p_value", config.get("p_value", 0.05)))
                base_dpsi = float(plan.get("abs_dpsi", config.get("abs_dpsi", 0.1)))
                events = [e for e in _load_events_file(background, kind) if e["p_value"] < base_p and abs(e["dpsi"]) > base_dpsi]
            events = [e for e in events if gene_set == "significant" or (e["dpsi"] > 0 if gene_set == "up" else e["dpsi"] < 0)]
            key = f"{_safe_token(unit['group'])}_{kind}"
            input_path = output / "native_inputs" / f"{key}.sig.dpsi"
            _write_events(input_path, events)
            cells.append({
                "group": unit["group"], "comparison": unit["label"], "event_type": kind,
                "key": key, "input": str(input_path.resolve()),
                "input_genes": len({e["gene_id"].split(".", 1)[0] for e in events}),
                "input_events": len(events), "missing": missing,
                "source": "significant_file" if significant is not None else "derived_from_dpsi",
            })
    if all(c["missing"] for c in cells):
        raise RuntimeError("缺少所有比较组的 dPSI / sig.dPSI 输入文件")
    manifest = {
        "mode": mode, "species": species, "ontology": "BP", "pvalue": pvalue, "qvalue": qvalue,
        "length_breaks": list(LENGTH_BREAKS), "simple": True,
        "cells": cells, "output": str(output.resolve()),
    }
    manifest_path = output / "native_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    store.update(job_id, stage="astk_enrichment", progress=5)
    native = _run_native(manifest_path, store, job_id)
    images, files, aggregate = [], [], []
    for cell in native["units"]:
        for relative in cell["images"]:
            path = output / relative
            with path.open("rb") as handle:
                if handle.read(8) != b"\x89PNG\r\n\x1a\n":
                    raise RuntimeError(f"ASTK 返回的图片不是有效 PNG: {relative}")
            images.append({
                "name": f"{cell['comparison']} · {cell['event_type']}" + (" · GO clusters" if "/simgo/" in relative else ""),
                "path": "output/" + relative, "comparison": cell["group"],
                "event_type": cell["event_type"], "kind": "clusters" if "/simgo/" in relative else mode,
                "status": cell["status"],
            })
        files.extend("output/" + p for p in cell["files"])
        for relative in cell["tables"]:
            with (output / relative).open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    aggregate.append({"comparison": cell["comparison"], "event_type": cell["event_type"], **{k: v for k, v in row.items() if k}})
    aggregate_path = output / ("enrichment_GO_BP.csv" if mode == "ora" else "enrichment_compare/GO_BP/comparison.csv")
    aggregate_path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(dict.fromkeys(["comparison", "event_type"] + [k for row in aggregate for k in row]))
    with aggregate_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(aggregate)
    files.append("output/" + aggregate_path.relative_to(output).as_posix())
    files.extend(["output/native_manifest.json", "output/native_enrichment.log", "output/native_results.json"])
    return {
        "module": "enrichment", "mode": mode, "job_id": job_id, "parent_job_id": parent_id,
        "params": {"mode": mode, "database": "GO_BP", "gene_set": gene_set, "pvalue": pvalue, "qvalue": qvalue},
        "summary": {
            "Database": "GO Biological Process", "Engine": "ASTK / clusterProfiler",
            "Species": species, "Comparisons": len(units), "AS event types": len(EVENT_TYPES),
            "Expected primary plots": len(cells), "Generated plots": len(images),
            "Missing input pairs": sum(c["missing"] for c in cells),
            "p / q cutoff": f"{pvalue:g} / {qvalue:g}",
            "Comparison basis": "ASTK length clusters (1, 51, 251, 1001)" if mode == "compare" else "OrgDb BP universe",
        },
        "provenance": native.get("provenance", {}), "units": native["units"],
        "images": {mode: images}, "files": list(dict.fromkeys(files)), "table": [],
    }


def run_downstream(store, job_id: str) -> None:
    job = store.read(job_id) or {}
    config = job.get("config") or {}
    downstream = config.get("downstream") or {}
    store.update(job_id, status="running", stage="downstream")
    try:
        if downstream.get("module") != "enrichment":
            raise RuntimeError("未知的后续分析模块")
        parent_id = downstream.get("parent_job_id") or config.get("parent_job_id")
        if not parent_id:
            raise RuntimeError("缺少父任务 ID")
        results = run_enrichment(store, job_id, parent_id, downstream.get("params") or {})
        output = store.job_dir(job_id) / "output"
        (output / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        store.update(job_id, status="completed", stage="done", progress=100)
    except Exception as exc:
        output = store.job_dir(job_id) / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / "downstream_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        store.update(job_id, status="failed", error=str(exc), stage="failed")
