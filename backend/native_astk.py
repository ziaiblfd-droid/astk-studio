from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .planner import InputError


EVENT_TYPES = ("A3", "A5", "AF", "AL", "MX", "RI", "SE")
NATIVE_ENGINE_NAMES = {"astk", "native", "auto"}
VENDOR_ENGINE_NAMES = {"suppa", "suppa2", "vendor", "portable"}


def _engine_mode() -> str:
    return os.getenv("ASTK_ENGINE", "auto").strip().lower() or "auto"


def _native_module() -> Any:
    return importlib.import_module("astk.suppa")


def _groups_have_equal_replicates(
    metadata: dict[str, Any],
) -> list[str]:
    unbalanced: list[str] = []
    for group, roles in metadata.items():
        if not isinstance(roles, dict):
            continue
        ctrl_count = len(roles.get("ctrl", {}).get("samples", []))
        case_count = len(roles.get("case", {}).get("samples", []))
        if ctrl_count != case_count:
            unbalanced.append(group)
    return unbalanced


def select_engine(job_dir: Path, metadata: dict[str, Any]) -> str:
    del job_dir
    mode = _engine_mode()
    if mode in VENDOR_ENGINE_NAMES:
        return "suppa2"
    try:
        _native_module()
    except ImportError as error:
        if mode in {"astk", "native"}:
            raise InputError(
                "ASTK native engine was requested, but the astk package is unavailable"
            ) from error
        return "suppa2"

    unbalanced = _groups_have_equal_replicates(metadata)
    if unbalanced:
        if mode in {"astk", "native"}:
            groups = ", ".join(unbalanced)
            raise InputError(
                "ASTK native engine currently requires equal ctrl/case replicates: "
                + groups
            )
        return "suppa2"
    return "astk"


def _absolute_metadata(job_dir: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for group, roles in metadata.items():
        payload[group] = {}
        for condition in ("ctrl", "case"):
            samples = []
            for sample in roles.get(condition, {}).get("samples", []):
                raw_path = Path(str(sample.get("path", "")))
                path = raw_path if raw_path.is_absolute() else (job_dir / raw_path)
                path = path.resolve()
                if not path.is_file():
                    raise InputError(f"Native ASTK input is missing: {path}")
                samples.append(
                    {
                        "name": str(sample.get("name", path.parent.name)),
                        "replicate": int(sample.get("replicate", len(samples) + 1)),
                        "path": str(path),
                    }
                )
            payload[group][condition] = {"samples": samples}
    return payload


def _write_native_metadata(
    job_dir: Path,
    metadata: dict[str, Any],
) -> Path:
    path = job_dir / "metadata" / "astk_native_metadata.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _absolute_metadata(job_dir, metadata)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _copy(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise RuntimeError(f"ASTK native output is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def canonicalize_native_outputs(
    native_dir: Path,
    analysis_dir: Path,
    comparisons: list[dict[str, str]],
    abs_dpsi: float,
) -> dict[str, int]:
    copied = {"events": 0, "psi": 0, "dpsi": 0, "significant": 0, "significant_psi": 0}
    events_dir = analysis_dir / "events"
    psi_dir = analysis_dir / "psi"
    dpsi_dir = analysis_dir / "dpsi"
    significant_dir = analysis_dir / "sig01" / "dpsi"
    significant_psi_dir = analysis_dir / "sig01" / "psi"

    for kind in EVENT_TYPES:
        source = native_dir / "ref" / f"annotation_{kind}_strict.ioe"
        if source.is_file():
            _copy(source, events_dir / f"events_{kind}_strict.ioe")
            copied["events"] += 1

    sig_name = "sig" + str(abs_dpsi).replace(".", "")
    native_significant_dir = native_dir / sig_name
    for comparison in comparisons:
        group = comparison["group"]
        for kind in EVENT_TYPES:
            psi_sources = {
                "c1": native_dir / "psi" / f"{group}_{kind}_c1.psi",
                "c2": native_dir / "psi" / f"{group}_{kind}_c2.psi",
            }
            if all(path.is_file() for path in psi_sources.values()):
                for suffix, source in psi_sources.items():
                    _copy(source, psi_dir / f"{group}_{kind}_{suffix}.psi")
                    copied["psi"] += 1

            dpsi_source = native_dir / "dpsi" / f"{group}_{kind}.dpsi"
            if dpsi_source.is_file():
                _copy(dpsi_source, dpsi_dir / f"{group}_{kind}.dpsi")
                copied["dpsi"] += 1

            sig_source = native_significant_dir / f"{group}_{kind}.sig.dpsi"
            if sig_source.is_file():
                _copy(sig_source, significant_dir / f"{group}_{kind}.sig.dpsi")
                copied["significant"] += 1

            for suffix in ("c1", "c2"):
                sig_psi_source = native_significant_dir / "psi" / f"{group}_{kind}_{suffix}.sig.psi"
                if sig_psi_source.is_file():
                    _copy(
                        sig_psi_source,
                        significant_psi_dir / f"{group}_{kind}_{suffix}.sig.psi",
                    )
                    copied["significant_psi"] += 1

    return copied


def run_native_astk(
    job_dir: Path,
    plan: dict[str, Any],
    metadata: dict[str, Any],
) -> list[str]:
    astk_suppa = _native_module()
    ds_flow = getattr(astk_suppa, "ds_flow")
    native_dir = job_dir / "output" / "analysis" / "native"
    if native_dir.exists():
        shutil.rmtree(native_dir)
    native_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = _write_native_metadata(job_dir, metadata)
    method = str(plan.get("method", "empirical")).lower()
    p_value = float(plan.get("p_value", 0.05))
    abs_dpsi = float(plan.get("abs_dpsi", 0.0))

    ds_flow(
        str(metadata_path),
        str(Path(plan["reference"]["gtf"]).resolve()),
        list(EVENT_TYPES),
        str(native_dir),
        method,
        "SUPPA2",
        p_value,
        abs_dpsi,
        0,
        None,
        4,
    )

    copied = canonicalize_native_outputs(
        native_dir,
        job_dir / "output" / "analysis",
        list(plan.get("comparisons", [])),
        abs_dpsi,
    )
    try:
        version = importlib.metadata.version("astk")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"

    plan["engine"] = "astk-native"
    plan["native_engine"] = f"astk {version}"
    plan_path = job_dir / "plan.json"
    plan_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return [
        "=== NATIVE ASTK ENGINE ===",
        f"ASTK version: {version}",
        f"Native output: {native_dir}",
        f"Copied events: {copied['events']}, psi: {copied['psi']}, "
        f"dpsi: {copied['dpsi']}, significant: {copied['significant']}, "
        f"significant psi: {copied['significant_psi']}",
    ]
