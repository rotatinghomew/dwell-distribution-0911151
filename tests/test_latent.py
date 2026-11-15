from copy import deepcopy
from pathlib import Path
import json
import math
import tempfile
import unittest

from dwell_distribution.client import ProductClient
from dwell_distribution.data import load_bundle, visible_snapshot
from dwell_distribution.latent import (
    calibration_report,
    latent_analysis,
    latent_interval,
    measurement_models,
    model_for,
)
from dwell_distribution.service import running_service
from dwell_distribution.store import ArtifactStore
from dwell_distribution.workflow import publish_latent_analysis, publish_overview


ROOT = Path(__file__).resolve().parents[1]


class IntervalTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = visible_snapshot(load_bundle(ROOT / "fixtures/bundle.json"), "2026-01-01")
        self.models = measurement_models(self.snapshot)

    def test_sensor_rounding_and_cap(self):
        model = model_for(self.models, "sensor", "r1")
        self.assertEqual(latent_interval(model, 35), (32.5, 37.5))
        lower, upper = latent_interval(model, 60)
        self.assertEqual(lower, 57.5)
        self.assertTrue(math.isinf(upper))
        model_r2 = model_for(self.models, "sensor", "r2")
        self.assertEqual(latent_interval(model_r2, 40), (35.0, 45.0))

    def test_gate_contract_model(self):
        model = model_for(self.models, "gate", "r1")
        self.assertEqual(latent_interval(model, 30), (29.5, 30.5))

    def test_interview_heaped_model(self):
        model = model_for(self.models, "interview", "r1")
        self.assertEqual(model["step"], 15.0)
        self.assertEqual(latent_interval(model, 30), (22.5, 37.5))
        self.assertEqual(latent_interval(model, 15), (7.5, 22.5))

    def test_invalid_records_rejected(self):
        model = model_for(self.models, "sensor", "r1")
        with self.assertRaises(ValueError):
            latent_interval(model, -1)
        with self.assertRaises(ValueError):
            latent_interval(model, 33)
        with self.assertRaises(ValueError):
            latent_interval(model, 65)
        with self.assertRaises(ValueError):
            model_for(self.models, "sensor", "unknown-rule")
        with self.assertRaises(ValueError):
            model_for(self.models, "drone", "r1")


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = visible_snapshot(load_bundle(ROOT / "fixtures/bundle.json"), "2026-01-01")
        self.models = measurement_models(self.snapshot)

    def test_invalid_selection_probability_rejected(self):
        self.snapshot["tables"]["paired_timing"][0]["inclusion_probability"] = 0
        with self.assertRaises(ValueError):
            calibration_report(self.snapshot, self.models)

    def test_mechanism_mismatch_rejected(self):
        pair = self.snapshot["tables"]["paired_timing"][0]
        pair["reference"] = pair["reference"] + 30.0
        with self.assertRaises(ValueError):
            calibration_report(self.snapshot, self.models)

    def test_report_uses_inverse_probability_weights(self):
        report = calibration_report(self.snapshot, self.models)
        self.assertEqual(report["pairs_used"], 60)
        self.assertEqual(set(report["methods"]), {"sensor", "gate", "interview"})
        for method_report in report["methods"].values():
            self.assertEqual(method_report["interval_coverage"], 1.0)
            self.assertGreater(method_report["effective_sample_size"], 0)
        limited = {item["center"] for item in report["reference_coverage_limits"]}
        self.assertEqual(limited, {"center-1", "center-3"})


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = visible_snapshot(load_bundle(ROOT / "fixtures/bundle.json"), "2026-01-01")

    def test_result_is_finite_and_preserves_snapshot(self):
        original = deepcopy(self.snapshot)
        result = latent_analysis(self.snapshot)
        json.dumps(result, allow_nan=False)
        self.assertEqual(self.snapshot, original)

    def test_strata_cover_all_visits_and_show_measurement_basis(self):
        result = latent_analysis(self.snapshot)
        center_strata = [row for row in result["strata"] if row["dimension"] == "center"]
        self.assertEqual(sum(row["visits"] for row in center_strata), len(self.snapshot["tables"]["visits"]))
        for row in result["strata"]:
            basis = row["measurement_basis"]
            self.assertEqual(sum(basis["records_by_method"].values()), row["visits"])
            self.assertEqual(sum(basis["records_by_rule"].values()), row["visits"])
            self.assertLessEqual(basis["capped_records"], row["visits"])

    def test_bounds_are_ranges_not_points(self):
        result = latent_analysis(self.snapshot)
        widths = [
            row["latent_median_minutes"]["upper"] - row["latent_median_minutes"]["lower"]
            for row in result["strata"]
        ]
        self.assertTrue(any(width > 0 for width in widths))
        for row in result["strata"]:
            self.assertLess(row["long_stay_proportion"]["lower"], row["long_stay_proportion"]["upper"])

    def test_comparisons_report_assumption_dependence(self):
        result = latent_analysis(self.snapshot)
        guide_rows = [row for row in result["comparisons"] if row["dimension"] == "guide"]
        self.assertTrue(guide_rows)
        for row in guide_rows:
            self.assertTrue(row["depends_on_extra_assumptions"])
            self.assertTrue(any("中心" in note for note in row["assumptions_needed"]))
        for row in result["comparisons"]:
            self.assertIn(row["supported_sign"], ("positive", "negative", "undetermined"))
            self.assertEqual(row["depends_on_extra_assumptions"], bool(row["assumptions_needed"]))

    def test_center_pairs_respect_guide_composition(self):
        result = latent_analysis(self.snapshot)
        pairs = {(row["a"]["center"], row["b"]["center"]) for row in result["comparisons"] if row["dimension"] == "center"}
        self.assertEqual(pairs, {("center-0", "center-2"), ("center-1", "center-3")})

    def test_threshold_is_validated(self):
        with self.assertRaises(ValueError):
            latent_analysis(self.snapshot, long_stay_threshold=0)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        bundle = load_bundle(ROOT / "fixtures/bundle.json")
        cls.store = ArtifactStore(str(Path(cls.directory.name) / "state.sqlite3"), bundle.get("policy"))
        cls.running = running_service(bundle, cls.store)
        cls.client = ProductClient(cls.running.__enter__())

    @classmethod
    def tearDownClass(cls):
        cls.running.__exit__(None, None, None)
        cls.store.close()
        cls.directory.cleanup()

    def test_latent_artifact_roundtrip_keeps_observed_overview_separate(self):
        published = publish_latent_analysis(self.client, "2026-01-01", "latent-roundtrip")
        self.assertEqual(published["artifact"]["method"], "latent-dwell-bounds-v1")
        restored = self.client.artifact(published["artifact_id"])
        self.assertEqual(restored, published["artifact"])
        overview = publish_overview(self.client, "2026-01-01", "observed-roundtrip")
        self.assertEqual(overview["artifact"]["method"], "observed-overview-v1")
        self.assertIn("histograms", overview["artifact"]["result"])
        self.assertNotEqual(published["artifact_id"], overview["artifact_id"])


if __name__ == "__main__":
    unittest.main()
