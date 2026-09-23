from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any


STUDIO_COLUMNS = {"sample_id", "condition", "quant_path", "baseline"}
ASTK_COLUMNS = {"group", "condition", "name", "path", "replicate"}
ASTK_CONDITIONS = {"ctrl", "case"}
TRUTHY = {"1", "true", "yes", "y", "baseline", "control"}
DEFAULT_REFERENCES = {
    "Mus musculus · mm10": {
        "id": "mm10-gencode-m25",
        "gtf": "/refs/mm10/gencode.vM25.annotation.gtf",
        "fasta": "/refs/mm10/GRCm38.primary_assembly.genome.fa",
    },
    "Homo sapiens · hg38": {
        "id": "hg38-gencode-v44",
        "gtf": "/refs/hg38/gencode.v44.annotation.gtf",
        "fasta": "/refs/hg38/GRCh38.primary_assembly.genome.fa",
    },
}

REFERENCE_FILES = {
    "Mus musculus · mm10": ("mm10", "gencode.vM25.annotation.gtf"),
    "Homo sapiens · hg38": ("hg38", "gencode.v44.annotation.gtf"),
}
REFERENCE_ROOTS = (Path("/refs"), Path(__file__).resolve().parent.parent / "references")
SUPPA_ROOT = Path(__file__).resolve().parent.parent / "vendor" / "suppa2"


class InputError(ValueError):
    pass


def slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_")
    return normalized or "group"


def filename_token(value: str) -> str:
    """Return a stable, filesystem-safe comparison identifier."""
    original = value.strip()
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", original).strip("._")
    if not normalized:
        normalized = "group"
    if normalized != original:
        digest = hashlib.sha1(original.encode("utf-8")).hexdigest()[:8]
        normalized = f"{normalized}_{digest}"
    return normalized


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
    if mm10_fasta := os.getenv("ASTK_MM10_FASTA"):
        references["Mus musculus · mm10"]["fasta"] = mm10_fasta
    if hg38_fasta := os.getenv("ASTK_HG38_FASTA"):
        references["Homo sapiens · hg38"]["fasta"] = hg38_fasta
    for species, (species_dir, filename) in REFERENCE_FILES.items():
        configured = references.get(species, {}).get("gtf", "")
        if configured and Path(configured).exists():
            continue
        for root in REFERENCE_ROOTS:
            candidate = root / species_dir / filename
            if candidate.exists():
                references.setdefault(species, {})["gtf"] = str(candidate)
                break
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


def find_sample_sheet(job_dir: Path) -> Path:
    input_dir = job_dir / "input"
    candidates = sorted(
        path for path in input_dir.iterdir()
        if path.is_file() and path.name.lower().endswith(".csv")
    )
    if not candidates:
        raise InputError("Missing CSV sample table")
    if len(candidates) > 1:
        names = ", ".join(path.name for path in candidates)
        raise InputError(f"Multiple CSV sample tables were found: {names}")
    return candidates[0]


def read_sample_columns(job_dir: Path) -> set[str]:
    path = find_sample_sheet(job_dir)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return set(csv.DictReader(handle).fieldnames or [])


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
    data_dir = job_dir / "input" / "data"
    candidates = [data_dir / clean, job_dir / "input" / clean]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    if len(clean.parts) >= 2:
        requested_sample = clean.parts[-2]
        matches = sorted(
            path for path in data_dir.rglob(clean.name)
            if path.is_file() and path.parent.name == requested_sample
        )
        if len(matches) == 1:
            return matches[0].resolve()
        if len(matches) > 1:
            raise InputError(f"quant_path is ambiguous in the uploaded data: {relative}")
    raise InputError(f"quant_path was not found in the uploaded data: {relative}")


def read_samples(job_dir: Path) -> list[dict[str, Any]]:
    path = find_sample_sheet(job_dir)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = STUDIO_COLUMNS - columns
        if missing:
            raise InputError(f"CSV sample table is missing columns: {', '.join(sorted(missing))}")
        rows = []
        seen_samples: dict[str, tuple[str, Path, bool]] = {}
        for line_number, row in enumerate(reader, 2):
            sample_id = row["sample_id"].strip()
            condition = row["condition"].strip()
            quant_path = row["quant_path"].strip()
            if not sample_id or not condition or not quant_path:
                raise InputError(f"CSV sample table line {line_number} has empty required values")
            resolved = resolve_quant_path(job_dir, quant_path)
            validate_quant_file(resolved)
            order_text = (row.get("order") or "").strip()
            baseline = row["baseline"].strip().lower() in TRUTHY
            signature = (condition, resolved, baseline)
            previous = seen_samples.get(sample_id)
            if previous is not None:
                if previous == signature:
                    continue
                raise InputError(f"Conflicting duplicate sample_id: {sample_id}")
            seen_samples[sample_id] = signature
            rows.append(
                {
                    "sample_id": sample_id,
                    "condition": condition,
                    "quant_path": resolved,
                    "baseline": baseline,
                    "order": int(order_text) if order_text else None,
                }
            )
    if len(rows) < 2:
        raise InputError("At least two samples are required")
    return rows


def read_astk_samples(job_dir: Path) -> dict[str, dict[str, list[dict[str, Any]]]]:
    path = find_sample_sheet(job_dir)
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    seen: set[tuple[str, str, str]] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = ASTK_COLUMNS - columns
        if missing:
            raise InputError(f"CSV sample table is missing columns: {', '.join(sorted(missing))}")
        for line_number, row in enumerate(reader, 2):
            group = row["group"].strip()
            condition = row["condition"].strip().lower()
            name = row["name"].strip()
            source_path = row["path"].strip()
            replicate_text = row["replicate"].strip()
            if not group or not condition or not name or not source_path or not replicate_text:
                raise InputError(f"CSV sample table line {line_number} has empty required values")
            if condition not in ASTK_CONDITIONS:
                raise InputError(f"CSV sample table line {line_number} condition must be ctrl or case")
            try:
                replicate = int(replicate_text)
            except ValueError as error:
                raise InputError(f"CSV sample table line {line_number} has an invalid replicate") from error
            if replicate < 1:
                raise InputError(f"CSV sample table line {line_number} replicate must be at least 1")
            key = (group, condition, name)
            if key in seen:
                raise InputError(f"Duplicate sample in group {group}: {condition}/{name}")
            seen.add(key)
            resolved = resolve_quant_path(job_dir, source_path)
            validate_quant_file(resolved)
            roles = groups.setdefault(group, {"ctrl": [], "case": []})
            roles[condition].append({"name": name, "replicate": replicate, "path": resolved})
    if not groups:
        raise InputError("At least one ASTK comparison group is required")
    for group, roles in groups.items():
        for condition in ASTK_CONDITIONS:
            samples = roles[condition]
            if not samples:
                raise InputError(f"ASTK group {group} must include both ctrl and case samples")
            replicates = [sample["replicate"] for sample in samples]
            if len(replicates) != len(set(replicates)):
                raise InputError(f"Duplicate replicate number in {group}/{condition}")
            samples.sort(key=lambda sample: sample["replicate"])
    return groups


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


def sample_stage_label(name: str) -> str:
    value = re.sub(r"(?i)(?:[._-]?(?:rep|replicate)[._-]?\d+)$", "", name.strip())
    value = re.sub(r"(?i)^(?:facial|face|stage|timepoint|sample)[._-]*", "", value)
    match = re.search(r"(\d+(?:[._]\d+)?)", value)
    if match:
        return match.group(1).replace("_", ".")
    return value or name.strip()


def infer_sample_group_label(samples: Any) -> str:
    if isinstance(samples, dict):
        samples = samples.get("samples", [])
    if not isinstance(samples, list):
        return ""
    labels = list(
        dict.fromkeys(
            sample_stage_label(sample.get("name", "") if isinstance(sample, dict) else str(sample))
            for sample in samples
        )
    )
    labels = [label for label in labels if label]
    return " / ".join(labels)


def native_comparison_label(
    group: str,
    roles: dict[str, list[dict[str, Any]]] | None = None,
) -> tuple[str, str, str]:
    if "_vs_" in group:
        control, treatment = group.split("_vs_", 1)
        if control and treatment:
            return control, treatment, f"{control} → {treatment}"
    if roles:
        control = infer_sample_group_label(roles.get("ctrl", []))
        treatment = infer_sample_group_label(roles.get("case", []))
        if control and treatment:
            return control, treatment, f"{control} → {treatment}"
    return "ctrl", "case", group


def write_astk_metadata(
    job_dir: Path, groups: dict[str, dict[str, list[dict[str, Any]]]]
) -> tuple[Path, Path, list[dict[str, str]]]:
    metadata_dir = job_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {}
    csv_rows: list[dict[str, Any]] = []
    comparisons: list[dict[str, str]] = []
    used_group_ids: set[str] = set()
    for raw_group, roles in groups.items():
        group = filename_token(raw_group)
        if group in used_group_ids:
            suffix = hashlib.sha1(raw_group.encode("utf-8")).hexdigest()[:8]
            group = f"{group}_{suffix}"
        used_group_ids.add(group)
        payload[group] = {"ctrl": {"samples": []}, "case": {"samples": []}}
        control, treatment, label = native_comparison_label(raw_group, roles)
        comparisons.append({"group": group, "control": control, "treatment": treatment, "label": label})
        for condition in ("ctrl", "case"):
            for sample in roles[condition]:
                item = {
                    "name": sample["name"],
                    "replicate": sample["replicate"],
                    "path": relative_job_path(job_dir, sample["path"]),
                }
                payload[group][condition]["samples"].append(item)
                csv_rows.append({"group": group, "condition": condition, **item})
    json_path = metadata_dir / "astk_metadata.json"
    csv_path = metadata_dir / "astk_metadata.csv"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["group", "condition", "name", "path", "replicate"])
        writer.writeheader()
        writer.writerows(csv_rows)
    return json_path, csv_path, comparisons


def prepare_job(job_dir: Path, require_reference: bool = False) -> dict[str, Any]:
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    config = job["config"]
    prepare_input_tree(job_dir)
    columns = read_sample_columns(job_dir)
    native_astk_input = ASTK_COLUMNS.issubset(columns)
    if native_astk_input:
        groups = read_astk_samples(job_dir)
        if os.getenv("ASTK_REQUIRE_EQUAL_REPLICATES", "0").lower() in TRUTHY:
            unequal = [
                group for group, roles in groups.items()
                if len(roles["ctrl"]) != len(roles["case"])
            ]
            if unequal:
                raise InputError(
                    "This ASTK installation requires equal replicate counts: " + ", ".join(unequal)
                )
        metadata_json, metadata_csv, plan_comparisons = write_astk_metadata(job_dir, groups)
        sample_count = len({sample["name"] for roles in groups.values() for samples in roles.values() for sample in samples})
    else:
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
        plan_comparisons = [
            {"group": f"{slug(control)}_vs_{slug(treatment)}", "control": control, "treatment": treatment,
             "label": f"{control} → {treatment}"}
            for control, treatment in comparisons
        ]
        sample_count = len(samples)
    references = load_references()
    species = config.get("species")
    if species not in references:
        raise InputError(f"Unsupported reference: {species}")
    reference = references[species]
    gtf = Path(reference["gtf"])
    if require_reference and not gtf.exists():
        raise InputError(f"Reference GTF does not exist: {gtf}")
    sequence_features = bool(config.get("sequence_features", False))
    psi_high_threshold = float(config.get("psi_high_threshold", 0.8))
    psi_low_threshold = float(config.get("psi_low_threshold", 0.2))
    if not 0 <= psi_low_threshold < psi_high_threshold <= 1:
        raise InputError("PSI thresholds must satisfy 0 <= low < high <= 1")
    fasta_value = str(reference.get("fasta", "")).strip()
    if sequence_features and not fasta_value:
        raise InputError(
            f"Sequence feature analysis requires a FASTA reference for {species}; "
            "configure ASTK_MM10_FASTA or ASTK_HG38_FASTA"
        )
    if sequence_features and not Path(fasta_value).exists():
        raise InputError(
            f"Sequence feature FASTA does not exist: {fasta_value}. "
            "Configure ASTK_MM10_FASTA or ASTK_HG38_FASTA on the server."
        )
    output_dir = job_dir / "output" / "analysis"
    suppa_command = os.getenv("SUPPA_COMMAND", str(SUPPA_ROOT / "eventGenerator.py"))
    command = [
        os.getenv("SUPPA_PYTHON") or os.getenv("PYTHON_COMMAND") or "python3",
        suppa_command,
        "-i", reference["gtf"],
        "-o", relative_job_path(job_dir, output_dir / "events" / "events"),
        "-f", "ioe",
        "-e", "SE", "SS", "MX", "RI", "FL",
        "-b", "S",
    ]
    plan = {
        "version": 1,
        "engine": "suppa2",
        "species": species,
        "reference": reference,
        "input_format": "astk" if native_astk_input else "studio",
        "sample_count": sample_count,
        "p_value": float(config.get("p_value", 0.05)),
        "abs_dpsi": float(config.get("abs_dpsi", 0.0)),
        "method": str(config.get("method", "empirical")),
        "sequence_features": sequence_features,
        "psi_high_threshold": psi_high_threshold,
        "psi_low_threshold": psi_low_threshold,
        "comparisons": plan_comparisons,
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
