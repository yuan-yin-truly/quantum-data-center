"""Meaningful adversarial examples for the submitted-layout contract."""

import json
import math
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geometry import validate_layout
from verify_submission import verify
SPEC = json.loads((ROOT / "challenge_spec.json").read_text())
BASE = json.loads((ROOT / "random_layout.json").read_text())["random_layout"]["placements_mm"]


class ConstraintCases(unittest.TestCase):
    def check(self, payload, expected, phrase=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "submission.json"
            path.write_text(json.dumps(payload))
            result = verify(path, ROOT / "challenge_spec.json")
            self.assertIs(result["passed"], expected)
            if phrase:
                self.assertIn(phrase, result["reason"])
            return result

    def test_baseline_and_legal_explicit_path(self):
        result = self.check({"placements_mm": BASE}, True)
        self.assertEqual(len(result["links"]), 8)
        route = result["links"]["P0"]["route_grid"]
        self.check({"placements_mm": BASE, "wire_routes_grid": {"P0": route}}, True)

    def test_placement_validation(self):
        self.check({"placements_mm": {**BASE, "G0": [0, 0]}}, False, "edge clearance")
        self.check({"placements_mm": {**BASE, "H0": BASE["G0"]}}, False, "clearance")
        self.check({"placements_mm": {**BASE, "G0": [math.nan, 2]}}, False, "invalid JSON")
        self.check({"placements_mm": {**BASE, "G0": [True, 2]}}, False, "finite")
        self.check({"placements_mm": {"G0": [3, 4]}}, False, "exactly")

    def test_bandwidth_edges_reach_and_total_budget(self):
        center = SPEC["example_layouts_mm"]["ring_center"]
        self.check({"placements_mm": {**center, "H3": [21., 15.]}}, False, "die-edge capacity")
        spread = SPEC["example_layouts_mm"]["ring_spread"]
        self.check({"placements_mm": {**spread, "G2": [35.5, 29.]}}, False, "exceeds")
        path = validate_layout(SPEC, spread)["routes"]["P0"]["path_grid"]
        detour = [path[0], [path[0][0]+1, path[0][1]], path[0]] + path[1:]
        self.check({"placements_mm": spread, "wire_routes_grid": {"P0": detour}},
                   False, "total bandwidth-weighted")

    def test_route_format_obstacles_and_endpoints(self):
        self.check({"placements_mm": BASE, "wire_routes_grid": {"UNKNOWN": [[0, 0]]}},
                   False, "unknown")
        self.check({"placements_mm": BASE, "wire_routes_grid": {"P0": [[0, 0]]}},
                   False, "must start")
        route = validate_layout(SPEC, BASE)["routes"]["P1"]["path_grid"]
        self.check({"placements_mm": BASE, "wire_routes_grid": {"P1": [route[0], route[-1]]}},
                   False, "adjacent")
        self.check({"placements_mm": BASE, "wire_routes_grid": {"P0": [[True, 0]]}},
                   False, "integer")
        self.check({"placements_mm": BASE, "wire_routes_grid": {"P0": route * 50}},
                   False, "track cells")


if __name__ == "__main__":
    unittest.main()
