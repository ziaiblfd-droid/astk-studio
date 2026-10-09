from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.downstream import (
    EVENT_TYPES, _comparison_units, _cutoff, _detect_species, _event_id_from_line,
    _load_events_file, _safe_token, run_downstream, run_enrichment,
)
from backend.store import JobStore


class DownstreamTests(unittest.TestCase):
    def make_fixture(self, root):
        store = JobStore(root / "jobs")
        store.create("PARENT", {"species": "mm10", "p_value": 0.05, "abs_dpsi": 0.1})
        store.update("PARENT", status="completed")
        parent = store.job_dir("PARENT")
        groups = ["facial_11.5_12", "facial_11.5_13"]
        (parent / "plan.json").write_text(json.dumps({"comparisons": [{"group": g} for g in groups]}), encoding="utf-8")
        (parent / "output/results.json").write_text(json.dumps({"reference": "mm10"}), encoding="utf-8")
        for group in groups:
            for kind in EVENT_TYPES:
                for directory, suffix in (("dpsi", ".dpsi"), ("sig01/dpsi", ".sig.dpsi")):
                    path = parent / "output/analysis" / directory / (group + "_" + kind + suffix)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(
                        f"event_id\tdpsi\tp_value\nENSMUSG1.1;{kind}:chr1:1-2:3-4:+\t0.4\t0.001\n"
                        f"ENSMUSG2;{kind}:chr1:1-2:3-4:+\t-0.4\t0.001\n",
                        encoding="utf-8")
        store.create("CHILD", {})
        return store

    def fake_native(self, manifest_path, store, job_id):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.manifest = manifest
        output = manifest_path.parent
        cells = []
        for cell in manifest["cells"]:
            base = f"enrichment{'_compare' if manifest['mode'] == 'compare' else ''}/{cell['key']}"
            image, table = base + "/GO.BP.png", base + "/GO.BP.csv"
            (output / image).parent.mkdir(parents=True, exist_ok=True)
            (output / image).write_bytes(b"\x89PNG\r\n\x1a\n" + b"test image")
            (output / table).write_text(
                '"","ID","Description","GeneRatio","BgRatio","pvalue","p.adjust","qvalue","geneID","Count"\n'
                '"GO:1","GO:1","splicing","2/449","198/24292",0.0001,0.001,0.0009,"A/B",2\n',
                encoding="utf-8")
            cells.append({**cell, "images": [image], "tables": [table], "files": [image, table],
                          "status": "missing_input" if cell["missing"] else "completed", "terms": 1})
        return {"units": cells, "provenance": {"engine": "ASTK"}}

    def run_fixture(self, store, params=None):
        with patch("backend.downstream._run_native", side_effect=self.fake_native):
            return run_enrichment(store, "CHILD", "PARENT", params or {})

    def test_event_parser(self):
        self.assertEqual(_event_id_from_line("event_id\tdpsi\tp_value"), "")
        self.assertEqual(_event_id_from_line("  G1;SE:chr1:1-2  0.4  0.01"), "G1;SE:chr1:1-2")

    def test_defaults_are_astk_point_one_and_bp_only(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_fixture(self.make_fixture(Path(temp)))
            self.assertEqual(result["params"]["pvalue"], 0.1)
            self.assertEqual(result["params"]["qvalue"], 0.1)
            self.assertEqual(self.manifest["ontology"], "BP")
            self.assertTrue(self.manifest["simple"])
            self.assertNotIn("background", self.manifest)

    def test_two_groups_produce_fourteen_native_figures(self):
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_fixture(Path(temp))
            result = self.run_fixture(store)
            self.assertEqual(len(result["images"]["ora"]), 14)
            self.assertEqual(len({i["path"] for i in result["images"]["ora"]}), 14)
            self.assertTrue(all((store.job_dir("CHILD") / i["path"]).is_file() for i in result["images"]["ora"]))
            self.assertEqual({u["input_genes"] for u in result["units"]}, {2})

    def test_compare_runs_length_clusters_per_group_type_not_mixed(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_fixture(self.make_fixture(Path(temp)), {"mode": "compare"})
            self.assertEqual(len(result["images"]["compare"]), 14)
            self.assertEqual(self.manifest["length_breaks"], [1, 51, 251, 1001])
            self.assertTrue(all(i["comparison"] and i["event_type"] for i in result["images"]["compare"]))

    def test_sig_file_does_not_require_tested_background(self):
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_fixture(Path(temp))
            (store.job_dir("PARENT") / "output/analysis/dpsi/facial_11.5_12_SE.dpsi").unlink()
            result = self.run_fixture(store)
            cell = next(c for c in result["units"] if c["key"] == "facial_11.5_12_SE")
            self.assertFalse(cell["missing"])
            self.assertEqual(cell["input_genes"], 2)

    def test_missing_sig_derived_per_type(self):
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_fixture(Path(temp))
            (store.job_dir("PARENT") / "output/analysis/sig01/dpsi/facial_11.5_12_SE.sig.dpsi").unlink()
            result = self.run_fixture(store)
            cell = next(c for c in result["units"] if c["key"] == "facial_11.5_12_SE")
            self.assertEqual(cell["source"], "derived_from_dpsi")
            self.assertEqual(cell["input_events"], 2)

    def test_direction_filter_keeps_versionless_ensembl_and_header(self):
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_fixture(Path(temp))
            self.run_fixture(store, {"gene_set": "down"})
            cell = self.manifest["cells"][0]
            events = _load_events_file(Path(cell["input"]))
            self.assertEqual([e["gene_id"] for e in events], ["ENSMUSG2"])
            self.assertTrue(Path(cell["input"]).read_text().startswith("event_id\t"))

    def test_csv_preserves_native_precision_ratios_and_true_qvalue(self):
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_fixture(Path(temp))
            self.run_fixture(store)
            with (store.job_dir("CHILD") / "output/enrichment_GO_BP.csv").open(encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 14)
            self.assertEqual(rows[0]["BgRatio"], "198/24292")
            self.assertNotEqual(rows[0]["p.adjust"], rows[0]["qvalue"])

    def test_invalid_databases_and_thresholds_rejected(self):
        for params in ({"database": "GO_MF"}, {"database": "KEGG"}, {"pvalue": -1}, {"qvalue": 2}, {"qvalue": "nan"}, {"mode": "bad"}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                run_enrichment(None, "CHILD", "PARENT", params)
        self.assertEqual(_cutoff({"pvalue": 0}, "pvalue"), 0)

    def test_native_error_fails_job_with_log(self):
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_fixture(Path(temp))
            store.update("CHILD", config={"downstream": {"module": "enrichment", "parent_job_id": "PARENT"}})
            with patch("backend.downstream._run_native", side_effect=RuntimeError("R failed")):
                run_downstream(store, "CHILD")
            self.assertEqual(store.read("CHILD")["status"], "failed")
            self.assertIn("R failed", (store.job_dir("CHILD") / "output/downstream_error.txt").read_text())

    def test_pdf_disguised_as_png_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_fixture(Path(temp))
            def fake(*args):
                result = self.fake_native(*args)
                (args[0].parent / result["units"][0]["images"][0]).write_bytes(b"%PDF")
                return result
            with patch("backend.downstream._run_native", side_effect=fake), self.assertRaisesRegex(RuntimeError, "PNG"):
                run_enrichment(store, "CHILD", "PARENT", {})

    def test_legacy_groups_and_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_fixture(Path(temp))
            parent = store.job_dir("PARENT")
            (parent / "plan.json").unlink()
            self.assertEqual(len(_comparison_units(parent)), 2)
            (parent / "plan.json").write_text(json.dumps({"comparisons": [{"group": "g"}, {"group": "g"}]}))
            self.assertEqual(len(_comparison_units(parent)), 1)

    def test_species_detection_is_not_silent_mouse_fallback(self):
        self.assertEqual(_detect_species({}, {"reference": {"species": "human"}}), "hg38")
        with self.assertRaises(ValueError):
            _detect_species({}, {})

    def test_unsafe_tokens_do_not_collide(self):
        self.assertNotEqual(_safe_token("a b"), _safe_token("a_b"))
        self.assertNotIn("/", _safe_token("../a"))

    def test_parser_rejects_invalid_numbers(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "SE.dpsi"
            path.write_text("event_id\tdpsi\tp_value\nG1;SE:chr1:1-2\t.2\t.01\nG2;SE:chr1:1-2\tbad\t.01\nG3;SE:chr1:1-2\tnan\t.01\nG4;SE:chr1:1-2\t.2\t2\n")
            self.assertEqual([r["gene_id"] for r in _load_events_file(path, "SE")], ["G1"])

    def test_frontend_bp_only_no_motif_or_tables(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("index.html", "downstream.js", "i18n.js"):
            self.assertNotIn("motif", (root / name).read_text(encoding="utf-8").lower())
        html = (root / "index.html").read_text(encoding="utf-8")
        for value in ("GO_MF", "GO_CC", 'value="KEGG"'):
            self.assertNotIn(value, html)
        self.assertNotIn("renderTable", (root / "downstream.js").read_text(encoding="utf-8"))

    def test_api_rejects_bad_parameters_before_creating_jobs(self):
        from backend.server import ASTKHandler
        for payload in (
            {"module": "motif"}, {"module": "enrichment", "params": {"mode": "invalid"}},
            {"module": "enrichment", "params": {"database": "GO_CC"}},
            {"module": "enrichment", "params": {"pvalue": "nan"}},
        ):
            with self.subTest(payload=payload):
                handler = object.__new__(ASTKHandler)
                handler.read_json_body = Mock(return_value=payload)
                handler.send_json = Mock()
                handler.create_downstream_job("PARENT")
                self.assertEqual(handler.send_json.call_args.args[1], 400)
