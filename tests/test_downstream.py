from __future__ import annotations

import json
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.downstream import (
    EVENT_TYPES, _bh_adjust, _comparison_units, _event_id_from_line,
    _fisher_right, _load_events_file, _run_ora, _safe_token, run_downstream, run_enrichment,
)
from backend.store import JobStore


class DownstreamTests(unittest.TestCase):
    def test_event_id_parser_ignores_headers_and_accepts_whitespace(self) -> None:
        self.assertEqual(_event_id_from_line("event_id\tdpsi\tp_value"), "")
        self.assertEqual(
            _event_id_from_line("  ENSMUSG1.1;SE:chr1:1-2:3-4  0.4  0.01"),
            "ENSMUSG1.1;SE:chr1:1-2:3-4",
        )

    def make_fixture(self, root: Path):
        store = JobStore(root / "jobs")
        store.create("PARENT", {"species": "mm10", "p_value": 0.05, "abs_dpsi": 0.1})
        store.update("PARENT", status="completed")
        directory = store.job_dir("PARENT")
        groups = ["facial_11.5_12", "facial_11.5_13"]
        (directory / "plan.json").write_text(json.dumps({"comparisons": [{"group": g} for g in groups]}), encoding="utf-8")
        (directory / "output/results.json").write_text(json.dumps({"reference": "mm10", "events": []}), encoding="utf-8")
        for group in groups:
            for kind in EVENT_TYPES:
                background = directory / "output/analysis/dpsi" / f"{group}_{kind}.dpsi"
                significant = directory / "output/analysis/sig01/dpsi" / f"{group}_{kind}.sig.dpsi"
                for path in (background, significant):
                    path.parent.mkdir(parents=True, exist_ok=True)
                rows = [f"G{i};{kind}:chr1:1-2:3-4\t{0.4 if i < 5 else 0.01}\t{0.001 if i < 5 else 0.8}\n" for i in range(100)]
                background.write_text("event_id\tdpsi\tp_value\n" + "".join(rows), encoding="utf-8")
                significant.write_text("event_id\tdpsi\tp_value\n" + "".join(rows[:5] if group == groups[0] else rows[5:8]), encoding="utf-8")
        genesets = root / "genesets"
        genesets.mkdir()
        (genesets / "GO_BP.gmt").write_text("term1\t\t" + "\t".join(f"G{i}" for i in range(5)) + "\nall\t\t" + "\t".join(f"G{i}" for i in range(100)) + "\n", encoding="utf-8")
        store.create("CHILD", {})
        return store, genesets

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
            (store.job_dir("PARENT") / "plan.json").write_text(json.dumps({"comparisons": [{"group": "g1"}]}), encoding="utf-8")
            background = parent_output / "analysis/dpsi/g1_SE.dpsi"
            significant = parent_output / "analysis/sig01/dpsi/g1_SE.sig.dpsi"
            for path in (background, significant):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text((parent_output / "events.sig.dpsi").read_text(encoding="utf-8"), encoding="utf-8")
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

    def test_two_comparisons_produce_fourteen_distinct_images(self):
        with tempfile.TemporaryDirectory() as temporary:
            store, genesets = self.make_fixture(Path(temporary))
            with patch("backend.downstream.GENESET_DIR", genesets):
                result = run_enrichment(store, "CHILD", "PARENT", {})
            images = result["images"]["ora"]
            self.assertEqual(len(images), 14)
            self.assertEqual(len({i["path"] for i in images}), 14)
            self.assertEqual(result["summary"]["Expected plots"], 14)
            for item in images:
                path = store.job_dir("CHILD") / item["path"]
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 1000)
            self.assertTrue(all(u["input_genes"] == 5 for u in result["units"][:7]))
            self.assertTrue(all(u["input_genes"] == 3 for u in result["units"][7:]))
            self.assertTrue(all(u["significant_terms"] == 1 for u in result["units"][:7]))
            self.assertTrue(all(u["significant_terms"] == 0 for u in result["units"][7:]))

    def test_missing_sig_file_is_derived_without_mixing_groups(self):
        with tempfile.TemporaryDirectory() as temporary:
            store, genesets = self.make_fixture(Path(temporary))
            (store.job_dir("PARENT") / "output/analysis/sig01/dpsi/facial_11.5_12_SE.sig.dpsi").unlink()
            with patch("backend.downstream.GENESET_DIR", genesets):
                result = run_enrichment(store, "CHILD", "PARENT", {"mode": "compare"})
            unit = next(u for u in result["units"] if u["group"] == "facial_11.5_12" and u["event_type"] == "SE")
            self.assertEqual(unit["input_genes"], 5)
            self.assertEqual(unit["source"], "derived_from_dpsi")
            self.assertEqual(len(result["images"]["compare"]), 2)
            for image in result["images"]["compare"]:
                self.assertTrue((store.job_dir("CHILD") / image["path"]).is_file())

    def test_missing_background_is_marked_and_other_units_continue(self):
        with tempfile.TemporaryDirectory() as temporary:
            store, genesets = self.make_fixture(Path(temporary))
            (store.job_dir("PARENT") / "output/analysis/dpsi/facial_11.5_12_SE.dpsi").unlink()
            with patch("backend.downstream.GENESET_DIR", genesets):
                result = run_enrichment(store, "CHILD", "PARENT", {})
            self.assertEqual(len(result["images"]["ora"]), 14)
            self.assertEqual(result["summary"]["Missing input pairs"], 1)
            unit = next(u for u in result["units"] if u["group"] == "facial_11.5_12" and u["event_type"] == "SE")
            self.assertEqual(unit["status"], "missing_background")
            self.assertEqual(unit["terms"], 0)

    def test_plot_failure_fails_job_instead_of_silent_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            store, genesets = self.make_fixture(Path(temporary))
            store.update("CHILD", config={"downstream": {"module": "enrichment", "parent_job_id": "PARENT"}})
            with patch("backend.downstream.GENESET_DIR", genesets), patch("backend.downstream._matplotlib", side_effect=RuntimeError("test")):
                run_downstream(store, "CHILD")
            self.assertEqual(store.read("CHILD")["status"], "failed")
            self.assertTrue((store.job_dir("CHILD") / "output/downstream_error.txt").exists())

    def test_fisher_and_bh_match_expected_values(self):
        self.assertAlmostEqual(_fisher_right(1, 0, 0, 9), 0.1)
        self.assertEqual(_bh_adjust([]), [])
        for actual, expected in zip(_bh_adjust([0.01, 0.04, 0.03]), [0.03, 0.04, 0.04]):
            self.assertAlmostEqual(actual, expected)

    def test_direction_and_unannotated_genes_are_filtered(self):
        events = [{"gene_id": "G1.2", "dpsi": 0.4}, {"gene_id": "G2", "dpsi": -0.5}, {"gene_id": "G3", "dpsi": 0}, {"gene_id": "unknown", "dpsi": 0.5}]
        rows, sig, count, background = _run_ora(events, events, {"G1": "G1"}, {"all": {"G1", "G2", "G3"}}, "up", 0, 0)
        self.assertEqual(count, 1)
        self.assertEqual(background, 3)
        self.assertEqual(rows[0]["genes"], ["G1"])
        self.assertEqual(sig, [])

    def test_unsafe_group_tokens_do_not_collide(self):
        self.assertNotEqual(_safe_token("a b"), _safe_token("a_b"))
        self.assertNotIn("/", _safe_token("../a"))

    def test_frontend_has_no_motif_or_result_table(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("index.html", "downstream.js", "i18n.js"):
            self.assertNotIn("motif", (root / name).read_text(encoding="utf-8").lower())
        self.assertNotIn("renderTable", (root / "downstream.js").read_text(encoding="utf-8"))

    def test_api_rejects_removed_module(self):
        from backend.server import ASTKHandler
        from unittest.mock import Mock
        handler = object.__new__(ASTKHandler)
        handler.read_json_body = Mock(return_value={"module": "motif"})
        handler.send_json = Mock()
        handler.create_downstream_job("PARENT")
        self.assertEqual(handler.send_json.call_args.args[1], 400)

    def test_parser_accepts_gene_prefix_and_rejects_invalid_numbers(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "test_SE.dpsi"
            path.write_text("event_id\tdpsi\tp_value\nGENE1;SE:chr1:1-2\t0.2\t0.01\nGENE2;SE:chr1:1-2\tbad\t0.01\nGENE3;SE:chr1:1-2\tnan\t0.01\nGENE4;SE:chr1:1-2\t0.2\t2\n", encoding="utf-8-sig")
            self.assertEqual([row["gene_id"] for row in _load_events_file(path, "SE")], ["GENE1"])

    def test_compare_paginates_and_exports_nonsignificant_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            store, genesets = self.make_fixture(Path(temporary))
            parent = store.job_dir("PARENT")
            (parent / "plan.json").write_text(json.dumps({"comparisons": [{"group": group} for group in ("facial_11.5_12", "facial_11.5_13", "extra")]}), encoding="utf-8")
            with patch("backend.downstream.GENESET_DIR", genesets):
                result = run_enrichment(store, "CHILD", "PARENT", {"mode": "compare"})
            self.assertEqual(len(result["images"]["compare"]), 4)
            self.assertEqual(result["summary"]["Expected plots"], 4)
            with (store.job_dir("CHILD") / "output/enrichment_compare/GO_BP/comparison.csv").open(encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            self.assertTrue(any(row["significant"] == "False" for row in rows))
            self.assertEqual({row["comparison"] for row in rows}, {"facial_11.5_12", "facial_11.5_13"})

    def test_empty_compare_still_produces_bubble_and_heatmap(self):
        with tempfile.TemporaryDirectory() as temporary:
            store, genesets = self.make_fixture(Path(temporary))
            with patch("backend.downstream.GENESET_DIR", genesets):
                result = run_enrichment(store, "CHILD", "PARENT", {"mode": "compare", "pvalue": 0})
            self.assertEqual(len(result["images"]["compare"]), 2)
            self.assertTrue(all((store.job_dir("CHILD") / image["path"]).is_file() for image in result["images"]["compare"]))

    def test_legacy_filename_inference_and_duplicate_comparisons(self):
        with tempfile.TemporaryDirectory() as temporary:
            store, _ = self.make_fixture(Path(temporary))
            parent = store.job_dir("PARENT")
            (parent / "plan.json").unlink()
            self.assertEqual(len(_comparison_units(parent)), 2)
            (parent / "plan.json").write_text(json.dumps({"comparisons": [{"group": "g"}, {"group": "g"}]}), encoding="utf-8")
            self.assertEqual(len(_comparison_units(parent)), 1)

    def test_ora_retains_all_overlap_genes(self):
        events = [{"gene_id": f"G{i}", "dpsi": 0.5} for i in range(60)]
        rows, _, _, _ = _run_ora(events, events, {}, {"term": {e["gene_id"] for e in events}}, "significant", 1, 1)
        self.assertEqual(len(rows[0]["genes"]), 60)

    def test_api_rejects_invalid_mode(self):
        from backend.server import ASTKHandler
        from unittest.mock import Mock
        handler = object.__new__(ASTKHandler)
        handler.read_json_body = Mock(return_value={"module": "enrichment", "params": {"mode": "invalid"}})
        handler.send_json = Mock()
        handler.create_downstream_job("PARENT")
        self.assertEqual(handler.send_json.call_args.args[1], 400)
