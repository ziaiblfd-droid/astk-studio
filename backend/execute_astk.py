from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .planner import prepare_job
from .result_parser import parse_results
from .visualization import generate_visualizations


def execute(job_dir: Path) -> None:
    plan = prepare_job(job_dir, require_reference=True)
    log_path = job_dir / "output" / "runner.log"
    process = subprocess.run(
        plan["command"],
        cwd=job_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    log_path.write_text(process.stdout + "\n" + process.stderr, encoding="utf-8")
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise RuntimeError(f"ASTK exited with code {process.returncode}{suffix}")
    plot_log = generate_visualizations(job_dir, plan)
    if plot_log:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write("\n\n=== VISUALIZATION ===\n")
            handle.write(plot_log)
            handle.write("\n")
    parse_results(job_dir, Path(plan["reference"]["gtf"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute a prepared ASTK Studio job")
    parser.add_argument("job_dir", type=Path)
    args = parser.parse_args()
    execute(args.job_dir.resolve())


if __name__ == "__main__":
    main()
