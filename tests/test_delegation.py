import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import contracts
import model_routes

REAL = Path(__file__).resolve().parents[1]


class DelegationTest(unittest.TestCase):
    def test_tasks_route_to_expected_products(self) -> None:
        expected = {"literature-search": "Antigravity", "candidate-generation": "Antigravity",
                    "novelty-search": "Antigravity", "implementation": "Codex",
                    "formula-derivation": "Codex", "paper-writing": "Codex",
                    "result-analysis": "GPT Pro / Ultra"}
        for task, product in expected.items():
            self.assertEqual(model_routes.delegation_route(REAL, task)["preferred_product"], product)
        with self.assertRaises(contracts.ProjectError):
            model_routes.delegation_route(REAL, "train-model")

    def test_every_task_has_a_complete_procedure(self) -> None:
        for task, spec in model_routes.DELEGATION.items():
            self.assertEqual(set(spec), set(model_routes.FIELDS), task)
            for key in ("send", "withhold", "architect_checks"):
                self.assertTrue(spec[key] and all(isinstance(x, str) and x for x in spec[key]), (task, key))
            for key in ("trigger", "call", "prompt", "returns", "next_step", "on_failure"):
                self.assertTrue(spec[key].strip(), (task, key))

    def test_log_records_fingerprints_and_enforces_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "configs").mkdir()
            (root / ".aris").mkdir()
            (root / "configs/models.json").write_text((REAL / "configs/models.json").read_text())
            policy = json.loads((root / "configs/models.json").read_text())
            policy["policy"]["max_review_calls"] = 1
            (root / "configs/models.json").write_text(json.dumps(policy))
            (root / "p.md").write_text("prompt")
            (root / "r.md").write_text("response")
            entry = model_routes.log_delegation(root, "implementation", Path("p.md"), Path("r.md"), {})
            self.assertEqual(entry["actual_identity"], "unknown")
            self.assertEqual(len(entry["response"]["sha256"]), 64)
            with self.assertRaisesRegex(contracts.ProjectError, "budget"):
                model_routes.log_delegation(root, "implementation", Path("p.md"), Path("r.md"), {})


if __name__ == "__main__":
    unittest.main()
