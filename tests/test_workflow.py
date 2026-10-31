"""Offline behavioral tests. All run records are isolated in temporary projects."""
from __future__ import annotations

import copy
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools"))
import contracts
import evidence
import gates
import runtime


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="auto-research-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "examples/toy").mkdir(parents=True)
        shutil.copyfile(PROJECT / "examples/toy/train.py", self.root / "examples/toy/train.py")
        (self.root / "data.txt").write_text("synthetic generator y=2x+1, independent splits; toy only\n")
        (self.root / "witness.txt").write_text("Local CPU synthetic fixture; produced inside isolated test\n")
        self.hyperparameters = {"n_train": 64, "n_test": 32, "epochs": 100, "learning_rate": 0.05, "noise_std": 0.02}
        self.config = {"kind": "toy", "dataset_id": "toy-data", "split": {"train": "synthetic/train", "test": "synthetic/test"}, "seed": 7, "hyperparameters": self.hyperparameters}
        dump(self.root / "experiments/config.json", self.config)
        self.protocol = {
            "idea_id": "toy-linear", "version": 1, "kind": "toy", "question": "Does the engineering evidence chain run on CPU?",
            "hypothesis": "Seeded CPU optimization can fit a known synthetic linear law.",
            "method": {"description": "Full batch gradient descent for scalar squared loss.", "implementation": ["examples/toy/train.py"]},
            "metrics": {"primary": [{"name": "mse", "direction": "minimize"}], "secondary": [{"name": "train_mse", "direction": "minimize"}]},
            "data": {"dataset_id": "toy-data", "version": "synthetic-v1", "split": self.config["split"]},
            "baseline": {"kind": "toy", "name": "synthetic known generating law", "reported_metrics": []},
            "hyperparameters": self.hyperparameters, "seeds": [7],
            "success_signals": [{"id": "fit", "rule": "test MSE < 0.02", "metrics": ["mse"]}],
            "failure_signals": [{"id": "divergence", "rule": "nonfinite output or parameters diverge", "metrics": ["mse", "train_mse"]}],
            "inconclusive_signals": [{"id": "insufficient", "rule": "missing run or raw predictions", "metrics": ["mse"]}],
            "ablations": [{"name": "no_updates", "expected": "MSE stays higher", "status": "not_run"}],
            "budget": {"max_cpu_seconds": 100, "max_gpu_hours": 0, "max_cost_usd": 0, "max_attempts": 20},
            "stopping": {"max_attempts": 20, "criterion": "one smoke computation, no research claim"},
            "provenance": {"mode": "preregistered", "observed_runs": [], "hypothesis_basis_runs": []},
        }
        self.contract_path = "contracts/toy-linear/v1.yaml"
        dump(self.root / self.contract_path, self.protocol)
        self.budget = {"max_cpu_seconds": 100, "max_gpu_hours": 0, "max_cost_usd": 0, "max_attempts": 20, "max_retries": 1, "real_enabled": True}
        dump(self.root / "configs/budget.json", self.budget)
        dump(self.root / "configs/models.json", {"policy": {"max_review_rounds": 2, "require_cross_family": True, "accept_human_reviews": True}})
        dump(self.root / "configs/research.json", {"question": None, "setting": None, "selected_idea": None, "baseline": {"paper_source": None}})
        self.resources = {
            "data": [{"id": "toy-data", "status": "verified", "kind": "toy", "path": "data.txt", "version": "synthetic-v1", "fingerprint": gates.digest(self.root / "data.txt"), "split": self.config["split"], "verification": {"evidence_file": "witness.txt"}}],
            "environments": [{"id": "toy-python", "status": "verified", "kind": "toy", "path": sys.executable, "version": sys.version, "verification": {"command": [sys.executable, "--version"], "evidence_file": "witness.txt"}}],
            "compute": [{"id": "toy-cpu", "status": "verified", "kind": "toy", "cpus": 1, "gpus": 0, "verification": {"evidence_file": "witness.txt"}}], "weights": []}
        dump(self.root / "configs/resources.json", self.resources)
        self.job = {"task_id": "toy-001", "kind": "toy", "stage": "sanity", "idea_id": "toy-linear", "contract": self.contract_path,
                    "command": ["{python}", "examples/toy/train.py", "--config", "{config}", "--seed", "7"], "config": "experiments/config.json", "seed": 7,
                    "dataset_id": "toy-data", "environment_id": "toy-python", "resource_id": "toy-cpu", "estimated": {"cpu_seconds": 5, "gpu_hours": 0, "cost_usd": 0},
                    "timeout_seconds": 5, "stall_seconds": 5, "required_metrics": ["mse", "train_mse"], "code_paths": ["examples/toy/train.py"], "cpus": 1, "gpus": 0}

    def freeze(self) -> dict:
        return contracts.freeze(self.root, self.contract_path)

    def run_job(self, **updates: object) -> dict:
        job = copy.deepcopy(self.job)
        job.update(updates)
        dump(self.root / "experiments/job.json", job)
        return runtime.run(self.root, "experiments/job.json", foreground=True)

    def test_cpu_toy_computes_metrics_recomputable_from_predictions(self) -> None:
        self.freeze()
        manifest = self.run_job()
        self.assertEqual(manifest["status"], "completed")
        out = self.root / "runs/toy-001"
        with (out / "predictions.csv").open() as stream:
            rows = list(csv.DictReader(stream))
        mse = sum((float(row["target"]) - float(row["prediction"])) ** 2 for row in rows) / len(rows)
        self.assertAlmostEqual(mse, manifest["metrics"]["values"]["mse"], places=14)
        self.assertLess(mse, 0.02)
        self.assertEqual(manifest["kind"], "toy")
        self.assertEqual(manifest["scientific_acceptance"], "not_assessed")
        self.assertEqual(contracts.sha(out / "contract.yaml"), manifest["contract"]["sha256"])
        self.assertTrue((out / "artifacts.json").is_file())

    def test_unfrozen_protocol_blocks_launch(self) -> None:
        with self.assertRaisesRegex(contracts.ProjectError, "not frozen"):
            self.run_job()
        self.assertFalse((self.root / "runs/toy-001").exists())

    def test_real_protocol_requires_prespecified_statistics(self) -> None:
        protocol = copy.deepcopy(self.protocol)
        protocol["kind"] = "real"  # Schema-only fixture; no real experiment runs.
        dump(self.root / self.contract_path, protocol)
        with self.assertRaisesRegex(contracts.ProjectError, "statistics"):
            contracts.validate(self.root, self.contract_path)

    def test_real_protocol_rejects_invalid_tolerance(self) -> None:
        protocol = copy.deepcopy(self.protocol)
        protocol["kind"] = "real"  # Schema-only fixture; no real experiment runs.
        protocol["statistics"] = {"metric": "mse", "aggregation": "fixture seed average", "atol": -0.1,
                                  "rtol": 0, "statistical_rule": "schema fixture only", "hardware_scope": "fixture CPU"}
        dump(self.root / self.contract_path, protocol)
        with self.assertRaisesRegex(contracts.ProjectError, "atol"):
            contracts.validate(self.root, self.contract_path)

    def test_missing_resources_block_launch(self) -> None:
        self.freeze()
        dump(self.root / "configs/resources.json", {"data": [], "environments": [], "compute": []})
        with self.assertRaisesRegex(contracts.ProjectError, "resource"):
            self.run_job()

    def test_missing_required_review_is_not_pass(self) -> None:
        with self.assertRaises(contracts.ProjectError):
            gates.check_receipt(self.root, None, "code-review", self.job)

    def test_nonzero_exit_is_failed_and_no_metrics_fabricated(self) -> None:
        self.freeze()
        result = self.run_job(command=self.job["command"] + ["--fail"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 23)
        self.assertFalse((self.root / "runs/toy-001/metrics.json").exists())

    def test_missing_metrics_cannot_complete(self) -> None:
        self.freeze()
        result = self.run_job(command=self.job["command"] + ["--missing-metrics"])
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("metrics", result)

    def test_timeout_cannot_complete(self) -> None:
        self.freeze()
        result = self.run_job(command=self.job["command"] + ["--sleep", "5"], timeout_seconds=0.4, stall_seconds=5)
        self.assertEqual(result["status"], "timeout")
        self.assertNotEqual(result["exit_code"], 0)

    def test_stall_cannot_complete(self) -> None:
        self.freeze()
        result = self.run_job(command=self.job["command"] + ["--sleep", "5"], timeout_seconds=5, stall_seconds=0.3)
        self.assertEqual(result["status"], "stalled")

    def test_signal_interruption_cannot_complete(self) -> None:
        script = self.root / "examples/toy/interrupt.py"
        script.write_text("import os, signal\nos.kill(os.getpid(), signal.SIGTERM)\n")
        self.job["code_paths"].append("examples/toy/interrupt.py")
        self.freeze()
        result = self.run_job(command=["{python}", "examples/toy/interrupt.py"])
        self.assertEqual(result["status"], "interrupted")

    def test_frozen_protocol_modification_is_detected(self) -> None:
        self.freeze()
        protocol = copy.deepcopy(self.protocol)
        protocol["success_signals"] = [{"name": "changed", "rule": "test MSE < 99"}]
        dump(self.root / self.contract_path, protocol)
        with self.assertRaisesRegex(contracts.ProjectError, "modified"):
            contracts.verify(self.root, self.contract_path)
        with self.assertRaises(contracts.ProjectError):
            self.run_job()

    def test_new_version_does_not_rebind_old_run(self) -> None:
        self.freeze()
        old = self.run_job()
        protocol = copy.deepcopy(self.protocol)
        protocol["version"] = 2
        protocol["provenance"] = {"mode": "exploratory", "observed_runs": ["toy-001"], "hypothesis_basis_runs": ["toy-001"]}
        protocol["amendment"] = {"previous": self.contract_path, "reason": "Test a separate engineering threshold after seeing toy output", "created_at": datetime.now(timezone.utc).isoformat(), "seen_results": ["toy-001"], "impact": "Future toy runs only; no relabeling of v1"}
        dump(self.root / "contracts/toy-linear/v2.yaml", protocol)
        contracts.freeze(self.root, "contracts/toy-linear/v2.yaml")
        retained = contracts.load(self.root / "runs/toy-001/manifest.json")
        self.assertEqual(retained["contract"], old["contract"])
        self.assertEqual(retained["contract"]["path"], self.contract_path)

    def test_post_result_protocol_cannot_claim_preregistered(self) -> None:
        self.freeze()
        self.run_job()
        protocol = copy.deepcopy(self.protocol)
        protocol["version"] = 2
        protocol["provenance"]["observed_runs"] = ["toy-001"]
        dump(self.root / "contracts/toy-linear/v2.yaml", protocol)
        with self.assertRaisesRegex(contracts.ProjectError, "exploratory"):
            contracts.validate(self.root, "contracts/toy-linear/v2.yaml")

    def test_over_budget_blocks_before_start(self) -> None:
        self.freeze()
        self.budget["max_cpu_seconds"] = 1
        dump(self.root / "configs/budget.json", self.budget)
        with self.assertRaisesRegex(contracts.ProjectError, "budget"):
            self.run_job()
        self.assertFalse((self.root / "runs/toy-001").exists())

    def test_global_budget_cannot_be_enlarged_by_toy_scope(self) -> None:
        self.freeze()
        self.budget["max_cpu_seconds"] = 0
        self.budget["scopes"] = {"toy": {"max_cpu_seconds": 100, "max_gpu_hours": 0, "max_cost_usd": 0, "max_attempts": 20, "max_retries": 1}}
        dump(self.root / "configs/budget.json", self.budget)
        with self.assertRaisesRegex(contracts.ProjectError, "global.cpu_seconds"):
            self.run_job()
        self.assertFalse((self.root / "runs/toy-001").exists())

    def test_duplicate_and_resume_never_resubmit(self) -> None:
        self.freeze()
        first = self.run_job()
        second = self.run_job()
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["created_at"], second["created_at"])
        report = runtime.resume(self.root)
        self.assertEqual(report["resubmitted"], 0)
        self.assertEqual(len(report["runs"]), 1)

    def test_detached_run_resume_active_and_complete_do_not_resubmit(self) -> None:
        self.freeze()
        job = copy.deepcopy(self.job)
        job["command"] += ["--sleep", "0.8"]
        dump(self.root / "experiments/job.json", job)
        launched = runtime.run(self.root, "experiments/job.json", foreground=False)
        self.assertEqual(launched["status"], "queued")
        try:
            active = runtime.resume(self.root)
            self.assertEqual(active["resubmitted"], 0)
            self.assertEqual(len(active["runs"]), 1)
            self.assertIn(active["runs"][0]["status"], {"queued", "running"})
            duplicate = runtime.run(self.root, "experiments/job.json", foreground=False)
            self.assertTrue(duplicate["duplicate"])
            self.assertEqual(duplicate["worker_pid"], launched["worker_pid"])
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                manifest = contracts.load(self.root / "runs/toy-001/manifest.json")
                if manifest["status"] in runtime.TERMINAL:
                    break
                time.sleep(0.05)
            self.assertEqual(manifest["status"], "completed")
            resumed = runtime.resume(self.root)
            self.assertEqual(resumed["resubmitted"], 0)
            self.assertEqual(len(resumed["runs"]), 1)
            self.assertEqual(resumed["runs"][0]["created_at"], launched["created_at"])
            self.assertTrue(runtime.run(self.root, "experiments/job.json")["duplicate"])
        finally:
            # Bounded cleanup only if an assertion fails before the detached worker exits.
            manifest = contracts.load(self.root / "runs/toy-001/manifest.json")
            if runtime.alive(manifest.get("worker_pid"), manifest.get("worker_start")):
                import signal
                os.kill(manifest["worker_pid"], signal.SIGTERM)
                deadline = time.monotonic() + 5
                while runtime.alive(manifest.get("worker_pid"), manifest.get("worker_start")) and time.monotonic() < deadline:
                    time.sleep(0.05)

    def test_local_environment_must_match_current_interpreter(self) -> None:
        alternate = self.root / "different-python"
        shutil.copyfile(sys.executable, alternate)
        self.resources["environments"][0]["path"] = str(alternate)
        dump(self.root / "configs/resources.json", self.resources)
        with self.assertRaises(contracts.ProjectError):
            gates.check_job(self.root, self.job)

    def test_contract_seed_mapping_schema_is_launchable(self) -> None:
        self.protocol["seeds"] = {"values": [7], "scheme": "single seeded engineering check"}
        dump(self.root / self.contract_path, self.protocol)
        self.freeze()
        self.assertEqual(self.run_job()["status"], "completed")

    def test_real_sanity_requires_reproduced_baseline_idea_and_novelty(self) -> None:
        # This is a structural gate unit test with explicit mocks, never a real
        # research run or a claim that a baseline/reviewer was actually exercised.
        protocol = copy.deepcopy(self.protocol)
        protocol["kind"] = "real"
        protocol["data"]["fingerprint"] = self.resources["data"][0]["fingerprint"]
        protocol["baseline"]["commit"] = "1" * 40
        dump(self.root / self.contract_path, protocol)
        research = {"question": "Mocked gate-only input", "setting": "No training", "selected_idea": "toy-linear", "baseline": {"commit": "1" * 40}}
        dump(self.root / "configs/research.json", research)
        job = {**self.job, "kind": "real", "stage": "sanity", "code_review_receipt": "mock-code", "decision_record": "decision.json", "novelty_record": "novelty.json"}
        dump(self.root / "decision.json", {"idea_id": "toy-linear", "decision": "go", "reason": "Mocked gate fixture only", "architect_identity": "unit-test fixture"})
        dump(self.root / "novelty.json", {"idea_id": "toy-linear", "decision": "revise", "queries": ["fixture"], "sources": [], "checked_at": "test-fixture"})
        mocked_resources = {"data": self.resources["data"][0], "environments": self.resources["environments"][0], "compute": self.resources["compute"][0]}
        def receipt(_root: Path, ref: str | None, purpose: str, _job: dict) -> dict:
            if ref is None:
                raise contracts.ProjectError(f"Missing required {purpose}")
            return {"test_fixture": True}
        with mock.patch.object(gates, "resource", side_effect=lambda _root, group, _id, _kind: mocked_resources[group]), mock.patch.object(gates, "check_baseline") as baseline, mock.patch.object(gates, "check_receipt", side_effect=receipt) as reviewer, mock.patch("selection.check_selection", return_value={"decision": "go"}):
            with self.assertRaisesRegex(contracts.ProjectError, "idea-review"):
                gates.check_job(self.root, job)
            baseline.assert_called_with(self.root, research, reproduced=True)
            self.assertEqual([call.args[2] for call in reviewer.call_args_list], ["code-review", "idea-review"])
            job["idea_review_receipt"] = "mock-idea"
            dump(self.root / "novelty.json", {"idea_id": "toy-linear", "decision": "revise", "queries": ["fixture"], "sources": [], "checked_at": "test-fixture"})
            with self.assertRaisesRegex(contracts.ProjectError, "novelty"):
                gates.check_job(self.root, job)
            baseline.assert_called_with(self.root, research, reproduced=True)

    def test_data_fingerprint_change_blocks_launch(self) -> None:
        self.freeze()
        (self.root / "data.txt").write_text("different synthetic fixture\n")
        with self.assertRaisesRegex(contracts.ProjectError, "fingerprint"):
            self.run_job()

    def test_config_hyperparameter_drift_is_blocked(self) -> None:
        self.freeze()
        changed = copy.deepcopy(self.config)
        changed["hyperparameters"]["learning_rate"] = 0.1
        dump(self.root / "experiments/config.json", changed)
        with self.assertRaisesRegex(contracts.ProjectError, "hyperparameters"):
            self.run_job()

    def test_config_seed_drift_is_blocked(self) -> None:
        self.freeze()
        changed = copy.deepcopy(self.config)
        changed["seed"] = 8
        dump(self.root / "experiments/config.json", changed)
        with self.assertRaisesRegex(contracts.ProjectError, "seed"):
            self.run_job()

    def test_omitting_frozen_secondary_metric_is_blocked(self) -> None:
        self.freeze()
        with self.assertRaisesRegex(contracts.ProjectError, "required_metrics"):
            self.run_job(required_metrics=["mse"])

    def test_retries_are_bounded_and_failed_attempts_consume_budget(self) -> None:
        self.freeze()
        first = self.run_job(command=self.job["command"] + ["--fail"])
        self.assertEqual(first["status"], "failed")
        retry = self.run_job(task_id="toy-002", retry_of="toy-001", command=self.job["command"] + ["--fail"])
        self.assertEqual(retry["status"], "failed")
        self.assertEqual(runtime.status(self.root)["reserved"]["cpu_seconds"], 10)
        with self.assertRaisesRegex(contracts.ProjectError, "retry limit"):
            self.run_job(task_id="toy-003", retry_of="toy-002", command=self.job["command"] + ["--fail"])

    def test_same_family_and_unknown_identity_are_not_independent(self) -> None:
        executor = {"provider": "test-provider", "model": "test-executor", "model_family": "family-A", "identity_source": "test-only fixture"}
        reviewer = {**executor, "model": "test-reviewer"}
        self.assertEqual(gates.independence(executor, reviewer), "same-family")
        self.assertEqual(gates.independence(executor, {}), "unknown")
        receipt = {"completion": "complete", "verdict": "PASS", "scope": {"purpose": "code-review", "idea_id": "toy-linear", "contract": self.contract_path}, "fresh_context": True,
                   "executor_identity": executor, "actual_identity": reviewer, "independence": "cross-family"}
        dump(self.root / "reviews/receipt.json", receipt)
        with self.assertRaisesRegex(contracts.ProjectError, "independent"):
            gates.check_receipt(self.root, "reviews/receipt.json", "code-review", self.job)

    def prepare_idea_pack(self) -> Path:
        (self.root / "baseline.md").write_text("Synthetic baseline source, engineering fixture only.\n")
        dump(self.root / "configs/research.json", {"question": "synthetic", "setting": "CPU", "selected_idea": "idea-A", "baseline": {"paper_source": "baseline.md"}})
        actor = {"provider": "test-provider", "model": "fixture-proposer", "model_family": "family-A", "identity_source": "unit-test fixture only"}
        dump(self.root / "idea-stage/ideas/idea-A.json", {"id": "idea-A", "hypothesis": "Current hypothesis", "description": "Current idea", "ranking": "architect bias must be stripped", "generation_transcript": "generation secret must be stripped", "proposer_identity": actor})
        dump(self.root / "idea-stage/ideas/idea-B.json", {"id": "idea-B", "hypothesis": "Other candidate must stay out"})
        (self.root / "idea-stage/IDEA_REPORT.md").write_text("Entire candidate pool must stay out\n")
        return evidence.context_pack(self.root, "idea-A", "idea-review")

    def test_idea_review_package_contains_only_current_idea(self) -> None:
        package = self.prepare_idea_pack()
        manifest = contracts.load(package / "manifest.json")
        payload = "\n".join(p.read_text() for p in (package / "files").iterdir())
        self.assertIn("Current hypothesis", payload)
        self.assertNotIn("Other candidate must stay out", payload)
        self.assertNotIn("architect bias must be stripped", payload)
        self.assertNotIn("generation secret must be stripped", payload)
        self.assertNotIn("Entire candidate pool must stay out", payload)
        self.assertTrue(all("idea-B" not in item["path"] for item in manifest["files"]))

    def test_review_import_missing_actual_identity_is_blocked(self) -> None:
        package = self.prepare_idea_pack()
        result = contracts.load(package / "result-template.json")
        result.update({"completion": "complete", "verdict": "PASS", "fresh_context": True})
        dump(package / "result.json", result)
        with self.assertRaisesRegex(contracts.ProjectError, "identities"):
            evidence.import_review(self.root, package, package / "result.json")

    def test_same_family_review_import_is_provisional_and_cannot_pass_gate(self) -> None:
        package = self.prepare_idea_pack()
        manifest = contracts.load(package / "manifest.json")
        result = contracts.load(package / "result-template.json")
        result.update({"completion": "complete", "verdict": "PASS", "fresh_context": True,
                       "scorecard": {"scores": {"novelty": 3, "feasibility": 3, "compatibility": 3, "complexity": 3, "expected_gain": 3}, "recommendation": "go", "reasons": ["Synthetic fixture only"], "revision_requests": []},
                       "actual_identity": {"provider": "test-provider", "model": "fixture-reviewer", "model_family": "family-A", "identity_source": "unit-test fixture only"},
                       "direct_reads": [item["path"] for item in manifest["files"]], "raw_response_file": "response.txt", "identity_evidence_file": "identity.txt"})
        (package / "response.txt").write_text("Synthetic review response, not an actual external-model review.\n")
        (package / "identity.txt").write_text("Synthetic identity metadata fixture for test only.\n")
        dump(package / "result.json", result)
        receipt_path = evidence.import_review(self.root, package, package / "result.json")
        receipt = contracts.load(receipt_path)
        self.assertEqual(receipt["independence"], "same-family")
        self.assertEqual(receipt["acceptance_status"], "provisional")
        with self.assertRaisesRegex(contracts.ProjectError, "independent"):
            gates.check_receipt(self.root, str(receipt_path), "idea-review", {"idea_id": "idea-A"})
        with self.assertRaises(contracts.ProjectError):
            evidence.import_review(self.root, package, package / "result.json")

    def test_toy_empirical_claim_is_rejected_from_formal_paper(self) -> None:
        self.freeze()
        self.run_job()
        (self.root / "baseline.md").write_text("Synthetic baseline source, test fixture only.\n")
        dump(self.root / "configs/research.json", {"baseline": {"paper_source": "baseline.md"}})
        dump(self.root / "analysis/toy.json", {
            "kind": "toy", "contract": self.contract_path, "runs": ["toy-001"],
            "outcome": "success", "decision": "engineering-chain-works",
            "limitations": ["Synthetic only; no scientific result"],
            "analyst_identity": {"provider": "fixture", "model": "analyst", "model_family": "fixture-A", "identity_source": "synthetic unit test"},
            "signal_results": [{"signal_id": sid, "status": status, "reason": "Synthetic evidence assessment", "evidence": [{"run_id": "toy-001", "metric": "mse"}]} for sid, status in (("fit", "met"), ("divergence", "not_met"), ("insufficient", "not_met"))]
        })
        package = evidence.context_pack(self.root, "toy-linear", "result-review", analysis_ref="analysis/toy.json")
        manifest = contracts.load(package / "manifest.json")
        review = contracts.load(package / "result-template.json")
        review.update({"completion": "complete", "verdict": "PASS", "fresh_context": True,
                       "actual_identity": {"actor_type": "human", "person": "Synthetic reviewer", "identity_source": "unit-test fixture only"},
                       "direct_reads": [entry["path"] for entry in manifest["files"]],
                       "raw_response_file": "response.txt", "identity_evidence_file": "identity.txt"})
        (package / "response.txt").write_text("Synthetic review of toy signals; no actual external review.\n")
        (package / "identity.txt").write_text("Synthetic identity fixture.\n")
        dump(package / "result.json", review)
        receipt = evidence.import_review(self.root, package, package / "result.json")
        dump(self.root / "paper/claims.json", [{"id": "test-claim", "type": "empirical", "kind": "toy", "hypothesis": self.protocol["hypothesis"], "contract": self.contract_path, "runs": ["toy-001"], "analysis_file": "analysis/toy.json", "metrics": ["mse"], "signal_ids": ["fit"], "result_review_receipt": receipt.relative_to(self.root).as_posix()}])
        self.assertEqual(evidence.audit(self.root, paper=False)["status"], "PASS")
        report = evidence.audit(self.root, paper=True)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("Toy/mock", report["errors"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
