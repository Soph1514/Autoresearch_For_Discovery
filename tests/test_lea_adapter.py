import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from the_pigeon_holes.formalization.lea import formalize


class LeaAdapterTests(unittest.TestCase):
    def run_adapter(self, root, process, response=True):
        checkout = root / "lea-prover"
        (checkout / "lea").mkdir(parents=True)
        (checkout / "lea/cli.py").touch()
        project = root / "lean"
        (project / ".lake/packages").mkdir(parents=True)
        (project / "lean-toolchain").write_text("leanprover/lean4:v4.19.0")
        (project / "lake-manifest.json").write_text(json.dumps({
            "name": "reference", "packages": [{"name": "mathlib", "url": "https://example.org/mathlib", "rev": "abc"}]
        }))
        (project / "Reference.lean").write_text("-- private reference")
        output = root / "output"
        output.mkdir()

        def communicate(task, timeout):
            self.assertIn("Problem statement:\noptimize a selection", task)
            if response:
                (output / "lea_workspace/Generated.lean").write_text(
                    "namespace Generated\ndef feasible : Prop := True\nend Generated\n"
                )

        process.communicate.side_effect = communicate
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout="revision\n")), \
             patch("subprocess.Popen", return_value=process) as launch:
            result = formalize(
                lea_root=checkout, task="formalize", statement="optimize a selection",
                lean_project=project, output=output, model="provider/model",
                max_turns=3, timeout=10, lake=sys.executable,
            )
        command = launch.call_args.args[0]
        self.assertIn("lea", command)
        self.assertIn("--config", command)
        self.assertEqual(result, (output / "lea_workspace/Generated.lean").resolve())
        self.assertFalse((output / "lea_workspace/Reference.lean").exists())
        self.assertFalse((output / "lea_workspace/.lake/build").exists())
        self.assertIn("def feasible", result.read_text())
        config = json.loads((output / "lea_config.json").read_text())
        self.assertNotIn("bash", config["agent"]["tools"])

    def test_collects_output_without_treating_it_as_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            self.run_adapter(Path(directory), Mock(returncode=0))

    def test_task_is_problem_agnostic(self):
        task = (Path(__file__).parents[1] / "problems/lea_task.txt").read_text()
        self.assertNotIn("SimpleGraph", task)
        self.assertNotIn("knapsack", task.lower())

    def test_failed_lea_run_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(RuntimeError, "status 1"):
            self.run_adapter(Path(directory), Mock(returncode=1))

    def test_missing_output_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(RuntimeError, "did not produce"):
            self.run_adapter(Path(directory), Mock(returncode=0), response=False)
