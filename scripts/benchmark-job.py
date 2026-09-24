#!/usr/bin/env python3
"""Run one real job in an isolated store and sample host/process resources."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.runner import run_job
from backend.store import JobStore


def _host() -> tuple[int, int, int, int]:
    cpu = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    values = [int(value) for value in cpu]
    mem = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in {"MemTotal", "MemAvailable"}:
            mem[key] = int(value.split()[0]) * 1024
    return sum(values), values[3] + values[4], mem["MemTotal"], mem["MemAvailable"]


def _processes(root_pid: int) -> tuple[int, int, int]:
    entries: dict[int, tuple[int, int, int]] = {}
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            stat = (path / "stat").read_text().rsplit(") ", 1)[1].split()
            entries[int(path.name)] = (
                int(stat[1]), int(stat[11]) + int(stat[12]),
                int(stat[21]) * os.sysconf("SC_PAGE_SIZE"),
            )
        except (OSError, ValueError, IndexError):
            continue
    descendants = {root_pid}
    while True:
        found = descendants | {pid for pid, (ppid, _, _) in entries.items() if ppid in descendants}
        if found == descendants:
            break
        descendants = found
    active = {pid: entries[pid] for pid in descendants if pid in entries}
    return len(active), sum(item[1] for item in active.values()), sum(item[2] for item in active.values())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--job-id")
    args = parser.parse_args()
    store = JobStore(args.output / "jobs")
    if args.worker:
        run_job(store, args.job_id)
        return

    job_id = "ASTK-BENCH-" + datetime.now().strftime("%y%m%d-%H%M%S")
    config = {
        "species": "Mus musculus · mm10",
        "design": "多时间点发育序列",
        "comparison_mode": "baseline",
        "event_type": "ALL",
        "method": "empirical",
        "p_value": 0.05,
        "abs_dpsi": 0,
        "sequence_features": True,
        "psi_high_threshold": 0.8,
        "psi_low_threshold": 0.2,
        "files": ["quant.zip", "samples.csv"],
        "demo": False,
    }
    store.create(job_id, config)
    job_dir = store.job_dir(job_id)
    shutil.copy2(args.zip, job_dir / "input" / "quant.zip")
    shutil.copy2(args.csv, job_dir / "input" / "samples.csv")
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    with (args.output / "worker.log").open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [sys.executable, __file__, "--worker", "--output", str(args.output), "--job-id", job_id],
            cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
        )
        previous_time = started
        previous_host = _host()
        previous_cpu = 0
        max_rss = max_cores = max_host_cpu = max_processes = 0
        min_available = previous_host[3]
        with (args.output / "resource-samples.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["seconds", "status", "stage", "processes", "rss_bytes",
                             "job_cpu_cores", "host_cpu_percent", "host_available_bytes"])
            while process.poll() is None:
                time.sleep(5)
                now = time.monotonic()
                host = _host()
                count, cpu, rss = _processes(process.pid)
                elapsed = now - previous_time
                cores = max(0, cpu - previous_cpu) / os.sysconf("SC_CLK_TCK") / elapsed
                host_cpu = 100 * (1 - (host[1] - previous_host[1]) / max(1, host[0] - previous_host[0]))
                job = store.read(job_id) or {}
                writer.writerow([round(now - started, 2), job.get("status"), job.get("stage"),
                                 count, rss, round(cores, 3), round(host_cpu, 2), host[3]])
                handle.flush()
                max_rss = max(max_rss, rss)
                max_cores = max(max_cores, cores)
                max_host_cpu = max(max_host_cpu, host_cpu)
                max_processes = max(max_processes, count)
                min_available = min(min_available, host[3])
                previous_time, previous_cpu, previous_host = now, cpu, host
        process.wait()
    job = store.read(job_id) or {}
    summary_path = job_dir / "output" / "sequence_features" / "summary.json"
    feature = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    result = {
        "job_id": job_id,
        "status": job.get("status"),
        "error": job.get("error"),
        "started_at_utc": started_at,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "sequence_seconds": feature.get("execution", {}).get("elapsed_seconds"),
        "sequence_failed": feature.get("failed"),
        "sequence_groups": len(feature.get("groups", [])),
        "sequence_comparisons": len(feature.get("comparisons", [])),
        "peak_job_rss_bytes_sampled": max_rss,
        "peak_job_cpu_cores_sampled": round(max_cores, 2),
        "peak_host_cpu_percent_sampled": round(max_host_cpu, 2),
        "minimum_host_available_bytes": min_available,
        "host_total_memory_bytes": previous_host[2],
        "peak_job_processes_sampled": max_processes,
        "job_disk_bytes": sum(path.stat().st_size for path in job_dir.rglob("*") if path.is_file()),
        "report_zip_bytes": (job_dir / "astk-report.zip").stat().st_size if (job_dir / "astk-report.zip").exists() else 0,
    }
    (args.output / "benchmark.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
