from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

from .planner import prepare_job
from .store import JobStore


DEMO_EVENTS = [
    ["ENSMUSG00000025900.13;SE:chr1:4293012-4311270", "Ttn", "SE", "E11.5 -> E16.5", "0.82", "+0.46", "2.1e-08"],
    ["ENSMUSG00000033845.7;AF:chr7:127883-130112", "Mef2c", "AF", "E11.5 -> E16.5", "0.18", "-0.39", "8.4e-07"],
    ["ENSMUSG00000067274.6;RI:chr5:991233-994814", "Ryr2", "RI", "E12.5 -> P0", "0.67", "+0.34", "1.7e-05"],
    ["ENSMUSG00000037742.8;A3:chr9:214221-216087", "Actc1", "A3", "E11.5 -> E13.5", "0.41", "-0.31", "3.2e-05"],
    ["ENSMUSG00000029661.12;SE:chr2:663102-667720", "Nrxn1", "SE", "E13.5 -> E16.5", "0.75", "+0.29", "6.8e-05"],
    ["ENSMUSG00000022514.10;AL:chr8:772891-776230", "Pkm", "AL", "E11.5 -> P0", "0.29", "-0.28", "9.4e-05"],
    ["ENSMUSG00000022454.14;A5:chr11:401992-405381", "Srsf3", "A5", "E12.5 -> E15.5", "0.63", "+0.25", "1.2e-04"],
    ["ENSMUSG00000020186.9;MX:chr3:918221-923145", "Mbnl1", "MX", "E13.5 -> E16.5", "0.52", "-0.22", "2.7e-04"],
]

STAGES = [
    ("Input validation", 12),
    ("Metadata generation", 26),
    ("Seven-class event generation", 48),
    ("PSI quantification", 68),
    ("Differential splicing", 88),
    ("Report generation", 100),
]


def _write_results(job_dir: Path, config: dict[str, Any]) -> None:
    sample_count = 6 if config.get("demo") else max(1, int(config.get("sample_count", len(config.get("files", [])))))
    results = {
        "metrics": {
            "total_events": 42817,
            "significant_events": 1824,
            "sample_count": sample_count,
            "median_abs_dpsi": 0.27,
        },
        "event_counts": {"A3": 3851, "A5": 3425, "AF": 9848, "AL": 4282, "MX": 2141, "RI": 5994, "SE": 13276},
        "events": DEMO_EVENTS,
        "mode": "demo",
    }
    path = job_dir / "output" / "results.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_archive(job_dir: Path) -> None:
    archive = job_dir / "astk-report.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in (job_dir / "job.json", job_dir / "plan.json"):
            if path.exists():
                bundle.write(path, path.relative_to(job_dir).as_posix())
        for root_name in ("metadata", "output"):
            root = job_dir / root_name
            if root.exists():
                for path in root.rglob("*"):
                    if path.is_file():
                        bundle.write(path, path.relative_to(job_dir).as_posix())
        bundle.writestr(
            "README.txt",
            "ASTK Studio analysis bundle\nGenerated with the bundled SUPPA2 workflow.\n",
        )


def run_job(store: JobStore, job_id: str) -> None:
    job_dir = store.job_dir(job_id)
    job = store.read(job_id)
    if job is None:
        return
    mode = os.getenv("ASTK_EXECUTION_MODE", "demo").lower()
    completed: list[dict[str, Any]] = []
    try:
        output_dir = job_dir / "output"
        for path in (output_dir / "analysis", output_dir / "results.json", job_dir / "astk-report.zip"):
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        store.update(job_id, status="running", stage=STAGES[0][0])
        if job["config"].get("files"):
            store.update(job_id, stage="Input validation", progress=6)
            plan = prepare_job(job_dir, require_reference=mode == "command")
            job["config"]["sample_count"] = plan["sample_count"]
        if mode == "command":
            if not os.getenv("ASTK_RUNNER_COMMAND"):
                raise RuntimeError("ASTK_RUNNER_COMMAND is required in command mode")
            _run_external(store, job_id, job_dir)
        else:
            for name, progress in STAGES:
                store.update(job_id, stage=name, progress=progress, stages=completed)
                time.sleep(0.32)
                completed.append({"name": name, "status": "complete"})
            _write_results(job_dir, job["config"])
        store.update(job_id, status="completed", stage="Completed", progress=100, stages=completed)
        _build_archive(job_dir)
    except Exception as exc:
        log_path = job_dir / "output" / "runner.log"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\nASTK Studio error: {exc}\n")
        store.update(job_id, status="failed", stage="Failed", error=str(exc))


def _run_external(store: JobStore, job_id: str, job_dir: Path) -> None:
    template = os.environ["ASTK_RUNNER_COMMAND"]
    command = template.format(job_dir=job_dir, input_dir=job_dir / "input", output_dir=job_dir / "output")
    store.update(job_id, stage="SUPPA2 runner", progress=15)
    process = subprocess.run(
        shlex.split(command, posix=os.name != "nt"),
        cwd=job_dir,
        capture_output=True,
        text=True,
        timeout=int(os.getenv("ASTK_JOB_TIMEOUT", "21600")),
        check=False,
    )
    captured = "\n".join(part for part in (process.stdout, process.stderr) if part).strip()
    if captured:
        with (job_dir / "output" / "runner.log").open("a", encoding="utf-8") as handle:
            handle.write("\n=== RUNNER STDOUT/STDERR ===\n")
            handle.write(captured)
            handle.write("\n")
    if process.returncode != 0:
        raise RuntimeError(f"SUPPA2 runner exited with code {process.returncode}")
    if not (job_dir / "output" / "results.json").exists():
        raise RuntimeError("SUPPA2 runner did not create output/results.json")
