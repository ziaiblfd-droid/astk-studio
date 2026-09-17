from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .planner import prepare_job
from .result_parser import parse_results


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
        raise RuntimeError(f"ASTK exited with code {process.returncode}")
    parse_results(job_dir, Path(plan["reference"]["gtf"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute a prepared ASTK Studio job")
    parser.add_argument("job_dir", type=Path)
    args = parser.parse_args()
    execute(args.job_dir.resolve())


if __name__ == "__main__":
    main()
