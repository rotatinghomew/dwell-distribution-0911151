from copy import deepcopy
from pathlib import Path
import json
import unittest

from dwell_distribution.data import load_bundle, visible_snapshot
from dwell_distribution.product import *


class ProductTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.snapshot = visible_snapshot(load_bundle(root / "fixtures/bundle.json"), "2026-01-01")

    def test_overview_is_finite_and_preserves_sources(self):
        original = deepcopy(self.snapshot)
        result = summarize(self.snapshot)
        self.assertTrue(result)
        self.assertIn("interpretation", result)
        json.dumps(result, allow_nan=False)
        self.assertEqual(self.snapshot, original)

    def test_histograms_preserve_observation_count(self):
        rows = raw_histograms(self.snapshot)
        self.assertEqual(sum(point["count"] for row in rows for point in row["bins"]), len(self.snapshot["tables"]["visits"]))

    def test_reference_selection_probabilities_validated(self):
        self.snapshot["tables"]["paired_timing"][0]["inclusion_probability"] = 0
        with self.assertRaises(ValueError):
            paired_overview(self.snapshot)
