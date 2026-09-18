from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.cleanup import cleanup_expired_jobs
from backend.planner import InputError, native_comparison_label, prepare_job, safe_extract_zip
from backend.result_parser import parse_results
from backend.server import validate_analysis_files
from backend.visualization import filter_significant_dpsi, load_comparisons, prepare_heatmap_inputs


QUANT = "Name\tLength\tEffectiveLength\tTPM\tNumReads\nTX1\t1000\t800\t12.5\t10\n"


class PipelineTests(unittest.TestCase):
    def make_job(self, root: Path) -> Path:
        job_dir = root / "ASTK-TEST"
        input_dir = job_dir / "input"
        input_dir.mkdir(parents=True)
        for sample in ("e11_r1", "e11_r2", "e12_r1", "e13_r1"):
            quant = input_dir / "data" / "quant" / sample / "quant.sf"
            quant.parent.mkdir(parents=True, exist_ok=True)
            quant.write_text(QUANT, encoding="utf-8")
        (input_dir / "samples.csv").write_text(
            "sample_id,condition,quant_path,baseline,order\n"
            "e11_r1,E11.5,quant/e11_r1/quant.sf,true,1\n"
            "e11_r2,E11.5,quant/e11_r2/quant.sf,true,1\n"
            "e12_r1,E12.5,quant/e12_r1/quant.sf,false,2\n"
            "e13_r1,E13.5,quant/e13_r1/quant.sf,false,3\n",
            encoding="utf-8",
        )
        (job_dir / "job.json").write_text(
            json.dumps(
                {
                    "config": {
                        "species": "Mus musculus · mm10",
                        "comparison_mode": "baseline",
                        "event_type": "ALL",
                        "method": "empirical",
                        "p_value": 0.05,
                        "abs_dpsi": 0.1,
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return job_dir

    def test_planner_generates_astk_metadata_for_unequal_replicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = self.make_job(Path(temporary))
            plan = prepare_job(job_dir)
            metadata = json.loads((job_dir / "metadata" / "astk_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["sample_count"], 4)
            self.assertEqual(len(plan["comparisons"]), 2)
            self.assertEqual(len(metadata["E11_5_vs_E12_5"]["ctrl"]["samples"]), 2)
            self.assertEqual(len(metadata["E11_5_vs_E12_5"]["case"]["samples"]), 1)
            self.assertEqual(plan["comparisons"][0]["group"], "E11_5_vs_E12_5")
            self.assertIn("dsflow", plan["command"])
            self.assertIn("0.1", plan["command"])

    def test_planner_accepts_native_astk_csv_with_original_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = self.make_job(Path(temporary))
            input_dir = job_dir / "input"
            (input_dir / "facial_11.CSV").write_text(
                "group,condition,name,path,replicate\n"
                "facial_11.5_12,case,e12_r1,./salmon/quant/e12_r1/quant.sf,1\n"
                "facial_11.5_12,ctrl,e11_r1,./salmon/quant/e11_r1/quant.sf,1\n"
                "facial_11.5_13,case,e13_r1,./salmon/quant/e13_r1/quant.sf,1\n"
                "facial_11.5_13,ctrl,e11_r1,./salmon/quant/e11_r1/quant.sf,1\n",
                encoding="utf-8",
            )
            (input_dir / "samples.csv").unlink()

            plan = prepare_job(job_dir)
            metadata = json.loads((job_dir / "metadata" / "astk_metadata.json").read_text(encoding="utf-8"))
            metadata_csv = (job_dir / "metadata" / "astk_metadata.csv").read_text(encoding="utf-8")

            self.assertEqual(plan["input_format"], "astk")
            self.assertEqual(plan["sample_count"], 3)
            self.assertEqual([item["group"] for item in plan["comparisons"]], ["facial_11.5_12", "facial_11.5_13"])
            self.assertEqual(metadata["facial_11.5_12"]["ctrl"]["samples"][0]["name"], "e11_r1")
            self.assertEqual(metadata["facial_11.5_12"]["case"]["samples"][0]["name"], "e12_r1")
            self.assertTrue(metadata["facial_11.5_12"]["case"]["samples"][0]["path"].endswith("quant/e12_r1/quant.sf"))
            self.assertEqual(metadata_csv.splitlines()[0], "group,condition,name,path,replicate")

    def test_native_comparison_labels_use_sample_periods(self) -> None:
        control, treatment, label = native_comparison_label(
            "facial_11.5_12",
            {
                "ctrl": [{"name": "facial.11.5.Rep1"}, {"name": "facial.11.5.Rep2"}],
                "case": [{"name": "facial.12.5.Rep1"}, {"name": "facial.12.5.Rep2"}],
            },
        )
        self.assertEqual(control, "11.5")
        self.assertEqual(treatment, "12.5")
        self.assertEqual(label, "11.5 → 12.5")

    def test_significant_dpsi_filter_uses_astk_strict_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "events.dpsi"
            output = root / "filtered" / "events.sig.dpsi"
            source.write_text(
                "event_id\tdPSI\tp-value\n"
                "keep-up\t0.11\t0.24\n"
                "keep-down\t-0.11\t0.24\n"
                "p-boundary\t0.50\t0.25\n"
                "dpsi-boundary\t0.10\t0.01\n",
                encoding="utf-8",
            )
            count = filter_significant_dpsi(source, output, p_value=0.25, abs_dpsi=0.1)
            self.assertEqual(count, 2)
            self.assertEqual(output.read_text(encoding="utf-8").splitlines()[-1], "keep-down\t-0.11\t0.24")

    def test_heatmap_inputs_select_top_shared_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            analysis = root / "analysis"
            (analysis / "psi").mkdir(parents=True)
            (analysis / "dpsi").mkdir(parents=True)
            for index, group in enumerate(("g1", "g2"), 1):
                (analysis / "psi" / f"{group}_SE_c1.psi").write_text(
                    "event_id\ts1\ts2\n"
                    "e1\t0.1\t0.2\n"
                    "e2\t0.2\t0.3\n"
                    "e3\t0.3\t0.4\n",
                    encoding="utf-8",
                )
                (analysis / "psi" / f"{group}_SE_c2.psi").write_text(
                    "event_id\ts3\ts4\n"
                    "e1\t0.1\t0.2\n"
                    "e2\t0.2\t0.3\n"
                    "e3\t0.3\t0.4\n",
                    encoding="utf-8",
                )
                (analysis / "dpsi" / f"{group}_SE.dpsi").write_text(
                    "event_id\tdPSI\tp-value\n"
                    f"e1\t{0.1 * index}\t0.01\n"
                    f"e2\t{0.5 * index}\t0.01\n"
                    f"e3\t{0.2 * index}\t0.01\n",
                    encoding="utf-8",
                )
            comparisons = [{"group": "g1"}, {"group": "g2"}]
            outputs = prepare_heatmap_inputs(analysis, comparisons, "SE")
            self.assertEqual(len(outputs), 3)
            selected = outputs[0].read_text(encoding="utf-8").splitlines()[1:]
            self.assertEqual([row.split("\t", 1)[0] for row in selected], ["e2", "e3", "e1"])

    def test_visualization_recovers_period_labels_from_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = Path(temporary) / "ASTK-TEST"
            metadata = job_dir / "metadata"
            metadata.mkdir(parents=True)
            (metadata / "astk_metadata.json").write_text(
                json.dumps(
                    {
                        "facial_11.5_12": {
                            "ctrl": {"samples": [{"name": "facial.11.5.Rep1"}]},
                            "case": {"samples": [{"name": "facial.12.5.Rep1"}]},
                        }
                    }
                ),
                encoding="utf-8",
            )
            plan = {
                "comparisons": [
                    {
                        "group": "facial_11.5_12",
                        "control": "ctrl",
                        "treatment": "case",
                        "label": "facial_11.5_12",
                    }
                ]
            }

            comparisons = load_comparisons(job_dir, plan)

            self.assertEqual(comparisons[0]["control"], "11.5")
            self.assertEqual(comparisons[0]["treatment"], "12.5")
            self.assertEqual(comparisons[0]["label"], "11.5 → 12.5")

    def test_result_parser_summarizes_astk_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = self.make_job(Path(temporary))
            prepare_job(job_dir)
            analysis = job_dir / "output" / "analysis"
            (analysis / "psi").mkdir(parents=True)
            (analysis / "sig01").mkdir(parents=True)
            (analysis / "img" / "volcano").mkdir(parents=True)
            (analysis / "psi" / "E11_5_vs_E12_5_SE_c1.psi").write_text(
                "event_id\te11_r1\te11_r2\n"
                "GENE1;SE:chr1:10-20:30-40:+\t0.1\t0.2\n"
                "GENE2;SE:chr1:50-60:70-80:+\t0.4\t0.5\n",
                encoding="utf-8",
            )
            (analysis / "psi" / "E11_5_vs_E12_5_AF_c1.psi").write_text(
                "event_id\te11_r1\te11_r2\nGENE3;AF:chr1:10-20:30-40:+\t0.2\t0.3\n",
                encoding="utf-8",
            )
            (analysis / "sig01" / "E11_5_vs_E12_5_SE.sig.dpsi").write_text(
                "comparison_dPSI\tcomparison_p-val\n"
                "GENE1;SE:chr1:10-20:30-40:+\t0.25\t0.01\n"
                "GENE2;SE:chr1:50-60:70-80:+\t-0.15\t0.02\n",
                encoding="utf-8",
            )
            (analysis / "img" / "volcano" / "E11_5_vs_E12_5_SE.png").write_bytes(b"png")
            results = parse_results(job_dir)
            self.assertEqual(results["metrics"]["total_events"], 3)
            self.assertEqual(results["metrics"]["significant_events"], 2)
            self.assertEqual(results["metrics"]["sample_count"], 4)
            self.assertEqual(results["event_counts"]["SE"], 2)
            self.assertEqual(results["direction_counts"], {"up": 1, "down": 1})
            self.assertEqual(results["images"]["volcano"][0]["name"], "E11_5_vs_E12_5_SE")
            self.assertEqual(results["comparisons"][0]["control"], "E11.5")
            self.assertEqual(results["events"][0][3], "E11.5 → E12.5")
            self.assertEqual(results["reference"]["id"], "mm10-gencode-m25")

    def test_zip_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../outside.txt", "blocked")
            with self.assertRaises(InputError):
                safe_extract_zip(archive, root / "data")

    def test_command_upload_requires_zip_and_one_csv(self) -> None:
        validate_analysis_files([("quant.zip", b"zip"), ("samples.csv", b"csv")])
        validate_analysis_files([("quant.zip", b"zip"), ("facial_11.csv", b"csv")])
        with self.assertRaises(ValueError):
            validate_analysis_files([("samples.csv", b"csv")])
        with self.assertRaises(ValueError):
            validate_analysis_files([("quant.zip", b"zip"), ("facial_11.csv", b"csv"), ("extra.csv", b"csv")])
        with self.assertRaises(ValueError):
            validate_analysis_files([("quant.zip", b"zip"), ("metadata.txt", b"text")])

    def test_cleanup_removes_only_expired_finished_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            now = datetime(2026, 9, 17, tzinfo=timezone.utc)
            expired = root / "ASTK-EXPIRED"
            current = root / "ASTK-CURRENT"
            active = root / "ASTK-ACTIVE"
            pinned = root / "ASTK-PINNED"
            for directory in (expired, current, active, pinned):
                directory.mkdir()

            old_timestamp = (now - timedelta(days=8)).isoformat()
            current_timestamp = (now - timedelta(days=2)).isoformat()
            (expired / "job.json").write_text(
                json.dumps({"status": "completed", "updated_at": old_timestamp}), encoding="utf-8"
            )
            (current / "job.json").write_text(
                json.dumps({"status": "completed", "updated_at": current_timestamp}), encoding="utf-8"
            )
            (active / "job.json").write_text(
                json.dumps({"status": "running", "updated_at": old_timestamp}), encoding="utf-8"
            )
            (pinned / "job.json").write_text(
                json.dumps({"status": "completed", "updated_at": old_timestamp, "pinned": True}), encoding="utf-8"
            )

            removed = cleanup_expired_jobs(root, retention_days=7, now=now)

            self.assertEqual(removed, ["ASTK-EXPIRED"])
            self.assertFalse(expired.exists())
            self.assertTrue(current.exists())
            self.assertTrue(active.exists())
            self.assertTrue(pinned.exists())


if __name__ == "__main__":
    unittest.main()
