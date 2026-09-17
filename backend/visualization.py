from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


EVENT_TYPES = ("A3", "A5", "AF", "AL", "MX", "RI", "SE")


def run_plot(command: list[str], log: list[str]) -> None:
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    log.append(f"$ {' '.join(command)}")
    if process.stdout.strip():
        log.append(process.stdout.strip())
    if process.stderr.strip():
        log.append(process.stderr.strip())
    if process.returncode != 0:
        log.append(f"[warning] plot command exited with code {process.returncode}")


def generate_visualizations(job_dir: Path, plan: dict[str, Any]) -> str:
    analysis = job_dir / "output" / "analysis"
    image_root = analysis / "img"
    for name in ("bar", "PCA", "heatmap", "volcano"):
        (image_root / name).mkdir(parents=True, exist_ok=True)

    log: list[str] = []
    comparisons = plan.get("comparisons", [])
    for comparison in comparisons:
        group = comparison["group"]
        significant = [analysis / "sig01" / f"{group}_{kind}.sig.dpsi" for kind in EVENT_TYPES]
        existing = [path for path in significant if path.exists()]
        if existing:
            run_plot(
                [
                    "astk", "barplot", "-i", *map(str, existing),
                    "-o", str(image_root / "bar" / f"{group}.png"),
                    "-dg", "-xl", *[kind for kind, path in zip(EVENT_TYPES, significant) if path.exists()],
                ],
                log,
            )
        for kind in EVENT_TYPES:
            dpsi = analysis / "dpsi" / f"{group}_{kind}.dpsi"
            if dpsi.exists():
                run_plot(
                    [
                        "astk", "volcano", "-i", str(dpsi),
                        "-o", str(image_root / "volcano" / f"{group}_{kind}.png"),
                    ],
                    log,
                )

    if comparisons:
        first = comparisons[0]
        for kind in EVENT_TYPES:
            psi_files = [analysis / "psi" / f"{first['group']}_{kind}_c1.psi"]
            psi_files.extend(analysis / "psi" / f"{item['group']}_{kind}_c2.psi" for item in comparisons)
            psi_files = [path for path in psi_files if path.exists()]
            labels = [first["control"], *[item["treatment"] for item in comparisons]]
            if len(psi_files) == len(labels):
                run_plot(
                    [
                        "astk", "pca", "-i", *map(str, psi_files),
                        "-o", str(image_root / "PCA" / f"{kind}.png"),
                        "-ff", "png", "-gb", "col", "-gl", *labels,
                    ],
                    log,
                )

            sig_psi = [analysis / "sig01" / "psi" / f"{first['group']}_{kind}_c1.sig.psi"]
            sig_psi.extend(
                analysis / "sig01" / "psi" / f"{item['group']}_{kind}_c2.sig.psi"
                for item in comparisons
            )
            sig_psi = [path for path in sig_psi if path.exists() and path.stat().st_size > 0]
            if sig_psi:
                run_plot(
                    [
                        "astk", "hm", "-i", *map(str, sig_psi),
                        "-o", str(image_root / "heatmap" / f"{kind}.png"),
                        "-ff", "png",
                    ],
                    log,
                )

    return "\n".join(log)
