"""Synthetic offline batch reviews; no reviewer, model, training or data access."""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import contracts
import evidence
import gates
import review_batch
import test_workflow as workflow


class ReviewBatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = workflow.WorkflowTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.actor = {"actor_type": "human", "person": "Synthetic operator", "identity_source": "synthetic fixture only"}
        self.reviewer = {"provider": "fixture", "model": "synthetic-reviewer", "model_family": "B", "identity_source": "synthetic fixture only"}
        self.fixture.protocol["idea_id"] = "baseline"
        self.fixture.contract_path = "contracts/baseline/v1.yaml"
        workflow.dump(self.root / self.fixture.contract_path, self.fixture.protocol)
        self.fixture.freeze()
        self.fixture.job.update(idea_id="baseline", contract=self.fixture.contract_path, executor_identity=self.actor)
        (self.root / "baseline.md").write_text("Synthetic source, no scientific result.\n")
        workflow.dump(self.root / "configs/research.json", {"baseline": {"paper_source": "baseline.md"}})
        self.policy(None)
        self.batch = self.root / "batch"
        self.results = self.batch / "RESULTS.json"

    def policy(self, limit):
        workflow.dump(self.root / "configs/models.json", {"policy": {"max_review_calls": limit, "max_review_rounds": 2}})

    def jobs(self, count=2):
        for number in range(count):
            ref = f"experiments/phase2/job-{number:02}.json"
            job = copy.deepcopy(self.fixture.job)
            job.update(task_id=f"fixture-{number}", command=["{python}", "examples/toy/train.py", "--job", ref])
            workflow.dump(self.root / ref, job)
        workflow.dump(self.root / "experiments/phase2/job-params.json", {"operator_fields": ["environment_id", "resource_id", "executor_identity"]})

    def prepare(self, count=2):
        self.jobs(count)
        return review_batch.prepare(self.root, "baseline", "experiments/phase2/*.json", self.batch)

    def results_for(self, index):
        values = contracts.load(self.batch / "results-template.json")
        for value in values.values():
            value.update(completion="complete", verdict="PASS", fresh_context=True,
                         actual_identity=self.reviewer, raw_response_file="evidence/response.txt",
                         identity_evidence_file="evidence/identity.txt")
        for row in index["packages"]:
            manifest = contracts.load(self.batch / row["package_path"] / "manifest.json")
            values[row["package_id"]]["direct_reads"] = [entry["path"] for entry in manifest["files"]]
        (self.batch / "evidence").mkdir()
        (self.batch / "evidence/response.txt").write_text("Synthetic full session response; no reviewer was invoked.\n")
        (self.batch / "evidence/identity.txt").write_text("Synthetic identity evidence, test only.\n")
        workflow.dump(self.results, values)
        return values

    def receipts(self):
        return list((self.root / "reviews/receipts").glob("*/receipt.json"))

    def import_single(self, package, result, name="single-result.json"):
        path = self.batch / name
        workflow.dump(path, result)
        return evidence.import_review(self.root, package, path)

    def test_prepare_calls_official_code_review_path_and_preserves_packages(self):
        self.jobs()
        with mock.patch.object(evidence, "context_pack", wraps=evidence.context_pack) as official:
            index = review_batch.prepare(self.root, "baseline", "experiments/phase2/*.json", self.batch)
        self.assertEqual(official.call_count, 2)
        self.assertEqual(len(index["packages"]), 2)
        self.assertEqual(index["skipped_metadata"], ["experiments/phase2/job-params.json"])
        for row in index["packages"]:
            self.assertEqual(len(row["binding_sha256"]), 64)
            original = self.root / row["source_package_path"]
            package = self.batch / row["package_path"]
            for path in original.rglob("*"):
                if path.is_file():
                    self.assertEqual(path.read_bytes(), (package / path.relative_to(original)).read_bytes())
            self.assertEqual(gates.digest(package / "manifest.json"), row["package_manifest_sha256"])

    def test_all_sixty_import_via_existing_logic_and_each_receipt_passes_binding_gate(self):
        index = self.prepare(60)
        self.results_for(index)
        with mock.patch.object(evidence, "import_review", wraps=evidence.import_review) as official:
            report = review_batch.import_batch(self.root, self.batch, self.results)
        self.assertEqual(official.call_count, 60)
        self.assertEqual(report["status"], "imported")
        self.assertEqual(len(self.receipts()), 60)
        for row in report["receipts"]:
            job = contracts.load(self.root / row["job_path"])
            gates.check_receipt(self.root, row["receipt_path"], "code-review", job)
            receipt = contracts.load(self.root / row["receipt_path"])
            self.assertEqual(receipt["round"], 1)
            self.assertEqual(receipt["independence"], "cross-family")
            self.assertEqual((self.root / receipt["raw_response"]["path"]).read_bytes(), (self.batch / "evidence/response.txt").read_bytes())
            self.assertEqual((self.root / receipt["identity_evidence"]["path"]).read_bytes(), (self.batch / "evidence/identity.txt").read_bytes())

    def test_every_operator_field_is_preflighted_before_any_package_is_created(self):
        for field in ("environment_id", "resource_id", "executor_identity"):
            with self.subTest(field=field):
                self.jobs()
                path = self.root / "experiments/phase2/job-01.json"
                job = contracts.load(path); job[field] = None; workflow.dump(path, job)
                with mock.patch.object(evidence, "context_pack") as official, self.assertRaisesRegex(contracts.ProjectError, field):
                    review_batch.prepare(self.root, "baseline", "experiments/phase2/*.json", self.batch)
                official.assert_not_called()
                self.assertFalse(self.batch.exists())

    def test_unknown_identity_and_missing_registration_are_refused(self):
        self.jobs()
        path = self.root / "experiments/phase2/job-01.json"
        job = contracts.load(path)
        job["executor_identity"] = {"provider": "unknown"}; workflow.dump(path, job)
        with self.assertRaisesRegex(contracts.ProjectError, "executor_identity"):
            review_batch.prepare(self.root, "baseline", "experiments/phase2/*.json", self.batch)
        self.jobs()
        job = contracts.load(path); job["environment_id"] = "unregistered"; workflow.dump(path, job)
        with self.assertRaisesRegex(contracts.ProjectError, "resource binding missing"):
            review_batch.prepare(self.root, "baseline", "experiments/phase2/*.json", self.batch)
        self.assertFalse(self.batch.exists())

    def test_no_jobs_and_existing_output_are_refused(self):
        with self.assertRaisesRegex(contracts.ProjectError, "no jobs"):
            review_batch.prepare(self.root, "baseline", "missing/*.json", self.batch)
        self.prepare()
        with self.assertRaisesRegex(contracts.ProjectError, "already exists"):
            review_batch.prepare(self.root, "baseline", "experiments/phase2/*.json", self.batch)

    def test_missing_extra_aggregate_and_duplicate_results_are_refused_before_import(self):
        index = self.prepare()
        valid = self.results_for(index)
        missing = dict(valid); missing.pop(next(iter(missing)))
        for invalid in (missing, dict(valid, extra={}), {"verdict": "PASS"}):
            with self.subTest(keys=list(invalid)):
                workflow.dump(self.results, invalid)
                with mock.patch.object(evidence, "import_review") as official, self.assertRaisesRegex(contracts.ProjectError, "exactly one result"):
                    review_batch.import_batch(self.root, self.batch, self.results)
                official.assert_not_called()
        key = next(iter(valid))
        self.results.write_text('{'+json.dumps(key)+':{},'+json.dumps(key)+':{}}')
        with self.assertRaisesRegex(contracts.ProjectError, "Duplicate JSON key"):
            review_batch.import_batch(self.root, self.batch, self.results)
        self.assertFalse(self.receipts())

    def test_late_wrong_binding_or_manifest_hash_refuses_entire_result_set(self):
        index = self.prepare()
        valid = self.results_for(index)
        last = index["packages"][-1]["package_id"]
        for field in ("binding_sha256", "package_manifest_sha256"):
            invalid = copy.deepcopy(valid); invalid[last][field] = "0" * 64
            workflow.dump(self.results, invalid)
            with mock.patch.object(evidence, "import_review") as official, self.assertRaisesRegex(contracts.ProjectError, "hash binding mismatch"):
                review_batch.import_batch(self.root, self.batch, self.results)
            official.assert_not_called()
        self.assertFalse(self.receipts())

    def test_missing_or_extra_package_directories_are_refused_before_import(self):
        index = self.prepare()
        self.results_for(index)
        package = self.batch / index["packages"][-1]["package_path"]
        moved = self.batch / "saved-package"
        package.rename(moved)
        with mock.patch.object(evidence, "import_review") as official, self.assertRaisesRegex(contracts.ProjectError, "package directories are missing or extra"):
            review_batch.import_batch(self.root, self.batch, self.results)
        official.assert_not_called()
        moved.rename(package)
        (self.batch / "packages/unindexed-package").mkdir()
        with mock.patch.object(evidence, "import_review") as official, self.assertRaisesRegex(contracts.ProjectError, "package directories are missing or extra"):
            review_batch.import_batch(self.root, self.batch, self.results)
        official.assert_not_called()
        self.assertFalse(self.receipts())

    def test_swapped_package_results_and_unbound_result_are_refused(self):
        index = self.prepare()
        valid = self.results_for(index)
        first, last = list(valid)
        invalid = {first: valid[last], last: valid[first]}
        workflow.dump(self.results, invalid)
        with self.assertRaisesRegex(contracts.ProjectError, "hash binding mismatch"):
            review_batch.import_batch(self.root, self.batch, self.results)
        invalid = copy.deepcopy(valid); invalid[last].pop("binding_sha256")
        workflow.dump(self.results, invalid)
        with self.assertRaisesRegex(contracts.ProjectError, "hash binding mismatch"):
            review_batch.import_batch(self.root, self.batch, self.results)
        self.assertFalse(self.receipts())

    def test_changed_job_and_packaged_material_are_refused(self):
        index = self.prepare()
        self.results_for(index)
        row = index["packages"][-1]
        path = self.root / row["job_path"]; saved = path.read_bytes()
        job = contracts.load(path); job["command"].append("--changed"); workflow.dump(path, job)
        with self.assertRaisesRegex(contracts.ProjectError, "Current job binding changed"):
            review_batch.import_batch(self.root, self.batch, self.results)
        path.write_bytes(saved)
        manifest = contracts.load(self.batch / row["package_path"] / "manifest.json")
        (self.batch / row["package_path"] / manifest["files"][-1]["packaged_path"]).write_text("changed")
        with self.assertRaisesRegex(contracts.ProjectError, "material/source changed"):
            review_batch.import_batch(self.root, self.batch, self.results)
        self.assertFalse(self.receipts())

    def test_numeric_budget_is_per_receipt_and_batch_cannot_bypass_it(self):
        index = self.prepare()
        values = self.results_for(index)
        self.policy(1)
        with self.assertRaisesRegex(contracts.ProjectError, "budget cannot cover"):
            review_batch.import_batch(self.root, self.batch, self.results)
        self.assertFalse(self.receipts())
        first, second = index["packages"]
        self.import_single(self.batch / first["package_path"], values[first["package_id"]])
        with self.assertRaisesRegex(contracts.ProjectError, "Global review call budget exhausted"):
            self.import_single(self.batch / second["package_path"], values[second["package_id"]])
        self.assertEqual(len(self.receipts()), 1)

    def test_numeric_budget_exactly_equal_batch_size_succeeds(self):
        index = self.prepare()
        self.results_for(index)
        self.policy(2)
        review_batch.import_batch(self.root, self.batch, self.results)
        self.assertEqual(len(self.receipts()), 2)

    def test_same_binding_has_two_rounds_and_cannot_reset_or_duplicate(self):
        index = self.prepare(1)
        values = self.results_for(index)
        row = index["packages"][0]
        package = self.batch / row["package_path"]
        result = values[row["package_id"]]
        self.import_single(package, result)
        with self.assertRaisesRegex(contracts.ProjectError, "already imported"):
            self.import_single(package, result)
        second = evidence.context_pack(self.root, "baseline", "code-review", job_ref=row["job_path"])
        manifest = contracts.load(second / "manifest.json")
        result = dict(result, direct_reads=[x["path"] for x in manifest["files"]])
        with self.assertRaisesRegex(contracts.ProjectError, "Review round must be 2"):
            self.import_single(second, result)
        result["round"] = 2
        self.import_single(second, result)
        third = evidence.context_pack(self.root, "baseline", "code-review", job_ref=row["job_path"])
        manifest = contracts.load(third / "manifest.json")
        result.update(round=3, direct_reads=[x["path"] for x in manifest["files"]])
        with self.assertRaisesRegex(contracts.ProjectError, "round budget exhausted"):
            self.import_single(third, result)
        self.assertEqual(len(self.receipts()), 2)

    def test_non_job_review_round_counter_is_unchanged(self):
        index = self.prepare(1)
        base = next(iter(self.results_for(index).values()))
        workflow.dump(self.root / "idea-stage/ideas/baseline.json", {"hypothesis": "Synthetic", "proposer_identity": self.actor})
        for round_no in (1, 2):
            package = evidence.context_pack(self.root, "baseline", "idea-review")
            manifest = contracts.load(package / "manifest.json")
            result = dict(base, round=1, direct_reads=[x["path"] for x in manifest["files"]],
                          scorecard={"scores": {key: 3 for key in ("novelty", "feasibility", "compatibility", "complexity", "expected_gain")},
                                     "recommendation": "go", "reasons": ["synthetic only"], "revision_requests": []})
            if round_no == 2:
                with self.assertRaisesRegex(contracts.ProjectError, "Review round must be 2"):
                    self.import_single(package, result)
            result["round"] = round_no
            self.import_single(package, result)
        self.assertEqual(len(self.receipts()), 2)

    def test_same_family_stays_provisional_and_does_not_pass_gate(self):
        self.fixture.job["executor_identity"] = {**self.reviewer, "model": "synthetic-implementer"}
        index = self.prepare(1)
        self.results_for(index)
        report = review_batch.import_batch(self.root, self.batch, self.results)
        row = report["receipts"][0]
        self.assertEqual(row["acceptance_status"], "provisional")
        with self.assertRaisesRegex(contracts.ProjectError, "independent"):
            gates.check_receipt(self.root, row["receipt_path"], "code-review", contracts.load(self.root / row["job_path"]))

    def test_identity_direct_read_and_raw_response_checks_still_apply(self):
        index = self.prepare(1)
        valid = self.results_for(index)
        package_id = index["packages"][0]["package_id"]
        package = self.batch / index["packages"][0]["package_path"]
        for field, value, error in (("actual_identity", {}, "identities"), ("executor_identity", {}, "Executor identity differs"),
                                     ("direct_reads", [], "direct reads"), ("raw_response_file", "absent.txt", "Missing evidence"),
                                     ("identity_evidence_file", "absent.txt", "Missing evidence"), ("fresh_context", False, "Fresh review context")):
            with self.subTest(field=field), self.assertRaisesRegex(contracts.ProjectError, error):
                result = dict(valid[package_id]); result[field] = value
                self.import_single(package, result)
        self.assertFalse(self.receipts())

    def test_import_reports_partial_failure_preserves_receipts_and_refuses_reimport(self):
        index = self.prepare()
        values = self.results_for(index)
        values[index["packages"][-1]["package_id"]]["direct_reads"] = []
        workflow.dump(self.results, values)
        with self.assertRaisesRegex(contracts.ProjectError, "preserve receipts.json"):
            review_batch.import_batch(self.root, self.batch, self.results)
        report = contracts.load(self.batch / "receipts.json")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(len(report["receipts"]), 1)
        self.assertEqual(len(self.receipts()), 1)
        with self.assertRaisesRegex(contracts.ProjectError, "already attempted"):
            review_batch.import_batch(self.root, self.batch, self.results)

    def test_binding_hash_is_canonical_and_sensitive_to_job_changes(self):
        self.assertIsNone(evidence.execution_binding_hash(None))
        first = {"job": {"seed": 7}, "schema_version": 1}
        self.assertEqual(evidence.execution_binding_hash(first), evidence.execution_binding_hash(dict(reversed(list(first.items())))))
        self.assertNotEqual(evidence.execution_binding_hash(first), evidence.execution_binding_hash({**first, "job": {"seed": 8}}))

    def test_cli_prepare_and_import(self):
        self.jobs(1)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(review_batch.main(["--root", str(self.root), "prepare", "--idea", "baseline", "--jobs-glob", "experiments/phase2/*.json", "--out", str(self.batch)]), 0)
        self.results_for(contracts.load(self.batch / "index.json"))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(review_batch.main(["--root", str(self.root), "import", "--dir", str(self.batch), "--results", str(self.results)]), 0)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(review_batch.main(["--root", str(self.root), "import", "--dir", str(self.batch), "--results", str(self.results)]), 2)


if __name__ == "__main__":
    unittest.main()
