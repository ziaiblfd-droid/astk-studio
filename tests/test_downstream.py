from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.downstream import _Fasta, _event_id_from_line, _parse_coords, run_enrichment
from backend.store import JobStore


class DownstreamTests(unittest.TestCase):
    def test_event_id_parser_ignores_headers_and_accepts_whitespace(self) -> None:
        self.assertEqual(_event_id_from_line("event_id\tdpsi\tp_value"), "")
        self.assertEqual(
            _event_id_from_line("  ENSMUSG1.1;SE:chr1:1-2:3-4  0.4  0.01"),
            "ENSMUSG1.1;SE:chr1:1-2:3-4",
        )

    def test_fasta_fetch_handles_wrapped_plain_fasta(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "genome.fa"
            path.write_text(">chr1\nACGTAC\nGTAC\n>chr2\nTTTT\n", encoding="ascii")
            fasta = _Fasta(path)
            self.assertEqual(fasta.fetch("chr1", 2, 10), "GTACGTAC")
            self.assertEqual(fasta.fetch("chr2", 1, 3), "TT")

    def test_motif_region_uses_exon_coordinates(self) -> None:
        event = {"chrom": "chr1", "coords": "100-120:200-240"}
        self.assertEqual(_parse_coords(event, "exon"), ("chr1", 100, 120))
        self.assertEqual(_parse_coords(event, "flank-10"), ("chr1", 90, 130))

    def test_enrichment_clamps_cutoffs_and_writes_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = JobStore(root / "jobs")
            parent = store.create("PARENT", {"species": "mm10"})
            store.update("PARENT", status="completed", progress=100)
            parent_output = store.job_dir("PARENT") / "output"
            (parent_output / "results.json").write_text(
                json.dumps({
                    "reference": "mm10",
                    "events": [["ENSMUSG1.1;SE:chr1:1-2:3-4", "GENE1", "SE"]],
                }),
                encoding="utf-8",
            )
            (parent_output / "events.sig.dpsi").write_text(
                "event_id\tdpsi\tp_value\n"
                "ENSMUSG1.1;SE:chr1:1-2:3-4\t0.4\t0.01\n",
                encoding="utf-8",
            )
            child = store.create("CHILD", {})
            genesets = root / "genesets"
            genesets.mkdir()
            (genesets / "GO_BP.gmt").write_text("term (GO:1)\t\tGENE1\n", encoding="utf-8")

            with patch("backend.downstream.GENESET_DIR", genesets):
                result = run_enrichment(
                    store,
                    "CHILD",
                    "PARENT",
                    {"database": "GO_BP", "pvalue": 0, "qvalue": 2, "gene_set": "unknown"},
                )

            self.assertEqual(result["params"]["gene_set"], "significant")
            self.assertEqual(result["params"]["pvalue"], 0.0)
            self.assertEqual(result["params"]["qvalue"], 1.0)
            self.assertTrue((store.job_dir("CHILD") / "output" / "enrichment_GO_BP.csv").exists())
