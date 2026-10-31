"""CPU-only fixtures; no ContextFlow imports, rollouts or GPU calls."""
import copy
import io
import json
import logging
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

import baseline.runner.contextflow_repro as runner
from baseline.runner import serve_with_probe
from baseline.runner.contextflow_repro import TASKS, METRICS, commands, parse_successes, write_metrics
from baseline.runner.verify_libero_data import verify_manifest
from gates import digest

# The executable client wrapper imports its sibling by script-directory name.
# Supply that sibling without loading any ContextFlow/LIBERO modules in fixtures.
with mock.patch.dict(sys.modules, {"serve_with_probe": serve_with_probe}):
    from baseline.runner.eval_with_probe import TrialObserver


def official_output_fixture(suite="libero_spatial", trials=2, all_tasks=False):
    # Exact logging.basicConfig(INFO) format and JSON fields from the pinned
    # main_incontext.py: eval_libero. Synthetic outcomes, never real evidence.
    descriptions = [v for k, v in TASKS.items() if k.startswith("S" if suite == "libero_spatial" else "O")]
    unseen = set(descriptions)
    if all_tasks:
        descriptions += [f"synthetic {suite} seen task {i}" for i in range(8)]
    log = ""
    rows = []
    for task_id, description in enumerate(descriptions):
        for episode in range(trials):
            done = episode % 2 == 0
            log += (f"INFO:root:\nTask: {description}\n"
                    f"INFO:root:Starting episode {episode+1}...\n"
                    f"INFO:root:Success: {done}\n"
                    f"INFO:root:# episodes completed so far: {task_id*trials+episode+1}\n")
        successes = (trials+1)//2
        rows.append({"task_id": task_id, "task_description": description, "episodes": trials,
                     "successes": successes, "success_rate": successes/trials,
                     "category": "unseen" if description in unseen else "seen"})
    result = {"config": {"task_suite_name": suite, "num_trials_per_task": trials, "seed": 7},
              "per_task_results": rows,
              "summary": {"total_episodes": len(rows)*trials, "total_successes": sum(r["successes"] for r in rows),
                          "num_unseen_tasks": 2, "num_seen_tasks": 8 if all_tasks else 0,
                          "num_tasks_evaluated": len(rows)}}
    return log, result


class ManifestTests(unittest.TestCase):
    def test_exact_payload_and_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "meta").mkdir()
            (directory / "meta/tasks.jsonl").write_text('{"task": "fixture"}\n')
            (directory / "README.md").write_text("tiny test data\n")
            files = [{"path": p.relative_to(directory).as_posix(), "size": p.stat().st_size,
                      "sha256": digest(p)} for p in directory.rglob("*") if p.is_file()]
            manifest = {"files": files, "n_files": len(files), "total_bytes": sum(f["size"] for f in files)}
            fingerprint = digest(directory)
            self.assertEqual(verify_manifest(directory, manifest, fingerprint)["n_files"], 2)
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                verify_manifest(directory, manifest, "0"*64)
            payload = directory / "README.md"
            payload.write_text("tiny test datX\n")  # Same size, different bytes.
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                verify_manifest(directory, manifest, fingerprint)

    def test_extra_file_symlink_and_unsafe_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            manifest = {"files": [], "n_files": 0, "total_bytes": 0}
            fingerprint = digest(directory)
            (directory / ".cache").write_text("extra")
            with self.assertRaisesRegex(ValueError, "extra="):
                verify_manifest(directory, manifest, fingerprint)
            (directory / ".cache").unlink()
            (directory / "link").symlink_to(directory)
            with self.assertRaisesRegex(ValueError, "symlinks"):
                verify_manifest(directory, manifest, fingerprint)
            (directory / "link").unlink()
            manifest.update(files=[{"path": "../escape", "size": 0, "sha256": "0"*64}], n_files=1)
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                verify_manifest(directory, manifest, fingerprint)


class ClientOutputTests(unittest.TestCase):
    def test_both_suites_fifty_trials(self):
        for suite in ("libero_spatial", "libero_object"):
            log, result = official_output_fixture(suite, 50)
            tasks = parse_successes(log, result, suite)
            self.assertEqual(len(tasks), 2)
            for task in tasks.values():
                self.assertEqual(len(task["outcomes"]), 50)
                self.assertEqual(task["success_rate"], 0.5)

    def test_missing_and_disagreeing_output(self):
        log, result = official_output_fixture()
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            parse_successes(log.replace("Success: True", "Success: [missing]", 1), result, "libero_spatial", 2)
        bad = copy.deepcopy(result)
        bad["per_task_results"][0]["successes"] = 2
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            parse_successes(log, bad, "libero_spatial", 2)
        bad = copy.deepcopy(result)
        bad["per_task_results"].pop()
        with self.assertRaisesRegex(ValueError, "exactly"):
            parse_successes(log, bad, "libero_spatial", 2)
        with self.assertRaisesRegex(ValueError, "without an expected task"):
            parse_successes("INFO:root:Success: True\n" + log, result, "libero_spatial", 2)

    def test_metrics_exact_floats_and_aggregation(self):
        tasks = {k: {"success_rate": rate} for k, rate in zip(TASKS, (0.8, 0.4, 0.6, 1.0))}
        all_tasks = {f"seen {i}": {"category": "seen", "success_rate": .25} for i in range(16)}
        all_tasks.update({f"unseen {i}": {"category": "unseen", "success_rate": 0.0} for i in range(4)})
        trials = [{"success": True, "steps": 30, "requests": [{"latency_ms": 10.0}]},
                  {"success": True, "steps": 50, "requests": [{"latency_ms": 30.0}]},
                  {"success": False, "steps": 290, "requests": [{"latency_ms": 20.0}]}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrics.json"
            write_metrics(path, tasks, 3, 41, all_tasks, trials)
            values = json.loads(path.read_text())
            self.assertEqual(set(values), set(METRICS))
            self.assertEqual(len(values), 13)
            self.assertTrue(all(type(v) is float for v in values.values()))
            self.assertAlmostEqual(values["unseen_avg_success"], 0.7)
            self.assertAlmostEqual(values["spatial_avg_success"], 0.6)
            self.assertAlmostEqual(values["object_avg_success"], 0.8)
            self.assertEqual(values["seen_avg_success"], .25)
            self.assertEqual(values["infer_latency_ms_median"], 20)
            self.assertEqual(values["infer_latency_ms_p95"], 29)
            self.assertEqual(values["unseen_mean_steps_success"], 40)
            for trial in trials:
                trial["success"] = False
            self.assertEqual(write_metrics(path, tasks, 3, 41, all_tasks, trials)["unseen_mean_steps_success"], -1)
            for invalid in (float("nan"), float("inf"), -1):
                with self.assertRaises(ValueError):
                    write_metrics(path, tasks, invalid, 41, all_tasks, trials)
            with self.assertRaises(ValueError):
                write_metrics(path, {}, 3, 41, all_tasks, trials)
            with self.assertRaisesRegex(ValueError, "16 seen"):
                write_metrics(path, tasks, 3, 41, {}, trials)

    def test_second_pass_categories_and_primary_are_separate(self):
        for suite in ("libero_spatial", "libero_object"):
            log, result = official_output_fixture(suite, 20, all_tasks=True)
            parsed = parse_successes(log, result, suite, 20, all_tasks=True)
            self.assertEqual(sum(t["category"] == "seen" for t in parsed.values()), 8)
            self.assertEqual(sum(t["category"] == "unseen" for t in parsed.values()), 2)
            with self.assertRaises(ValueError):
                parse_successes(log, result, suite)
            bad = copy.deepcopy(result)
            bad["per_task_results"][0]["category"] = "seen"
            with self.assertRaisesRegex(ValueError, "eight seen"):
                parse_successes(log, bad, suite, 20, all_tasks=True)

    def test_commands_use_run_owned_artifacts_and_official_defaults(self):
        work, checkpoint, plan = commands(Path("/official"), sys.executable, "/client/python", Path("/tmp/dryrun"), 42, 8000, "task42", Path("/scratch"))
        self.assertEqual(work, Path("/tmp/dryrun/work"))
        self.assertEqual(checkpoint, Path("/tmp/dryrun/checkpoint/19999"))
        self.assertIn("--seed", plan["train"])
        self.assertIn("--policy.inference_dtype=float32", plan["server"])
        self.assertEqual(plan["train"][-2:], ["--checkpoint-base-dir", "/scratch"])
        self.assertTrue(plan["server"][1].endswith("serve_with_probe.py"))
        self.assertEqual(plan["server"][-1], str(checkpoint))
        self.assertEqual(len(plan), 7)  # Norm, train, server and four official clients.
        for phase, trials, flag in (("unseen", "50", "--unseen-only"), ("all_tasks", "20", "--no-unseen-only")):
            for suite in ("libero_spatial", "libero_object"):
                cmd = plan[f"{phase}_{suite}"]
                self.assertTrue(cmd[1].endswith("eval_with_probe.py"))
                self.assertNotIn("--seed", cmd)  # Official eval seed remains 7.
                self.assertNotIn("--unseen-task-index", cmd)
                self.assertIn(flag, cmd)
                self.assertEqual(cmd[cmd.index("--num-trials-per-task")+1], trials)
                self.assertIn(f"/eval/{phase}/", cmd[cmd.index("--results-out-path")+1])

    def test_dry_run_stops_before_any_pipeline_process(self):
        # Entire external environment is a mock fixture. This proves only wrapper
        # control flow, not official imports, data or usable pi0 weights.
        source = Path(__file__).resolve().parents[1]
        protocol = json.loads((source / "contracts/baseline/v2.yaml").read_text())
        job = json.loads((source / "experiments/baseline-seed42.json").read_text())
        config = json.loads((source / job["config"]).read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "official"
            repo.mkdir()
            for ref, value in (("configs/research.json", {"baseline": {"repo_path": str(repo)}}),
                               (job["contract"], protocol), (job["config"], config),
                               ("experiments/baseline-seed42.json", job)):
                path = root / ref
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value))
            data = root / "data/physical-intelligence/libero"
            data.mkdir(parents=True)
            cache = root / "cache"
            params = cache / "openpi-assets/checkpoints/pi0_base/params"
            params.mkdir(parents=True)
            (params / "fixture").write_text("not real weights")
            tokenizer = cache / "big_vision/paligemma_tokenizer.model"
            tokenizer.parent.mkdir(parents=True)
            tokenizer.write_text("not a real tokenizer")
            resources = {"data": dict(protocol["data"], path=str(data)),
                         "environments": {"path": sys.executable}, "compute": {"gpus": 1, "cpus": 1},
                         "weights": {"path": str(params), "fingerprint": digest(params)}}
            (root / "contracts/.registry.json").write_text(json.dumps({"schema_version": 1, "contracts": {
                job["contract"]: {"sha256": digest(root / job["contract"]), "version": 2,
                                  "idea_id": "baseline", "frozen_at": "2026-10-30T09:44:27Z"}}}))
            (root / "configs/resources.json").write_text(json.dumps({"environments": [
                {"id": job["environment_id"], "path": sys.executable}]}))
            out = root / "dryrun"
            def config_check(command, cwd, env, log):
                self.assertEqual(command[1], "-c")
                self.assertIn("get_kept_episode_indices", command[2])
                Path(env["CONTEXTFLOW_SPLIT_REPORT"]).write_text('{"kept_episodes": 1, "removed_episodes": 1}')
                return 0
            versions = [SimpleNamespace(stdout=v, returncode=0, check_returncode=lambda: None) for v in ("3.11", "3.8")]
            args = SimpleNamespace(dry_run=True, run_dir=str(out), seed=42, job=None)
            with mock.patch.object(Path, "cwd", return_value=root), \
                 mock.patch.dict(runner.os.environ, {"OPENPI_DATA_HOME": str(cache), "CONTEXTFLOW_LIBERO_PYTHON": sys.executable,
                                 "CONTEXTFLOW_CHECKPOINT_SCRATCH": str(root / "scratch")}, clear=True), \
                 mock.patch.object(runner, "checked_checkout"), \
                 mock.patch.object(runner, "resource", side_effect=lambda root, group, ident, kind: resources[group]), \
                 mock.patch.object(runner, "execute", side_effect=config_check) as execute, \
                 mock.patch.object(runner.subprocess, "run", side_effect=versions), \
                 mock.patch.object(runner.subprocess, "Popen") as spawn, mock.patch("builtins.print"):
                runner.run(args)
            self.assertEqual(execute.call_count, 1)
            spawn.assert_not_called()
            self.assertFalse((out / "metrics.json").exists())
            self.assertTrue((out / "pi0-base-sha256.json").is_file())
            self.assertEqual(len(list((out / "logs").glob("*.log"))), 4)
            self.assertEqual(len(json.loads((out / "details.json").read_text())["commands"]), 7)


class DiagnosticsTests(unittest.TestCase):
    def test_latency_and_demo_log_validation(self):
        row = dict(request_id=0, latency_ms=12.5, demo_episode_indices=[42, 43], task="fixture", task_index=7)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "requests.jsonl"
            path.write_text(json.dumps(row)+"\n")
            self.assertEqual(runner.parse_probe_log(path), {0: row})
            for changed in ({"latency_ms": -1}, {"latency_ms": float("nan")}, {"latency_ms": True},
                            {"demo_episode_indices": []}, {"demo_episode_indices": [-1]},
                            {"demo_episode_indices": [True]}, {"request_id": 1}):
                with self.subTest(changed=changed):
                    path.write_text(json.dumps(dict(row, **changed))+"\n")
                    with self.assertRaisesRegex(ValueError, "Invalid"):
                        runner.parse_probe_log(path)
            path.write_text(json.dumps(row)+"\n"+json.dumps(row)+"\n")
            with self.assertRaises(ValueError):
                runner.parse_probe_log(path)
            path.write_text("")
            with self.assertRaisesRegex(ValueError, "Missing"):
                runner.parse_probe_log(path)

    def test_trial_attribution_and_complete_counts(self):
        task = "fixture task"
        tasks = {"fixture": {"task_description": task, "episodes": 2, "outcomes": [True, False], "category": "unseen"}}
        requests = {i: dict(request_id=i, task=task, latency_ms=float(10+10*i), demo_episode_indices=[42+i]) for i in range(3)}
        rows = [dict(task=task, episode=0, success=True, steps=20, steps_attempted=20, failure_step=None, request_ids=[0, 1]),
                dict(task=task, episode=1, success=False, steps=30, steps_attempted=31, failure_step=31, request_ids=[2])]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trials.jsonl"
            def save(value):
                path.write_text("".join(json.dumps(row)+"\n" for row in value))
            save(rows)
            used = set()
            parsed = runner.collect_trials(path, tasks, requests, used)
            self.assertEqual(used, {0, 1, 2})
            self.assertEqual(parsed[0]["demo_episode_indices"], [42, 43])
            self.assertEqual(parsed[0]["request_latency_summary"], {"count": 2, "median_ms": 15, "p95_ms": 19.5})
            self.assertEqual(parsed[1]["failure_step"], 31)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                runner.collect_trials(path, tasks, requests, used)
            save(rows[:1])
            with self.assertRaisesRegex(ValueError, "Missing trial"):
                runner.collect_trials(path, tasks, requests, set())
            bad = copy.deepcopy(rows)
            bad[0]["success"] = False
            save(bad)
            with self.assertRaisesRegex(ValueError, "Inconsistent"):
                runner.collect_trials(path, tasks, requests, set())
            bad = copy.deepcopy(rows)
            bad[0]["request_ids"] = [99]
            save(bad)
            with self.assertRaisesRegex(ValueError, "Missing, duplicate"):
                runner.collect_trials(path, tasks, requests, set())

    def test_inference_probe_preserves_call_and_result(self):
        stream = io.StringIO()
        result = {"actions": object()}
        obs = {"prompt": "fixture task", "task_index": 2}
        original = mock.Mock(return_value=result)
        probe = serve_with_probe.InferenceProbe(original, stream)
        selected = SimpleNamespace(reshape=lambda *a: SimpleNamespace(tolist=lambda: [17, 19]))
        def infer(*args, **kwargs):
            probe.observe_demo({"selected_episode": selected})
            return original(*args, **kwargs)
        probe.original_infer = infer
        self.assertIs(probe.infer(obs), result)
        original.assert_called_once_with(obs)
        row = json.loads(stream.getvalue())
        self.assertEqual(row["demo_episode_indices"], [17, 19])
        self.assertEqual(row["request_id"], 0)
        self.assertGreaterEqual(row["latency_ms"], 0)

    def test_failed_inference_is_observed_and_preserves_exception(self):
        stream = io.StringIO()
        error = RuntimeError("synthetic inference failure")
        probe = serve_with_probe.InferenceProbe(None, stream)
        selected = SimpleNamespace(reshape=lambda *a: SimpleNamespace(tolist=lambda: [17]))
        def infer(obs):
            probe.observe_demo({"selected_episode": selected})
            raise error
        probe.original_infer = infer
        for index in range(2):
            with self.assertRaises(RuntimeError) as caught:
                probe.infer({"prompt": "fixture task", "task_index": 2})
            self.assertIs(caught.exception, error)
            row = json.loads(stream.getvalue().splitlines()[-1])
            self.assertEqual(row["request_id"], index)
            self.assertEqual(row["demo_episode_indices"], [17])
            self.assertEqual(row["error"], "RuntimeError")
            self.assertGreaterEqual(row["latency_ms"], 0)

    def test_trial_observer_counts_steps_and_preserves_actions_and_errors(self):
        stream = io.StringIO()
        observer = TrialObserver(SimpleNamespace(num_steps_wait=10), stream)
        def emit(message):
            observer.emit(logging.LogRecord("fixture", logging.INFO, "fixture", 1, message, (), None))
        observer.reset("fixture task", 0)
        action = [0.1, 0.2]
        result = (object(), 0.0, False, {})
        original = mock.Mock(return_value=result)
        self.assertIs(observer.step(original, action), result)
        self.assertEqual(observer.state["steps"], 0)  # reset/init work is outside the rollout.
        emit("Starting episode 1...")
        for _ in range(11):
            self.assertIs(observer.step(original, action), result)
        self.assertIs(original.call_args.args[0], action)
        emit("Success: True")
        row = json.loads(stream.getvalue())
        self.assertEqual((row["steps"], row["settling_steps"], row["policy_steps"]), (11, 10, 1))
        self.assertIsNone(row["failure_step"])

        observer.reset("fixture task", 1)
        emit("Starting episode 2...")
        error = RuntimeError("synthetic env failure")
        with self.assertRaises(RuntimeError) as caught:
            observer.step(mock.Mock(side_effect=error), action)
        self.assertIs(caught.exception, error)
        emit("Caught exception: synthetic env failure")
        emit("Success: False")
        row = json.loads(stream.getvalue().splitlines()[-1])
        self.assertEqual((row["steps"], row["steps_attempted"], row["failure_step"]), (0, 1, 1))


class BoundProtocolTests(unittest.TestCase):
    def test_successor_version_and_limits_are_checked_against_frozen_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ref = "contracts/baseline/v7.yaml"
            protocol = {"idea_id": "baseline", "version": 7, "stopping": {"timeout_seconds": 432000, "stall_seconds": 9000}}
            path = root / ref; path.parent.mkdir(parents=True)
            path.write_text(json.dumps(protocol))
            registry = {"schema_version": 1, "contracts": {ref: {"sha256": digest(path), "version": 7, "idea_id": "baseline"}}}
            (root / "contracts/.registry.json").write_text(json.dumps(registry))
            job = {"contract": ref, **protocol["stopping"]}
            runner.validate_bound_protocol(root, job, protocol, path)
            for field in ("timeout_seconds", "stall_seconds"):
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, "must equal"):
                    runner.validate_bound_protocol(root, dict(job, **{field: job[field]-1}), protocol, path)
            with self.assertRaisesRegex(ValueError, "version/hash"):
                runner.validate_bound_protocol(root, job, dict(protocol, version=2), path)
            snapshot = root / "snapshot.yaml"; snapshot.write_bytes(path.read_bytes()+b"\n")
            with self.assertRaisesRegex(ValueError, "version/hash"):
                runner.validate_bound_protocol(root, job, protocol, snapshot)
            with self.assertRaisesRegex(ValueError, "Run protocol binding"):
                runner.validate_bound_protocol(root, job, protocol, path, {"contract": {"path": ref, "sha256": "0"*64}})


class CheckpointTests(unittest.TestCase):
    def make_checkpoint(self, root):
        source = root / "scratch/ContextFlow/task/19999"
        (source / "params").mkdir(parents=True)
        (source / "assets/libero").mkdir(parents=True)
        (source / "params/shard").write_bytes(bytes(range(256)))
        (source / "assets/libero/norm_stats.json").write_text('{"fixture": true}\n')
        (source / "train_state").mkdir()
        (source / "train_state/optimizer").write_text("must remain on scratch")
        return source

    def test_copy_only_evaluation_payload_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_checkpoint(root)
            destination = root / "run/checkpoint/19999"
            rows = runner.copy_checkpoint(source, destination)
            self.assertEqual({r["path"] for r in rows}, {"params/shard", "assets/libero/norm_stats.json"})
            self.assertFalse((destination / "train_state").exists())
            for row in rows:
                self.assertEqual((source / row["path"]).read_bytes(), (destination / row["path"]).read_bytes())
            manifest = json.loads((destination.parent / "checkpoint-sha256.json").read_text())
            self.assertEqual(manifest["files"], rows)
            self.assertEqual(manifest["evaluated_path"], str(destination))
            with self.assertRaises(FileExistsError):
                runner.copy_checkpoint(source, destination)

    def test_copy_rejects_corruption_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_checkpoint(root)
            original = runner.shutil.copytree
            def corrupt(src, dst, *args, **kwargs):
                result = original(src, dst, *args, **kwargs)
                if Path(src).name == "params":
                    (Path(dst) / "shard").write_bytes(b"corrupted")
                return result
            with mock.patch.object(runner.shutil, "copytree", side_effect=corrupt):
                with self.assertRaisesRegex(ValueError, "verification failed"):
                    runner.copy_checkpoint(source, root / "bad/19999")
            (source / "params/link").symlink_to(source / "params/shard")
            with self.assertRaisesRegex(ValueError, "symlinks"):
                runner.copy_checkpoint(source, root / "linked/19999")


if __name__ == "__main__":
    unittest.main()
