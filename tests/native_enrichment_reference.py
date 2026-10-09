"""Linux regression against the original ASTK inputs, partitions, and CSVs.

Run with --source /path/to/facial_11.5_based --output /isolated/validation.
Never writes to the reference source or production jobs.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.downstream import EVENT_TYPES, _load_events_file, _write_events


def compare_csv(actual: Path, expected: Path) -> int:
    def read(path):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return {row["ID"]: row for row in csv.DictReader(handle)}
    got, want = read(actual), read(expected)
    if got.keys() != want.keys():
        raise AssertionError(f"{actual}: GO IDs differ: got {len(got)}, expected {len(want)}")
    for term, row in want.items():
        for column in ("Description", "GeneRatio", "BgRatio", "Count"):
            if got[term][column] != row[column]:
                raise AssertionError(f"{actual}: {term} {column} differs")
        for column in ("pvalue", "p.adjust", "qvalue"):
            if not math.isclose(float(got[term][column]), float(row[column]), rel_tol=1e-10, abs_tol=1e-14):
                raise AssertionError(f"{actual}: {term} {column} differs")
        if set(got[term]["geneID"].split("/")) != set(row["geneID"].split("/")):
            raise AssertionError(f"{actual}: {term} gene membership differs")
    return len(got)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("ora", "compare"), default="ora")
    parser.add_argument(
        "--skip-go-clustering",
        action="store_true",
        help="skip optional simplifyEnrichment plots for faster statistical regression",
    )
    parser.add_argument(
        "--reuse-output",
        action="store_true",
        help="validate an existing output directory without rerunning R",
    )
    args = parser.parse_args()
    if args.reuse_output:
        if not args.output.is_dir():
            raise FileNotFoundError(args.output)
    else:
        args.output.mkdir(parents=True, exist_ok=False)
    cells = []
    for age in (12, 13, 14, 15):
        group = f"facial_11.5_{age}"
        for kind in EVENT_TYPES:
            key = f"{group}_{kind}"
            source = args.source / "sig01" / f"{key}.sig.dpsi"
            if not source.is_file():
                raise FileNotFoundError(source)
            events = _load_events_file(source, kind)
            input_path = args.output / "native_inputs" / source.name
            if not args.reuse_output:
                _write_events(input_path, events)
            cells.append({
                "group": group, "comparison": group, "event_type": kind, "key": key,
                "input": str(input_path.resolve()), "input_events": len(events),
                "input_genes": len({e["gene_id"].split(".", 1)[0] for e in events}),
                "missing": False, "source": "reference_significant_file",
            })
    manifest = {
        "mode": args.mode, "species": "mm10", "ontology": "BP", "pvalue": 0.1, "qvalue": 0.1,
        "length_breaks": [1, 51, 251, 1001], "cells": cells, "output": str(args.output.resolve()),
        "simple": not args.skip_go_clustering,
    }
    manifest_path = args.output / "native_manifest.json"
    if not args.reuse_output:
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        subprocess.run([sys.executable, str(ROOT / "backend/native_enrichment.py"), str(manifest_path)], check=True)
    native = json.loads((args.output / "native_results.json").read_text())
    total = 0
    missing_reference = []
    for cell in native["units"]:
        if args.mode == "ora":
            expected = args.source / "enrich/Over_representation" / cell["key"] / "GO.BP.qval0.1_pval0.1.csv"
            if expected.is_file():
                total += compare_csv(args.output / cell["tables"][0], expected)
            else:
                missing_reference.append(cell["key"])
                if cell["terms"] != 0:
                    raise AssertionError(
                        f"{cell['key']}: original ASTK result is absent but new output has "
                        f"{cell['terms']} terms"
                    )
        else:
            # Compare ASTK's native selector against the user's saved lenCluster
            # files, including the precise upper-bound convention.
            for cluster in cell["cluster_inputs"]:
                old = _load_events_file(
                    args.source / "lenc" / cluster["label"] / Path(cell["input"]).name,
                    cell["event_type"],
                )
                new = _load_events_file(Path(cluster["path"]), cell["event_type"])
                if {e["event_id"] for e in old} != {e["event_id"] for e in new}:
                    raise AssertionError(f"ASTK length selection differs: {cell['key']} {cluster['label']}")
        if cell["warnings"]:
            raise AssertionError(f"GO clustering incomplete: {cell['key']}: {cell['warnings']}")
        for image in cell["images"]:
            with (args.output / image).open("rb") as handle:
                assert handle.read(8) == b"\x89PNG\r\n\x1a\n"
    print(json.dumps({
        "mode": args.mode,
        "units": len(native["units"]),
        "primary_images": sum(any("/simgo/" not in image for image in c["images"]) for c in native["units"]),
        "all_images": sum(len(c["images"]) for c in native["units"]),
        "numerically_matched_ORA_terms": total,
        "reference_csv_missing_for_empty_units": missing_reference,
        "provenance": native["provenance"],
    }, indent=2))


if __name__ == "__main__":
    main()
