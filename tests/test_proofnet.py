import unittest
from unittest.mock import patch

from the_pigeon_holes.formalization.proofnet import load_problems


class ProofNetTests(unittest.TestCase):
    @patch("datasets.load_dataset")
    def test_returns_one_problem_per_id(self, load_dataset):
        load_dataset.return_value = [
            {"id": "a", "nl_statement": "first"},
            {"id": "a", "nl_statement": "duplicate"},
            {"id": "b", "nl_statement": "second"},
        ]
        self.assertEqual([row["id"] for row in load_problems(limit=2)], ["a", "b"])
        load_dataset.assert_called_once_with("PAug/ProofNetVerif", split="valid")
