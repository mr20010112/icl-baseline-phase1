"""Imported reviews bind actual snapshot execution; identities are synthetic."""
import copy
from pathlib import Path
import unittest

import test_workflow as workflow
from test_workflow import dump
import contracts
import evidence
import gates
import runtime


class ReviewExecutionFlowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = workflow.WorkflowTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.actor = {"provider": "fixture", "model": "implementer", "model_family": "A", "identity_source": "synthetic test only"}
        self.proposer = {**self.actor, "model": "proposer", "model_family": "C"}
        self.reviewer = {**self.actor, "model": "reviewer", "model_family": "B"}
        self.fixture.job["executor_identity"] = self.actor
        (self.root / "baseline.md").write_text("Synthetic baseline source; no scientific result.\n")
        dump(self.root / "configs/research.json", {"selected_idea": "toy-linear", "candidate_count": 1, "baseline": {"paper_source": "baseline.md"}})
        dump(self.root / "idea-stage/ideas/toy-linear.json", {"hypothesis": self.fixture.protocol["hypothesis"], "proposer_identity": self.proposer})
        self.fixture.freeze()

    def review(self, purpose):
        dump(self.root / "experiments/job.json", self.fixture.job)
        package = evidence.context_pack(self.root, "toy-linear", purpose,
                                        job_ref="experiments/job.json" if purpose == "code-review" else None)
        manifest = contracts.load(package / "manifest.json")
        result = contracts.load(package / "result-template.json")
        result.update(completion="complete", verdict="PASS", fresh_context=True,
                      actual_identity=self.reviewer,
                      direct_reads=[x["path"] for x in manifest["files"]],
                      raw_response_file="response.txt", identity_evidence_file="identity.txt")
        if purpose == "idea-review":
            result["scorecard"] = {"scores": {key: 3 for key in ("novelty", "feasibility", "compatibility", "complexity", "expected_gain")}, "recommendation": "go", "reasons": ["Synthetic fixture only"], "revision_requests": []}
        (package / "response.txt").write_text("Synthetic review; no external model was invoked.\n")
        (package / "identity.txt").write_text("Synthetic provider identity fixture.\n")
        dump(package / "result.json", result)
        return evidence.import_review(self.root, package, package / "result.json").relative_to(self.root).as_posix()

    def test_imported_code_review_binds_launch_and_rejects_changed_arguments(self):
        receipt = self.review("code-review")
        self.fixture.job["code_review_receipt"] = receipt
        gates.check_receipt(self.root, receipt, "code-review", self.fixture.job)
        changed = copy.deepcopy(self.fixture.job)
        changed["command"] += ["--sleep", "1"]
        with self.assertRaisesRegex(contracts.ProjectError, "execution binding"):
            gates.check_receipt(self.root, receipt, "code-review", changed)
        result = self.fixture.run_job()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(Path(result["command"][1]), self.root / "runs/toy-001/code/examples/toy/train.py")

    def test_distinct_proposer_and_implementer_reviews_both_pass(self):
        idea_receipt = self.review("idea-review")
        code_receipt = self.review("code-review")
        job = {**self.fixture.job, "idea_review_receipt": idea_receipt, "code_review_receipt": code_receipt}
        gates.check_receipt(self.root, idea_receipt, "idea-review", job)
        gates.check_receipt(self.root, code_receipt, "code-review", job)


if __name__ == "__main__":
    unittest.main()
