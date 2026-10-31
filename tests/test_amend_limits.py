"""Limit successors on isolated copies only; no data, networks or workloads."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import amend_limits as limits
import contracts
import evidence
import gates
import review_batch
import runtime
import test_workflow as workflow


class LimitCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="amend-limits-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "contracts", self.root / "contracts")
        self.copy(limits.AUTHORIZATION)
        for seed in (42, 43, 44):
            self.copy(f"experiments/baseline-seed{seed}.json")
        self.copy("experiments/baseline-config.json")

    def copy(self, ref):
        path = self.root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / ref, path)

    def phase2(self):
        if not (ROOT / "experiments/phase2").exists():
            self.skipTest("phase-2 payload is absent in phase-1 package")
        shutil.copytree(ROOT / "experiments/phase2", self.root / "experiments/phase2")
        self.copy("eval/shared_client/evaluation-params.json")

    def timeout(self, version=2):
        return contracts.load(self.root / f"contracts/baseline/v{version}.yaml")["stopping"]["timeout_seconds"] * 2

    def test_plan_is_read_only_and_allowlist_checks_raw_scientific_bytes(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        plan = limits.make_plan(self.root, 1, self.timeout(), reason="Synthetic pre-run extension")
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        row = plan["protocols"][0]
        original = (self.root / row["source"]).read_bytes()
        successor = plan["files"][row["successor"]].encode()
        limits.assert_only_changes(original, successor)
        # Same decoded scientific value, different JSON spelling: still refused.
        bad = successor.replace(b'"batch_size": 32', b'"batch_size": 3.2e1')
        self.assertNotEqual(bad, successor)
        with self.assertRaisesRegex(contracts.ProjectError, "scientific field differs in bytes"):
            limits.assert_only_changes(original, bad)
        p = json.loads(successor)
        for field in ("seeds", "data", "metrics", "hyperparameters", "success_signals"):
            bad = copy.deepcopy(p)
            bad[field] = {"unauthorized": True}
            with self.subTest(field=field), self.assertRaises(contracts.ProjectError):
                limits.assert_only_changes(original, limits.encode(bad))

    def test_pre_run_apply_preserves_provenance_original_files_and_job_settings(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = limits.apply_limits(self.root, 1, self.timeout(), reason="Synthetic pre-run extension")
        row = result["protocols"][0]
        protocol = contracts.load(self.root / row["successor"])
        original = contracts.load(self.root / row["source"])
        self.assertEqual(protocol["provenance"], original["provenance"])
        self.assertFalse(protocol["amendment"]["post_hoc"])
        self.assertEqual(protocol["budget"]["max_attempts"], original["budget"]["max_attempts"])
        self.assertEqual(protocol["budget"]["max_cpu_seconds"], original["budget"]["max_attempts"] * self.timeout())
        self.assertEqual(protocol["budget"]["max_gpu_hours"], original["budget"]["max_attempts"] * self.timeout() / 3600)
        for path, data in before.items():
            if path.as_posix() != "contracts/.registry.json":
                self.assertEqual((self.root / path).read_bytes(), data, path)
        self.assertEqual(contracts.verify(self.root)["count"], len(contracts.load(self.root / "contracts/.registry.json")["contracts"]))
        for change in row["job_changes"]:
            old = contracts.load(self.root / change["source"])
            new = contracts.load(self.root / change["job"])
            self.assertIsNone(new["code_review_receipt"])
            self.assertNotEqual(old["task_id"], new["task_id"])
            for key in ("seed", "cpus", "gpus", "environment_id", "resource_id", "executor_identity", "required_metrics", "code_paths"):
                self.assertEqual(old[key], new[key], key)
            self.assertEqual((self.root / change["config_source"]).read_bytes(), (self.root / change["config"]).read_bytes())
        self.assertIn("Disclosed limit deviation", (self.root / "OPERATOR_LOG.md").read_text())

    def test_post_hoc_apply_obeys_existing_provenance_gate_and_discloses_it(self):
        contracts.atomic_json(self.root / "runs/synthetic-timeout/manifest.json", {"idea_id": "baseline", "status": "timeout"})
        plan = limits.make_plan(self.root, 1, self.timeout(), reason="Synthetic post-hoc extension")
        self.assertEqual(plan["classification"], limits.POST_HOC)
        result = limits.apply_limits(self.root, 1, self.timeout(), reason="Synthetic post-hoc extension")
        ref = result["protocols"][0]["successor"]
        protocol = contracts.validate(self.root, ref)
        self.assertEqual(protocol["provenance"]["mode"], "exploratory")
        self.assertEqual(protocol["provenance"]["observed_runs"], ["synthetic-timeout"])
        self.assertEqual(protocol["provenance"]["hypothesis_basis_runs"], [])
        self.assertEqual(protocol["amendment"]["seen_results"], ["synthetic-timeout"])
        for path in ("reports/third-party/limit-deviation.md", "OPERATOR_LOG.md"):
            self.assertIn(limits.POST_HOC, (self.root / path).read_text())

    def test_running_and_log_observed_runs_are_included_but_queued_is_not(self):
        for task, status in (("running", "running"), ("queued", "queued"), ("logged", "queued")):
            contracts.atomic_json(self.root / f"runs/{task}/manifest.json", {"idea_id": "baseline", "status": status})
        (self.root / "runs/logged/stdout.log").write_text("Synthetic partial progress\n")
        plan = limits.make_plan(self.root, 1, self.timeout(), reason="Synthetic observed ledger")
        self.assertEqual(plan["observed_runs"], ["logged", "running"])

    def test_lowering_and_invalid_values_are_refused_unless_explicit(self):
        for timeout, options in ((0, {}), (-1, {}), (self.timeout(), {"stall_seconds": 1}),
                                 (self.timeout() // 4, {}), (1, {"allow_lower": True})):
            with self.subTest(timeout=timeout, options=options), self.assertRaises(contracts.ProjectError):
                limits.make_plan(self.root, 1, timeout, reason="Synthetic", **options)
        plan = limits.make_plan(self.root, 1, self.timeout() // 4, reason="Disclosed lower limits", allow_lower=True)
        self.assertTrue(json.loads(plan["files"][plan["protocols"][0]["successor"]])["amendment"]["allow_lower"])

    def test_repeated_amendment_uses_latest_scientific_parent_and_preserves_chain(self):
        first = limits.apply_limits(self.root, 1, self.timeout(), reason="First synthetic extension")
        second = limits.apply_limits(self.root, 1, self.timeout() * 2, reason="Second synthetic extension")
        protocol = contracts.load(self.root / second["protocols"][0]["successor"])
        self.assertEqual(protocol["amendment"]["original"]["path"], first["protocols"][0]["successor"])
        self.assertEqual(protocol["amendment"]["previous"], first["protocols"][0]["successor"])
        self.assertEqual(limits.validate_deviation(self.root, second["protocols"][0]["successor"]), "contracts/baseline/v2.yaml")

    def test_phase2_four_successors_keep_science_eval_hash_and_all_sixty_copies(self):
        self.phase2()
        before = (self.root / "eval/shared_client/evaluation-params.json").read_bytes()
        result = limits.apply_limits(self.root, 2, self.timeout(3), reason="Synthetic phase-2 extension")
        self.assertEqual(len(result["protocols"]), 4)
        self.assertEqual(sum(len(row["jobs"]) for row in result["protocols"]), 60)
        self.assertEqual(contracts.verify(self.root)["count"], 10)
        for row in result["protocols"]:
            limits.assert_only_changes((self.root / row["source"]).read_bytes(), (self.root / row["successor"]).read_bytes())
            p = contracts.validate(self.root, row["successor"])
            self.assertEqual(p["amendment"]["origin"], row["origin"])
            for ref in row["jobs"].values():
                job = contracts.load(self.root / ref); cfg = contracts.load(self.root / job["config"])
                self.assertEqual(cfg["contract"], job["contract"])
                self.assertEqual(job["command"][-1], ref)
                runtime.bind_config(job, cfg, p)
        self.assertEqual((self.root / "eval/shared_client/evaluation-params.json").read_bytes(), before)

    def test_scientific_eval_file_tampering_and_frozen_source_tampering_are_refused(self):
        self.phase2()
        file = self.root / "eval/shared_client/evaluation-params.json"
        file.write_bytes(file.read_bytes()+b"\n")
        with self.assertRaisesRegex(contracts.ProjectError, "evaluation-params hash changed"):
            limits.make_plan(self.root, 2, self.timeout(3), reason="Synthetic")
        file = self.root / "contracts/baseline/v2.yaml"
        file.write_bytes(file.read_bytes()+b"\n")
        with self.assertRaisesRegex(contracts.ProjectError, "Frozen protocol was modified"):
            limits.make_plan(self.root, 1, self.timeout(), reason="Synthetic")

    def test_pending_target_is_never_overwritten_and_source_drift_is_detected(self):
        plan = limits.make_plan(self.root, 1, self.timeout(), reason="Synthetic")
        target = self.root / plan["protocols"][0]["successor"]
        target.write_text("pending operator work")
        with self.assertRaisesRegex(contracts.ProjectError, "Refusing to overwrite"):
            limits._check_inputs(self.root, plan)
        target.unlink()
        (self.root / "experiments/baseline-config.json").write_text("{}")
        with self.assertRaisesRegex(contracts.ProjectError, "Input changed"):
            limits._check_inputs(self.root, plan)

    def test_cli_plan_returns_post_hoc_classification(self):
        contracts.atomic_json(self.root / "runs/synthetic-failed/manifest.json", {"idea_id": "baseline", "status": "failed"})
        output = io.StringIO()
        with redirect_stdout(output):
            code = limits.main(["--root", str(self.root), "plan", "--phase", "1", "--timeout-seconds", str(self.timeout()), "--reason", "Synthetic CLI"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["classification"], limits.POST_HOC)


class AmendedReviewGateTests(unittest.TestCase):
    def test_amended_chain_batch_import_and_existing_launch_checks(self):
        fixture = workflow.WorkflowTests(); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        root = fixture.root
        protocol = copy.deepcopy(fixture.protocol)
        protocol.update(idea_id="baseline", seeds=[42, 43, 44])
        protocol["stopping"] = {"timeout_seconds": 10, "stall_seconds": 2, "max_rounds": 1}
        protocol["budget"].update(max_attempts=6, max_cpu_seconds=60)
        contracts.atomic_json(root / "contracts/baseline/v1.yaml", protocol)
        contracts.freeze(root, "contracts/baseline/v1.yaml")
        protocol.update(version=2, amendment={"previous": "contracts/baseline/v1.yaml", "created_at": limits.now(), "reason": "Synthetic baseline", "impact": "Synthetic only", "seen_results": []})
        contracts.atomic_json(root / "contracts/baseline/v2.yaml", protocol)
        contracts.freeze(root, "contracts/baseline/v2.yaml")
        actor = {"actor_type": "human", "person": "Synthetic operator", "identity_source": "synthetic only"}
        for seed in (42, 43, 44):
            job = copy.deepcopy(fixture.job)
            job.update(idea_id="baseline", contract="contracts/baseline/v2.yaml", task_id=f"synthetic-{seed}",
                       seed=seed, config="experiments/baseline-config.json", timeout_seconds=10, stall_seconds=2, executor_identity=actor)
            contracts.atomic_json(root / f"experiments/baseline-seed{seed}.json", job)
        cfg = dict(fixture.config); cfg.pop("seed"); cfg["seeds"] = [42, 43, 44]
        contracts.atomic_json(root / "experiments/baseline-config.json", cfg)
        auth = root / limits.AUTHORIZATION; auth.parent.mkdir(exist_ok=True)
        auth.write_text("Synthetic authorization, test only.\n")
        (root / "baseline.md").write_text("Synthetic paper fixture.\n")
        contracts.atomic_json(root / "configs/research.json", {"baseline": {"paper_source": "baseline.md"}})
        contracts.atomic_json(root / "configs/models.json", {"policy": {"max_review_calls": None, "max_review_rounds": 2}})
        result = limits.apply_limits(root, 1, 20, reason="Synthetic gate integration")
        batch = root / "batch"
        glob = f"experiments/limit-deviations/{result['batch']}/jobs/*.json"
        index = review_batch.prepare(root, "baseline", glob, batch)
        results = contracts.load(batch / "results-template.json")
        (batch / "response.txt").write_text("Synthetic full session response, no external reviewer.\n")
        (batch / "identity.txt").write_text("Synthetic identity evidence.\n")
        for row in index["packages"]:
            manifest = contracts.load(batch / row["package_path"] / "manifest.json")
            results[row["package_id"]].update(completion="complete", verdict="PASS", fresh_context=True,
                actual_identity={"provider": "fixture", "model": "reviewer", "model_family": "synthetic", "identity_source": "synthetic only"},
                direct_reads=[item["path"] for item in manifest["files"]], raw_response_file="response.txt", identity_evidence_file="identity.txt")
        contracts.atomic_json(batch / "RESULTS.json", results)
        report = review_batch.import_batch(root, batch, batch / "RESULTS.json")
        for row in report["receipts"]:
            job = contracts.load(root / row["job_path"])
            gates.check_receipt(root, row["receipt_path"], "code-review", job)
            gates.check_job(root, job)
            p = contracts.load(root / job["contract"])
            runtime.bind_config(job, contracts.load(root / job["config"]), p)
            runtime.check_protocol_budget(root, job, p, runtime.reservation(job))
            with self.assertRaisesRegex(contracts.ProjectError, "exceeds frozen stopping"):
                runtime.bind_config(dict(job, timeout_seconds=21), contracts.load(root / job["config"]), p)
        contracts.atomic_json(root / "runs/synthetic-reservation/manifest.json", {"contract": {"path": job["contract"]}, "reservation": {"cpu_seconds": p["budget"]["max_cpu_seconds"], "gpu_hours": 0, "cost_usd": 0}})
        with self.assertRaisesRegex(contracts.ProjectError, "frozen protocol budget exceeded"):
            runtime.check_protocol_budget(root, job, p, runtime.reservation(job))


if __name__ == "__main__":
    unittest.main()
