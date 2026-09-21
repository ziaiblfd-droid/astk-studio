from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from .planner import InputError, prepare_job
from .native_astk import run_native_astk, select_engine
from .result_parser import parse_results
from .visualization import generate_visualizations


EVENT_TYPES = ("A3", "A5", "AF", "AL", "MX", "RI", "SE")
SUPPA_ROOT = Path(__file__).resolve().parent.parent / "vendor" / "suppa2"


class SuppaRunner:
    def __init__(self, job_dir: Path) -> None:
        self.job_dir = job_dir
        self.lines: list[str] = []

    def run(self, script: str, arguments: list[str], log_path: Path) -> None:
        command = [
            *runtime_command(),
            str(SUPPA_ROOT / script),
            *[str(argument) for argument in arguments],
        ]
        self.lines.append(f"$ {shlex.join(command)}")
        process = subprocess.run(
            command,
            cwd=self.job_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if process.stdout.strip():
            self.lines.append(process.stdout.rstrip())
        if process.stderr.strip():
            self.lines.append(process.stderr.rstrip())
        log_path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        if process.returncode != 0:
            detail = (process.stderr or process.stdout or "").strip().splitlines()
            suffix = f": {detail[-1]}" if detail else ""
            raise RuntimeError(f"{script} exited with code {process.returncode}{suffix}")

    def append(self, message: str, log_path: Path) -> None:
        self.lines.append(message)
        log_path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def runtime_command() -> list[str]:
    configured = os.getenv("SUPPA_PYTHON") or os.getenv("PYTHON_COMMAND") or sys.executable
    return shlex.split(configured, posix=os.name != "nt")


def load_metadata(job_dir: Path, plan: dict[str, Any]) -> dict[str, Any]:
    path = job_dir / plan["metadata_json"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise InputError("Generated metadata is invalid")
    return payload


def resolve_sample_path(job_dir: Path, relative: str) -> Path:
    path = (job_dir / relative).resolve()
    if job_dir.resolve() not in path.parents or not path.is_file():
        raise InputError(f"Sample quant.sf is missing from the job: {relative}")
    return path


def read_tpm(path: Path) -> dict[str, float]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"Name", "TPM"}
        if not required.issubset(reader.fieldnames or []):
            raise InputError(f"Invalid Salmon quant.sf: {path}")
        values: dict[str, float] = {}
        for row in reader:
            transcript = (row.get("Name") or "").strip()
            if not transcript:
                continue
            try:
                value = float(row.get("TPM") or 0)
            except ValueError as error:
                raise InputError(f"Invalid TPM value in {path} for {transcript}") from error
            values[transcript] = max(0.0, value)
    if not values:
        raise InputError(f"No transcript TPM values were found in {path}")
    return values


def unique_sample_name(name: str, used: set[str]) -> str:
    base = name.strip() or "sample"
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def sample_rows(job_dir: Path, samples: list[dict[str, Any]]) -> list[tuple[str, Path]]:
    used: set[str] = set()
    rows: list[tuple[str, Path]] = []
    for sample in samples:
        name = unique_sample_name(str(sample.get("name") or "sample"), used)
        path = resolve_sample_path(job_dir, str(sample["path"]))
        rows.append((name, path))
    return rows


def write_expression_matrix(path: Path, samples: list[tuple[str, Path]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = [name for name, _ in samples]
    expression = [read_tpm(sample_path) for _, sample_path in samples]
    transcripts = sorted(set().union(*(values.keys() for values in expression)))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(names)
        for transcript in transcripts:
            writer.writerow(
                [transcript, *[f"{values.get(transcript, 0.0):.10g}" for values in expression]]
            )


def validate_group(method: str, group: str, roles: dict[str, Any]) -> None:
    if method != "empirical":
        return
    counts = {
        role: len(roles.get(role, {}).get("samples", []))
        for role in ("ctrl", "case")
    }
    if counts["ctrl"] < 2 or counts["case"] < 2:
        raise InputError(
            f"Group {group} needs at least two ctrl and two case replicates "
            "for SUPPA empirical differential analysis"
        )


def execute(job_dir: Path) -> None:
    plan = prepare_job(job_dir, require_reference=True)
    analysis_dir = job_dir / "output" / "analysis"
    events_dir = analysis_dir / "events"
    expression_dir = analysis_dir / "expression"
    psi_dir = analysis_dir / "psi"
    dpsi_dir = analysis_dir / "dpsi"
    for directory in (events_dir, expression_dir, psi_dir, dpsi_dir):
        directory.mkdir(parents=True, exist_ok=True)

    runner = SuppaRunner(job_dir)
    log_path = job_dir / "output" / "runner.log"
    metadata = load_metadata(job_dir, plan)
    method = str(plan.get("method", "empirical")).lower()
    if method not in {"empirical", "classical"}:
        raise InputError(f"Unsupported differential splicing method: {method}")

    engine = select_engine(job_dir, metadata)
    if engine == "astk":
        for message in run_native_astk(job_dir, plan, metadata):
            runner.append(message, log_path)
    else:
        runner.append("=== PORTABLE SUPPA2 ENGINE ===", log_path)
        runner.run(
            "eventGenerator.py",
            [
                "-i", plan["reference"]["gtf"],
                "-o", events_dir / "events",
                "-f", "ioe",
                "-e", "SE", "SS", "MX", "RI", "FL",
                "-b", "S",
                "-m", "WARNING",
            ],
            log_path,
        )

        for comparison in plan["comparisons"]:
            group = comparison["group"]
            roles = metadata.get(group)
            if not isinstance(roles, dict):
                raise InputError(f"Missing metadata for comparison group: {group}")
            validate_group(method, group, roles)

            expressions: dict[str, Path] = {}
            for role, suffix in (("ctrl", "c1"), ("case", "c2")):
                samples = roles.get(role, {}).get("samples", [])
                expression_path = expression_dir / f"{group}_{role}.tsv"
                write_expression_matrix(expression_path, sample_rows(job_dir, samples))
                expressions[role] = expression_path

            for kind in EVENT_TYPES:
                ioe_path = events_dir / f"events_{kind}_strict.ioe"
                if not ioe_path.exists():
                    continue
                psi_paths: dict[str, Path] = {}
                for role, suffix in (("ctrl", "c1"), ("case", "c2")):
                    psi_prefix = psi_dir / f"{group}_{kind}_{suffix}"
                    runner.run(
                        "psiCalculator.py",
                        [
                            "-i", ioe_path,
                            "-e", expressions[role],
                            "-o", psi_prefix,
                            "-m", "WARNING",
                        ],
                        log_path,
                    )
                    psi_paths[role] = Path(f"{psi_prefix}.psi")
                    if not psi_paths[role].exists():
                        raise RuntimeError(f"SUPPA did not create {psi_paths[role]}")

                dpsi_prefix = dpsi_dir / f"{group}_{kind}"
                arguments = [
                    "-m", method,
                    "-i", ioe_path,
                    "-p", psi_paths["ctrl"], psi_paths["case"],
                    "-e", expressions["ctrl"], expressions["case"],
                    "-l", str(plan["abs_dpsi"]),
                    "-o", dpsi_prefix,
                    "-mo", "WARNING",
                ]
                runner.run("significanceCalculator.py", arguments, log_path)
                dpsi_path = Path(f"{dpsi_prefix}.dpsi")
                if not dpsi_path.exists():
                    raise RuntimeError(f"SUPPA did not create {dpsi_path}")
                psivec_path = Path(f"{dpsi_prefix}.psivec")
                if psivec_path.exists():
                    psivec_path.unlink()

    runner.append("=== VISUALIZATION ===", log_path)
    plot_log = generate_visualizations(job_dir, plan)
    if plot_log:
        runner.lines.append(plot_log)
        log_path.write_text("\n".join(runner.lines) + "\n", encoding="utf-8")
    parse_results(job_dir, Path(plan["reference"]["gtf"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute an SUPPA2-based ASTK Studio job")
    parser.add_argument("job_dir", type=Path)
    args = parser.parse_args()
    execute(args.job_dir.resolve())


if __name__ == "__main__":
    main()
