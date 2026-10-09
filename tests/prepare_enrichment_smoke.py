"""Create isolated synthetic inputs for local browser/API verification."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_downstream import DownstreamTests


if __name__ == "__main__":
    directory = ROOT / "data" / ("enrichment-smoke-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    directory.mkdir(parents=True)
    store, genesets = DownstreamTests().make_fixture(directory)
    store.update("CHILD", status="completed")
    print(directory)
    print(genesets)
