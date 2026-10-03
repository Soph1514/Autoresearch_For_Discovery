import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "src/the_pigeon_holes/formalization/validate.py"


class KnapsackValidationTest(unittest.TestCase):
    def test_generated_matches_reference_without_cheating(self):
        problem = Path(__file__).resolve().parent
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(problem)],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
