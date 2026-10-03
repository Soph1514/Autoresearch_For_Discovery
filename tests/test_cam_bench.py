import json
import tempfile
import unittest
from pathlib import Path

from the_pigeon_holes import pull_cam_bench


class CAMBenchTests(unittest.TestCase):
    def test_reads_problem_by_directory_name(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "CAM-Bench.json"
            mapping = Path(directory) / "benchmark_map.json"
            mapping.write_text(json.dumps({"constant_fitting": "Convex Optimization 6.2-(a)"}))
            cache.write_text(json.dumps([{
                "id": 7,
                "book": "Convex Optimization",
                "exercise": "6.2-(a)",
                "informal_statement": "general problem",
                "formal_statement": "theorem reference : True := by sorry",
            }]))
            problem = pull_cam_bench("constant_fitting", cache, mapping)
            self.assertEqual(problem.name, "Convex Optimization 6.2-(a)")
            self.assertEqual(problem.informal_statement, "general problem")
            self.assertIn("theorem reference", problem.formal_statement)

    def test_rejects_unmapped_problem(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "CAM-Bench.json"
            mapping = Path(directory) / "benchmark_map.json"
            mapping.write_text("{}")
            cache.write_text("[]")
            with self.assertRaisesRegex(ValueError, "No CAM-Bench mapping for problem: missing"):
                pull_cam_bench("missing", cache, mapping)
