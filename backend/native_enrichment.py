"""Process entry point: native ASTK length selection and configured R runtime."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def prepare(manifest: dict) -> None:
    import astk
    from astk.utils.func import Rscript_bin
    from astk.utils._cli_func import df_len_select

    manifest["astk_utils"] = str(Path(astk.__file__).parent / "R/utils.R")
    manifest["rscript"] = Rscript_bin()
    output = Path(manifest["output"])
    for cell in manifest["cells"]:
        source = Path(cell["input"])
        cell["cluster_inputs"] = []
        if manifest["mode"] != "compare":
            continue
        for start, end in zip(manifest["length_breaks"], manifest["length_breaks"][1:]):
            label = f"{start}-{end}"
            path = output / "native_inputs/lenc" / label / source.name
            path.parent.mkdir(parents=True, exist_ok=True)
            if cell["input_events"]:
                # Match ASTK lc's multi-input branch used by the reference script,
                # including its inclusive upper endpoint (e + 1).
                df_len_select(str(source), str(path), start, end + 1)
            else:
                path.write_text("event_id\tdpsi\tp_value\n", encoding="utf-8")
            cell["cluster_inputs"].append({"label": label, "path": str(path)})


def main() -> None:
    path = Path(sys.argv[1])
    manifest = json.loads(path.read_text(encoding="utf-8"))
    prepare(manifest)
    runtime = path.with_name("native_runtime.json")
    runtime.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    subprocess.run(
        [manifest["rscript"], str(Path(__file__).with_name("native_enrichment.R")), str(runtime)],
        check=True,
    )


if __name__ == "__main__":
    main()
