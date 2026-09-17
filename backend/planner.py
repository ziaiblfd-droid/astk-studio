from __future__ import annotations

import argparse
import csv
import json
import os
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = {"sample_id", "condition", "quant_path", "baseline"}
TRUTHY = {"1", "true", "yes", "y", "baseline", "control"}
DEFAULT_REFERENCES = {
    "Mus musculus · mm10": {
        "id": "mm10-gencode-m25",
        "gtf": "/refs/mm10/gencode.vM25.annotation.gtf",
    },
    "Homo sapiens · hg38": {
        "id": "hg38-gencode-v44",
        "gtf": "/refs/hg38/gencode.v44.annotation.gtf",
    },
}


class InputError(ValueError):
    pass


def slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_")
    return normalized or "group"


def load_references() -> dict[str, dict[str, str]]:
    custom = os.getenv("ASTK_REFERENCE_CONFIG")
    if custom:
        path = Path(custom)
        if not path.exists():
            raise InputError(f"Reference configuration does not exist: {path}")
        references = json.loads(path.read_text(encoding="utf-8"))
    else:
        references = {name: dict(value) for name, value in DEFAULT_REFERENCES.items()}
    if mm10_gtf := os.getenv("ASTK_MM10_GTF"):
        references["Mus musculus · mm10"]["gtf"] = mm10_gtf
    if hg38_gtf := os.getenv("ASTK_HG38_GTF"):
        references["Homo sapiens · hg38"]["gtf"] = hg38_gtf
    return references


def safe_extract_zip(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            if member.is_dir():
                continue
            target = (destination / member.filename).resolve()
            if destination_root not in target.parents:
                raise InputError(f"Unsafe path in ZIP: {member.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, target.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)


def prepare_input_tree(job_dir: Path) -> None:
    input_dir = job_dir / "input"
    data_dir = input_dir / "data"
    archives = sorted(input_dir.glob("*.zip"))
    for archive in archives:
        safe_extract_zip(archive, data_dir)


def find_samples_csv(job_dir: Path) -> Path:
    candidates = sorted((job_dir / "input").rglob("samples.csv"))
    if not candidates:
        raise InputError("Missing samples.csv")
    if len(candidates) > 1:
        raise InputError("Multiple samples.csv files were found")
    return candidates[0]


def validate_quant_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        raise InputError(f"quant.sf does not exist: {path}")
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        header = handle.readline().strip().split("\t")
    expected = {"Name", "Length", "EffectiveLength", "TPM", "NumReads"}
    if not expected.issubset(set(header)):
        raise InputError(f"Invalid Salmon quant.sf header: {path}")


def resolve_quant_path(job_dir: Path, relative: str) -> Path:
    clean = Path(relative.replace("\\", "/"))
    if clean.is_absolute() or ".." in clean.parts:
        raise InputError(f"quant_path must be relative: {relative}")
    candidates = [job_dir / "input" / "data" / clean, job_dir / "input" / clean]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise InputError(f"quant_path was not found in the uploaded data: {relative}")


def read_samples(job_dir: Path) -> list[dict[str, Any]]:
    path = find_samples_csv(job_dir)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise InputError(f"samples.csv is missing columns: {', '.join(sorted(missing))}")
        rows = []
        seen_ids: set[str] = set()
        for line_number, row in enumerate(reader, 2):
            sample_id = row["sample_id"].strip()
            condition = row["condition"].strip()
            quant_path = row["quant_path"].strip()
            if not sample_id or not condition or not quant_path:
                raise InputError(f"samples.csv line {line_number} has empty required values")
            if sample_id in seen_ids:
                raise InputError(f"Duplicate sample_id: {sample_id}")
            seen_ids.add(sample_id)
            resolved = resolve_quant_path(job_dir, quant_path)
            validate_quant_file(resolved)
            order_text = (row.get("order") or "").strip()
            rows.append(
                {
                    "sample_id": sample_id,
                    "condition": condition,
                    "quant_path": resolved,
                    "baseline": row["baseline"].strip().lower() in TRUTHY,
                    "order": int(order_text) if order_text else None,
                }
            )
    if len(rows) < 2:
        raise InputError("At least two samples are required")
    return rows


def make_comparisons(samples: list[dict[str, Any]], mode: str = "baseline") -> list[tuple[str, str]]:
    conditions = list(dict.fromkeys(row["condition"] for row in samples))
    if len(conditions) < 2:
        raise InputError("At least two conditions are required")
    baseline_conditions = {row["condition"] for row in samples if row["baseline"]}
    if mode == "adjacent":
        order_by_condition: dict[str, int] = {}
        for condition in conditions:
            values = {row["order"] for row in samples if row["condition"] == condition and row["order"] is not None}
            if len(values) != 1:
                raise InputError("Adjacent comparisons require one consistent order value per condition")
            order_by_condition[condition] = values.pop()
        ordered = sorted(conditions, key=order_by_condition.get)
        return list(zip(ordered, ordered[1:]))
    if len(baseline_conditions) != 1:
        raise InputError("Exactly one baseline condition must be marked in samples.csv")
    baseline = next(iter(baseline_conditions))
    return [(baseline, condition) for condition in conditions if condition != baseline]


def relative_job_path(job_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(job_dir.resolve()).as_posix()


def write_metadata(job_dir: Path, samples: list[dict[str, Any]], comparisons: list[tuple[str, str]]) -> tuple[Path, Path]:
    metadata_dir = job_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in samples:
        grouped[row["condition"]].append(row)
    payload: dict[str, Any] = {}
    csv_rows: list[dict[str, Any]] = []
    for control, treatment in comparisons:
        group_name = f"{slug(control)}_vs_{slug(treatment)}"
        payload[group_name] = {"ctrl": {"samples": []}, "case": {"samples": []}}
        for role, condition in (("ctrl", control), ("case", treatment)):
            for replicate, sample in enumerate(grouped[condition], 1):
                item = {
                    "name": sample["sample_id"],
                    "replicate": replicate,
                    "path": relative_job_path(job_dir, sample["quant_path"]),
                }
                payload[group_name][role]["samples"].append(item)
                csv_rows.append({"group": group_name, "condition": role, **item})
    json_path = metadata_dir / "astk_metadata.json"
    csv_path = metadata_dir / "astk_metadata.csv"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["group", "condition", "replicate", "name", "path"])
        writer.writeheader()
        writer.writerows(csv_rows)
    return json_path, csv_path


def prepare_job(job_dir: Path, require_reference: bool = False) -> dict[str, Any]:
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    config = job["config"]
    prepare_input_tree(job_dir)
    samples = read_samples(job_dir)
    mode = config.get("comparison_mode", "baseline")
    comparisons = make_comparisons(samples, mode)
    if os.getenv("ASTK_REQUIRE_EQUAL_REPLICATES", "0").lower() in TRUTHY:
        counts = defaultdict(int)
        for sample in samples:
            counts[sample["condition"]] += 1
        unequal = [(control, treatment) for control, treatment in comparisons if counts[control] != counts[treatment]]
        if unequal:
            pairs = ", ".join(f"{control} vs {treatment}" for control, treatment in unequal)
            raise InputError(f"This ASTK installation requires equal replicate counts: {pairs}")
    metadata_json, metadata_csv = write_metadata(job_dir, samples, comparisons)
    references = load_references()
    species = config.get("species")
    if species not in references:
        raise InputError(f"Unsupported reference: {species}")
    reference = references[species]
    gtf = Path(reference["gtf"])
    if require_reference and not gtf.exists():
        raise InputError(f"Reference GTF does not exist: {gtf}")
    output_dir = job_dir / "output" / "analysis"
    command = [
        "astk", "dsflow",
        "-od", relative_job_path(job_dir, output_dir),
        "-md", relative_job_path(job_dir, metadata_json),
        "-gtf", reference["gtf"],
        "-et", config.get("event_type", "ALL"),
        "-m", config.get("method", "empirical"),
        "-p", str(config.get("p_value", 0.05)),
        "-adpsi", str(config.get("abs_dpsi", 0.1)),
    ]
    plan = {
        "version": 1,
        "species": species,
        "reference": reference,
        "sample_count": len(samples),
        "comparisons": [
            {"group": f"{slug(c)}_vs_{slug(t)}", "control": c, "treatment": t}
            for c, t in comparisons
        ],
        "metadata_json": relative_job_path(job_dir, metadata_json),
        "metadata_csv": relative_job_path(job_dir, metadata_csv),
        "command": command,
    }
    plan_path = job_dir / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare an ASTK Studio job")
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--require-reference", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare_job(args.job_dir.resolve(), args.require_reference), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
