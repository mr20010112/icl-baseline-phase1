#!/usr/bin/env python3
"""Launch the pinned official ContextFlow pipeline; training requires research.py run."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time

# Under the launcher this points at runs/<task>/code/tools, the reviewed snapshot.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from gates import digest, load_json, resource, resolve
from contracts import atomic_json, project_path, verify as verify_contract

METRICS = ("unseen_avg_success", "spatial_avg_success", "object_avg_success",
           "success_S1", "success_S2", "success_O1", "success_O2",
           "train_gpu_hours", "train_peak_gpu_mem_gb", "seen_avg_success",
           "infer_latency_ms_median", "infer_latency_ms_p95", "unseen_mean_steps_success")
TASKS = {
    "S1": "pick up the black bowl on the cookie box and place it on the plate",
    "S2": "pick up the black bowl next to the plate and place it on the plate",
    "O1": "pick up the milk and place it in the basket",
    "O2": "pick up the tomato sauce and place it in the basket",
}

# This child imports official code in the registered training interpreter. Selection
# is performed ONLY by the official function used by ContextFlow.data.create().
OFFICIAL_SPLIT_CHECK = r'''
import json, os, pathlib, sys
from openpi.training import config
from openpi.training.config_libero import LIBERO_UNSEEN_TASKS
seed, exp = sys.argv[1:3]
sys.argv = ["train.py", "ContextFlow", "--seed", seed, "--exp-name", exp,
            "--checkpoint-base-dir", os.environ["CONTEXTFLOW_CHECKPOINT_SCRATCH"]]
cfg = config.cli()
factory = cfg.data
from lerobot.common.datasets.lerobot_dataset import LeRobotDatasetMetadata
metadata = LeRobotDatasetMetadata(factory.repo_id, local_files_only=True)
assert pathlib.Path(metadata.root).resolve() == pathlib.Path(factory.episode_json_path).resolve().parent.parent
assert factory.remove_task_list == LIBERO_UNSEEN_TASKS
kept = config.get_kept_episode_indices(factory.episode_json_path, factory.remove_task_list)
rows = [json.loads(line) for line in pathlib.Path(factory.episode_json_path).read_text().splitlines() if line.strip()]
by_id = {int(row["episode_index"]): row for row in rows}
assert len(by_id) == len(rows) and kept and len(set(kept)) == len(kept)
for index in kept:
    assert not any(task in LIBERO_UNSEEN_TASKS for task in by_id[index]["tasks"]), index
assert cfg.seed == int(seed)
assert pathlib.Path(cfg.checkpoint_base_dir) == pathlib.Path(os.environ["CONTEXTFLOW_CHECKPOINT_SCRATCH"])
assert cfg.save_interval == 5000 and cfg.keep_period == 5000
assert cfg.num_train_steps == 20000 and cfg.batch_size == 32 and cfg.fsdp_devices == 1
assert cfg.data.sample_frames == 8 and cfg.data.sample_actions == 128
assert cfg.data.random_select and cfg.data.seed_base == 1
report = {"kept_episodes": len(kept), "removed_episodes": len(rows)-len(kept),
          "total_episodes": len(rows), "unseen_tasks": LIBERO_UNSEEN_TASKS,
          "seed": cfg.seed, "episode_json_path": factory.episode_json_path,
          "official_selector": "openpi.training.config.get_kept_episode_indices"}
pathlib.Path(os.environ["CONTEXTFLOW_SPLIT_REPORT"]).write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
'''


def parse_successes(log: str, results: dict, suite: str, trials: int = 50, all_tasks: bool = False) -> dict:
    """Read official Success logs; validate against official per-task JSON counts.

    No simulator state, reward, video filename or exception is interpreted here.
    """
    expected = {k: v for k, v in TASKS.items() if k.startswith("S" if suite == "libero_spatial" else "O")}
    if suite not in ("libero_spatial", "libero_object"):
        raise ValueError(f"Unexpected suite: {suite}")
    rows = results["per_task_results"]
    if all_tasks:
        if (len(rows) != 10 or len({r["task_description"] for r in rows}) != 10
                or len({r["task_id"] for r in rows}) != 10
                or {r["task_description"] for r in rows if r["category"] == "unseen"} != set(expected.values())
                or sum(r["category"] == "seen" for r in rows) != 8):
            raise ValueError("All-task pass requires eight seen and two protocol unseen tasks per suite")
        expected = {r["task_description"]: r["task_description"] for r in rows}
    outcomes = {name: [] for name in expected.values()}
    current = None
    for line in log.splitlines():
        task = re.search(r"(?:^|[\s:])Task: (.+?)\s*$", line)
        if task:
            current = task.group(1)
        success = re.search(r"(?:^|[\s:])Success: (True|False)\s*$", line)
        if success:
            if current not in outcomes:
                raise ValueError(f"Success without an expected task: {current}")
            outcomes[current].append(success.group(1) == "True")
    config = results["config"]
    if config["task_suite_name"] != suite or config["num_trials_per_task"] != trials or config["seed"] != 7:
        raise ValueError("Official evaluation config differs from protocol/default seed 7")
    if len(rows) != len(expected) or {r["task_description"] for r in rows} != set(expected.values()):
        raise ValueError("Expected exactly the two protocol tasks in official JSON")
    parsed = {}
    for key, description in expected.items():
        row = next(r for r in rows if r["task_description"] == description)
        values = outcomes[description]
        if (len(values) != trials or row["episodes"] != trials or (not all_tasks and row["category"] != "unseen")
                or row["successes"] != sum(values) or not math.isclose(row["success_rate"], sum(values)/trials)):
            raise ValueError(f"Incomplete or inconsistent official results: {key}")
        parsed[key] = {"task_description": description, "outcomes": values,
                       "successes": row["successes"], "episodes": trials,
                       "success_rate": float(row["success_rate"]), "category": row["category"]}
    summary = results["summary"]
    if (summary["total_episodes"] != len(expected)*trials or summary["total_successes"] != sum(sum(v) for v in outcomes.values())
            or summary["num_unseen_tasks"] != 2 or summary["num_seen_tasks"] != (8 if all_tasks else 0)
            or summary["num_tasks_evaluated"] != len(expected)):
        raise ValueError("Official summary does not cover the required tasks/trials")
    return parsed


def percentile(values, quantile):
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Missing inference latencies")
    position = (len(ordered)-1)*quantile
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] + (ordered[hi]-ordered[lo])*(position-lo)


def parse_probe_log(path: Path) -> dict:
    records = {}
    for line in path.read_text().splitlines():
        row = json.loads(line)
        index, latency, demos = row["request_id"], row["latency_ms"], row["demo_episode_indices"]
        if (type(index) is not int or index != len(records)
                or type(latency) not in (int, float) or not math.isfinite(latency) or latency < 0
                or not isinstance(demos, list) or not demos
                or any(type(i) is not int or i < 0 for i in demos)
                or not isinstance(row["task"], str) or type(row["task_index"]) is not int):
            raise ValueError("Invalid latency/demo-index observation")
        records[index] = row
    if not records:
        raise ValueError("Missing server observations")
    return records


def collect_trials(path: Path, tasks: dict, requests: dict, used_ids: set) -> list:
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    by_task = {r["task_description"]: r for r in tasks.values()}
    counts = {task: 0 for task in by_task}
    for row in rows:
        task = row["task"]
        if task not in by_task:
            raise ValueError("Unexpected trial task")
        number = counts[task]
        expected = by_task[task]
        if (row["episode"] != number or number >= expected["episodes"]
                or type(row["success"]) is not bool or row["success"] != expected["outcomes"][number]
                or type(row["steps"]) is not int or row["steps"] < 0
                or type(row["steps_attempted"]) is not int or not row["steps"] <= row["steps_attempted"] <= row["steps"]+1
                or (row["success"] and row["failure_step"] is not None)
                or (not row["success"] and (type(row["failure_step"]) is not int
                                            or not 1 <= row["failure_step"] <= row["steps_attempted"]+1))):
            raise ValueError("Inconsistent per-trial observations")
        counts[task] += 1
        samples = []
        for index in row["request_ids"]:
            if type(index) is not int or index in used_ids or index not in requests or requests[index]["task"] != task:
                raise ValueError("Missing, duplicate or mismatched inference request")
            used_ids.add(index)
            samples.append(requests[index])
        if row["success"] and not samples:
            raise ValueError("Successful trial has no inference requests")
        latencies = [r["latency_ms"] for r in samples]
        row.update(category=expected["category"], requests=samples,
                   demo_episode_indices=sorted({i for r in samples for i in r["demo_episode_indices"]}),
                   request_latency_summary={"count": len(samples),
                       "median_ms": percentile(latencies, .5) if samples else None,
                       "p95_ms": percentile(latencies, .95) if samples else None})
    if any(counts[t] != by_task[t]["episodes"] for t in counts):
        raise ValueError("Missing trial observations")
    return rows


def checkpoint_inventory(path: Path) -> list:
    entries = []
    for part in ("params", "assets"):
        entries.append(path / part)
        entries.extend((path / part).rglob("*"))
    if path.is_symlink() or any(p.is_symlink() for p in entries):
        raise ValueError("Checkpoint copy must not contain symlinks")
    rows = [{"path": p.relative_to(path).as_posix(), "bytes": p.stat().st_size, "sha256": digest(p)}
            for p in sorted(entries) if p.is_file()]
    for part in ("params", "assets"):
        if not (path / part).is_dir() or not any(r["path"].startswith(part+"/") for r in rows):
            raise ValueError(f"Missing checkpoint {part} payload")
    return rows


def copy_checkpoint(source: Path, destination: Path) -> list:
    # Hash only the evaluation payload, leaving optimizer state on scratch.
    expected = checkpoint_inventory(source)
    destination.mkdir(parents=True, exist_ok=False)
    for part in ("params", "assets"):
        shutil.copytree(source / part, destination / part)
    actual = checkpoint_inventory(destination)
    if expected != actual:
        raise ValueError("Checkpoint copy verification failed (byte SHA256/size/path mismatch)")
    atomic_json(destination.parent / "checkpoint-sha256.json", {"files": actual,
                "source": str(source), "evaluated_path": str(destination)})
    return actual


def write_metrics(path: Path, tasks: dict, gpu_hours: float, peak_gb: float,
                  all_tasks: dict, unseen_trials: list) -> dict:
    if set(tasks) != set(TASKS):
        raise ValueError("Metrics require all four tasks")
    values = {f"success_{key}": float(tasks[key]["success_rate"]) for key in TASKS}
    if any(not 0 <= value <= 1 for value in values.values()):
        raise ValueError("Success fractions must lie in [0,1]")
    values.update(spatial_avg_success=(values["success_S1"]+values["success_S2"])/2,
                  object_avg_success=(values["success_O1"]+values["success_O2"])/2,
                  unseen_avg_success=sum(values.values())/4,
                  train_gpu_hours=float(gpu_hours), train_peak_gpu_mem_gb=float(peak_gb))
    seen = [t["success_rate"] for t in all_tasks.values() if t["category"] == "seen"]
    if len(seen) != 16 or any(not 0 <= rate <= 1 for rate in seen):
        raise ValueError("Metrics require exactly 16 seen tasks from the all-task pass")
    latencies = [r["latency_ms"] for trial in unseen_trials for r in trial["requests"]]
    steps = [trial["steps"] for trial in unseen_trials if trial["success"]]
    values.update(seen_avg_success=float(sum(seen)/16),
                  infer_latency_ms_median=float(percentile(latencies, .5)),
                  infer_latency_ms_p95=float(percentile(latencies, .95)),
                  unseen_mean_steps_success=float(sum(steps)/len(steps)) if steps else -1.0)
    if (set(values) != set(METRICS) or any(not math.isfinite(v) or
            (v < 0 and not (key == "unseen_mean_steps_success" and v == -1)) for key, v in values.items())):
        raise ValueError("Metrics must be exactly the thirteen finite protocol floats")
    atomic_json(path, {key: values[key] for key in METRICS})
    return values


@contextmanager
def step(out: Path, name: str):
    path = out / "logs" / f"{name}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", buffering=1) as log:
        print(f"STEP {name}", flush=True)
        try:
            yield log
        except BaseException as exc:
            log.write(f"ERROR {type(exc).__name__}: {exc}\nexit_code={getattr(exc, 'returncode', 1)}\n")
            raise
        else:
            log.write("exit_code=0\n")


def stop_process(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def execute(command, cwd, env, log, sample=None):
    log.write("command=" + shlex.join(command) + "\ncwd=" + str(cwd) + "\n")
    log.flush()
    started = time.monotonic()
    proc = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=log, stderr=subprocess.STDOUT)
    previous_size = 0
    last_sample = 0.0
    try:
        while proc.poll() is None:
            now = time.monotonic()
            if sample and now-last_sample >= 2:
                sample(now-started)
                last_sample = now
            size = os.fstat(log.fileno()).st_size
            if size != previous_size:
                # Launcher stall detection observes stdout, stderr or progress.json.
                print(f"official output: {Path(log.name).name} bytes={size}", flush=True)
                previous_size = size
            time.sleep(0.2)
        elapsed = time.monotonic()-started
        log.write(f"command_exit_code={proc.returncode}\nwall_seconds={elapsed:.6f}\n")
        if proc.returncode:
            raise subprocess.CalledProcessError(proc.returncode, command)
        return elapsed
    finally:
        stop_process(proc)


def commands(repo: Path, python: str, client: str, out: Path, seed: int, port: int, task_id: str,
             scratch: Path):
    exp = task_id
    work = out / "work"
    checkpoint = out / "checkpoint" / "19999"
    wrapper = Path(__file__).resolve().parent
    plan = {
        "norm": [python, str(repo / "scripts/compute_norm_stats.py"), "--config-name", "ContextFlow"],
        "train": [python, str(repo / "scripts/train.py"), "ContextFlow", "--seed", str(seed), "--exp-name", exp,
                  "--checkpoint-base-dir", str(scratch)],
        "server": [python, str(wrapper / "serve_with_probe.py"), "--port", str(port), "policy:checkpoint",
                   "--policy.inference_dtype=float32", "--policy.config=ContextFlow", "--policy.dir", str(checkpoint)],
    }
    for phase, trials in (("unseen", 50), ("all_tasks", 20)):
        for suite in ("libero_spatial", "libero_object"):
            plan[f"{phase}_{suite}"] = [client, str(wrapper / "eval_with_probe.py"), "--host", "127.0.0.1",
                       "--port", str(port), "--task-suite-name", suite, "--num-trials-per-task", str(trials),
                       "--unseen-only" if phase == "unseen" else "--no-unseen-only",
                       "--results-out-path", str(out / "eval" / phase / f"{suite}.json"),
                       "--video-out-path", str(out / "eval" / phase / suite / "videos")]
    return work, checkpoint, plan


def command_environments(out: Path) -> dict:
    result = {"train": {"XLA_PYTHON_CLIENT_MEM_FRACTION": "0.9"},
              "server": {"JAX_DEFAULT_MATMUL_PRECISION": "float32"}}
    for phase in ("unseen", "all_tasks"):
        for suite in ("libero_spatial", "libero_object"):
            result[f"{phase}_{suite}"] = {"CONTEXTFLOW_TRIAL_LOG": str(out / "eval" / phase / f"{suite}-trials.jsonl")}
    return result


def checked_checkout(repo: Path, commit: str, log):
    for argv in (["git", "-C", str(repo), "rev-parse", "HEAD"],
                 ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"]):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        log.write(shlex.join(argv) + f"\n{result.stdout}{result.stderr}command_exit_code={result.returncode}\n")
        result.check_returncode()
        if ("rev-parse" in argv and result.stdout.strip() != commit) or ("status" in argv and result.stdout.strip()):
            raise ValueError("ContextFlow must be at the protocol commit with a clean checkout")


def registered_path(root, row):
    return resolve(root, row.get("path"), file=False).absolute()


def validate_bound_protocol(root, job, protocol, protocol_path, manifest=None):
    """Accept the declared frozen version, including reviewed limit successors."""
    record = verify_contract(root, job["contract"])
    declared = project_path(root, job["contract"])
    if (declared.name != f"v{protocol['version']}.yaml" or record["version"] != protocol["version"]
            or record["idea_id"] != protocol["idea_id"] or digest(protocol_path) != record["sha256"]):
        raise ValueError("Bound protocol version/hash differs from its frozen registration")
    if manifest is not None and (manifest["contract"]["path"] != job["contract"]
                                 or manifest["contract"]["sha256"] != record["sha256"]):
        raise ValueError("Run protocol binding differs from declared frozen protocol")
    if any(job[field] != protocol["stopping"][field] for field in ("timeout_seconds", "stall_seconds")):
        raise ValueError("Job timeout/stall must equal the bound frozen stopping values")


def run(args):
    root = Path.cwd().resolve()
    if not args.dry_run and args.run_dir:
        raise ValueError("--run-dir is for dry-run only")
    out_value = args.run_dir if args.dry_run and args.run_dir else os.environ.get("RESEARCH_RUN_DIR")
    if not out_value:
        raise ValueError("RESEARCH_RUN_DIR is required (or --run-dir for dry-run)")
    out = Path(out_value).expanduser().resolve()
    if args.dry_run and out.exists() and any(out.iterdir()):
        raise ValueError("Dry-run directory must be new or empty; retain previous evidence")
    out.mkdir(parents=True, exist_ok=True)
    if args.dry_run:
        job = load_json(root / (args.job or f"experiments/baseline-seed{args.seed}.json"))
        protocol = load_json(root / job["contract"])
        config = load_json(root / job["config"])
        validate_bound_protocol(root, job, protocol, root / job["contract"])
    else:
        manifest = load_json(out / "manifest.json")
        job = manifest["job"]
        if manifest["status"] != "running" or out != root / "runs" / job["task_id"]:
            raise ValueError("Training must be launched by tools/research.py run")
        if os.environ.get("RESEARCH_SEED") != str(args.seed):
            raise ValueError("RESEARCH_SEED differs from --seed")
        protocol = load_json(out / "contract.yaml")
        config = load_json(Path(os.environ["RESEARCH_CONFIG"]))
        validate_bound_protocol(root, job, protocol, out / "contract.yaml", manifest)
    if (job["seed"] != args.seed or args.seed not in protocol["seeds"]["values"]
            or job["gpus"] != 1 or job["stage"] != "baseline" or job["idea_id"] != "baseline"
            or config["hyperparameters"] != protocol["hyperparameters"]
            or job["required_metrics"] != list(METRICS)):
        raise ValueError("Job/config does not implement baseline v2")
    research = load_json(root / "configs/research.json")
    if research["baseline"]["repo_path"] == "<OPERATOR_CONTEXTFLOW_CHECKOUT>":
        raise ValueError("Missing evidence: <OPERATOR_CONTEXTFLOW_CHECKOUT>; set "
                         "configs/research.json:baseline.repo_path to your verified "
                         "official ContextFlow checkout's absolute path")
    repo = resolve(root, research["baseline"]["repo_path"], file=False).resolve()
    if out.is_relative_to(repo):
        raise ValueError("Run directory must be outside the read-only ContextFlow checkout")
    details = {"dry_run": args.dry_run, "seed": args.seed, "task_id": job["task_id"],
               "protocol_sha256": digest(root / job["contract"]), "commands": {}, "tasks": {}}
    atomic_json(out / "details.json", details)
    with step(out, "01-checkout") as log:
        checked_checkout(repo, protocol["baseline"]["commit"], log)
    scratch_value = os.environ.get("CONTEXTFLOW_CHECKPOINT_SCRATCH")
    scratch = Path(scratch_value).expanduser().resolve() if scratch_value else Path("/<CONTEXTFLOW_CHECKPOINT_SCRATCH>")
    client_value = os.environ.get("CONTEXTFLOW_LIBERO_PYTHON", "<CONTEXTFLOW_LIBERO_PYTHON>")
    port = int(os.environ.get("CONTEXTFLOW_SERVER_PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("CONTEXTFLOW_SERVER_PORT must be in 1..65535")
    # Print the entire plan even when registration blocks preflight. Unregistered
    # interpreters/paths are explicitly placeholders, never execution fallbacks.
    entries = load_json(root / "configs/resources.json").get("environments", [])
    python_plan = next((r["path"] for r in entries if r["id"] == job["environment_id"]), "<REGISTERED_CONTEXTFLOW_PYTHON>")
    work, checkpoint, plan = commands(repo, python_plan, client_value, out, args.seed, port, job["task_id"], scratch)
    details.update(commands=plan, cwd=str(work), checkpoint_path=str(checkpoint),
                   command_environment=command_environments(out),
                   scratch_checkpoint_path=str(scratch / "ContextFlow" / job["task_id"] / "19999"))
    atomic_json(out / "details.json", details)
    for name, command in plan.items():
        common = {"OPENPI_PROJECT_ROOT": str(repo), "CONTEXTFLOW_PROBE_LOG": str(out / "eval/server-requests.jsonl")}
        prefix = " ".join(f"{k}={shlex.quote(v)}" for k, v in dict(common, **details["command_environment"].get(name, {})).items())
        print(f"planned {name}: cd {shlex.quote(str(work))} && {prefix} {shlex.join(command)}", flush=True)
    with step(out, "02-data") as log:
        data = resource(root, "data", job["dataset_id"], "real")
        data_dir = registered_path(root, data).resolve()
        for key in ("version", "split", "fingerprint"):
            if data[key] != protocol["data"][key]:
                raise ValueError(f"Registered data differs from protocol: {key}")
        if data_dir.name != "libero" or data_dir.parent.name != "physical-intelligence":
            raise ValueError("Data path must end in physical-intelligence/libero for official LEROBOT_HOME lookup")
        details["data"] = {"path": str(data_dir), "fingerprint": data["fingerprint"]}
        log.write(json.dumps(details["data"]) + "\n")
        atomic_json(out / "data-fingerprint.json", details["data"])
        environment = resource(root, "environments", job["environment_id"], "real")
        python = str(registered_path(root, environment))
        # Keep the venv executable path (resolving symlinks would discard its environment).
        if not args.dry_run and not Path(python).samefile(sys.executable):
            raise ValueError("Launcher must use the registered training interpreter")
        compute = resource(root, "compute", job["resource_id"], "real")
        if compute["gpus"] < 1 or compute["cpus"] < job["cpus"]:
            raise ValueError("Registered compute is insufficient")
    if client_value == "<CONTEXTFLOW_LIBERO_PYTHON>":
        raise ValueError("Set CONTEXTFLOW_LIBERO_PYTHON to the official Python 3.8 client interpreter")
    client = str(Path(client_value).expanduser().absolute())
    if not Path(client).is_file() or not os.access(client, os.X_OK):
        raise ValueError("CONTEXTFLOW_LIBERO_PYTHON is not executable")
    if not scratch_value or not Path(scratch_value).expanduser().is_absolute():
        raise ValueError("Set CONTEXTFLOW_CHECKPOINT_SCRATCH to an absolute operator scratch directory")
    if scratch.is_relative_to(out) or out.is_relative_to(scratch) or scratch.is_relative_to(repo):
        raise ValueError("Checkpoint scratch must be separate from run dir and official checkout")
    scratch_checkpoint = scratch / "ContextFlow" / job["task_id"] / "19999"
    if scratch_checkpoint.parent.exists():
        raise ValueError("Scratch experiment directory already exists; retain evidence and use a new task ID")
    work, checkpoint, plan = commands(repo, python, client, out, args.seed, port, job["task_id"], scratch)
    work.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1", PYTHONOPTIMIZE="0", HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1",
               LEROBOT_HOME=str(data_dir.parent.parent), OPENPI_PROJECT_ROOT=str(repo),
               PYTHONPATH=os.pathsep.join(str(repo / p) for p in ("src", "third_party/libero", "packages/openpi-client/src")),
               CONTEXTFLOW_SPLIT_REPORT=str(out / "leakage.json"),
               CONTEXTFLOW_CHECKPOINT_SCRATCH=str(scratch),
               CONTEXTFLOW_PROBE_LOG=str(out / "eval" / "server-requests.jsonl"))
    # Default only for logging/rendering; all model/data hyperparameters remain official.
    env.setdefault("WANDB_MODE", "offline")
    env.setdefault("MUJOCO_GL", "egl")
    with step(out, "03-leakage") as log:
        execute([python, "-c", OFFICIAL_SPLIT_CHECK, str(args.seed), job["task_id"]], work, env, log)
        details["leakage"] = load_json(out / "leakage.json")
        for interpreter, version in ((python, "3.11"), (client, "3.8")):
            result = subprocess.run([interpreter, "-c", "import sys; print('%s.%s' % sys.version_info[:2])"],
                                    capture_output=True, text=True, timeout=60, env=env)
            log.write(f"interpreter={interpreter} version={result.stdout.strip()} command_exit_code={result.returncode}\n")
            result.check_returncode()
            if result.stdout.strip() != version:
                raise ValueError(f"Interpreter must be Python {version}: {interpreter}")
    with step(out, "04-weights") as log:
        cache = os.environ.get("OPENPI_DATA_HOME")
        if not cache:
            raise ValueError("OPENPI_DATA_HOME must explicitly identify the prepared official cache")
        cache = Path(cache).expanduser().resolve(strict=True)
        params = cache / "openpi-assets/checkpoints/pi0_base/params"
        if not params.is_dir():
            raise ValueError(f"Missing pi0_base params: {params}; download separately")
        # Official download.maybe_download invalidates pre-Feb-3-2025 cache entries.
        if params.stat().st_mtime <= 1738540800:
            raise ValueError("pi0_base cache is expired according to official download.py")
        files = sorted(p for p in params.rglob("*") if p.is_file())
        if not files:
            raise ValueError("Empty pi0_base params")
        if any(p.is_symlink() for p in params.rglob("*")):
            raise ValueError("pi0_base params must be a complete physical cache, without symlinks")
        if len(job.get("weight_ids", [])) != 1:
            raise ValueError("Job must register exactly one pi0_base params weight resource")
        weights = resource(root, "weights", job["weight_ids"][0], "real")
        if registered_path(root, weights).resolve() != params:
            raise ValueError("Registered weights must point at OPENPI_DATA_HOME pi0_base/params")
        rows = [{"path": p.relative_to(params).as_posix(), "bytes": p.stat().st_size, "sha256": digest(p)} for p in files]
        atomic_json(out / "pi0-base-sha256.json", {"path": str(params), "fingerprint": weights["fingerprint"], "files": rows})
        # data.create() instantiates this official tokenizer; require it pre-cached.
        tokenizer = cache / "big_vision/paligemma_tokenizer.model"
        if not tokenizer.is_file() or tokenizer.stat().st_size == 0:
            raise ValueError(f"Missing official tokenizer cache: {tokenizer}; prepare separately")
        env["OPENPI_DATA_HOME"] = str(cache)
        details["tokenizer"] = {"path": str(tokenizer), "sha256": digest(tokenizer)}
        log.write(f"pi0_base files={len(rows)} fingerprint={weights['fingerprint']}\n")
    details.update(commands=plan, cwd=str(work), checkpoint_path=str(checkpoint),
                   command_environment=command_environments(out),
                   environment={k: env[k] for k in ("LEROBOT_HOME", "OPENPI_DATA_HOME", "PYTHONPATH", "OPENPI_PROJECT_ROOT", "HF_HUB_OFFLINE", "HF_DATASETS_OFFLINE", "WANDB_MODE", "MUJOCO_GL", "CONTEXTFLOW_CHECKPOINT_SCRATCH", "CONTEXTFLOW_PROBE_LOG")})
    details["environment"].update({k: env[k] for k in ("CUDA_VISIBLE_DEVICES", "JAX_PLATFORMS", "XLA_FLAGS", "XLA_PYTHON_CLIENT_PREALLOCATE") if k in env})
    atomic_json(out / "details.json", details)
    print("environment: " + json.dumps(details["environment"], sort_keys=True), flush=True)
    for name, command in plan.items():
        extra_env = details["command_environment"].get(name, {})
        prefix = " ".join(f"{k}={shlex.quote(v)}" for k, v in extra_env.items())
        print(f"{name}: cd {shlex.quote(str(work))} && {prefix} {shlex.join(command)}", flush=True)
    if args.dry_run:
        print("DRY RUN complete: checks only; no normalization, training, server or evaluation was run.")
        return
    visible = env.get("CUDA_VISIBLE_DEVICES", "")
    if not visible or len(visible.split(",")) != 1:
        raise ValueError("Set CUDA_VISIBLE_DEVICES to exactly one GPU index or UUID")
    if env.get("JAX_PLATFORMS") == "cpu":
        raise ValueError("JAX_PLATFORMS=cpu cannot execute this protocol")
    peak = 0.0
    with step(out, "05-norm-stats") as log:
        execute(plan["norm"], work, env, log)
    with step(out, "06-train") as log, (out / "logs/gpu-memory.csv").open("x", buffering=1) as memory:
        memory.write("elapsed_seconds,gpu_uuid,total_mib,used_mib\n")
        def sample(elapsed):
            nonlocal peak
            cmd = ["nvidia-smi", "--id", visible, "--query-gpu=uuid,memory.total,memory.used", "--format=csv,noheader,nounits"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            result.check_returncode()
            lines = result.stdout.strip().splitlines()
            if len(lines) != 1:
                raise ValueError("nvidia-smi must report exactly the selected GPU")
            uuid, total, used = (v.strip() for v in lines[0].split(","))
            if float(total)*1024**2 < 40e9:
                raise ValueError("Protocol requires >=40 GB GPU memory")
            peak = max(peak, float(used)*1024**2/1e9)
            memory.write(f"{elapsed:.3f},{uuid},{total},{used}\n")
        sample(0)
        train_env = dict(env, XLA_PYTHON_CLIENT_MEM_FRACTION="0.9")
        train_seconds = execute(plan["train"], work, train_env, log, sample)
        details["checkpoint_files"] = copy_checkpoint(scratch_checkpoint, checkpoint)
    details["training"] = {"wall_seconds": train_seconds, "gpus": 1, "peak_gpu_mem_gb": peak,
                           "sample_seconds": 2, "XLA_PYTHON_CLIENT_MEM_FRACTION": "0.9"}
    atomic_json(out / "details.json", details)
    server_env = dict(env, JAX_DEFAULT_MATMUL_PRECISION="float32")
    (out / "eval").mkdir(exist_ok=True)
    details.update(all_tasks={}, trials={"unseen": [], "all_tasks": []})
    used_ids = set()
    with step(out, "07-server") as server_log:
        # Refuse a pre-existing listener, so readiness cannot attach to another policy.
        with socket.socket() as sock:
            sock.bind(("0.0.0.0", port))
        server_log.write("command=" + shlex.join(plan["server"]) + "\nJAX_DEFAULT_MATMUL_PRECISION=float32\n")
        server_log.flush()
        server = subprocess.Popen(plan["server"], cwd=work, env=server_env, stdin=subprocess.DEVNULL,
                                  stdout=server_log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+600
            while True:
                if server.poll() is not None:
                    raise subprocess.CalledProcessError(server.returncode or 1, plan["server"])
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=1):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Policy server port was not ready within 600 seconds")
                    time.sleep(1)
            number = 8
            for phase, count in (("unseen", 50), ("all_tasks", 20)):
                (out / "eval" / phase).mkdir(exist_ok=True)
                for suite in ("libero_spatial", "libero_object"):
                    trial_log = out / "eval" / phase / f"{suite}-trials.jsonl"
                    client_env = dict(env, CONTEXTFLOW_TRIAL_LOG=str(trial_log))
                    with step(out, f"{number:02d}-{phase}-{suite}") as log:
                        execute(plan[f"{phase}_{suite}"], work, client_env, log)
                        log.flush()
                        tasks = parse_successes(Path(log.name).read_text(),
                            load_json(out / "eval" / phase / f"{suite}.json"), suite, count, phase == "all_tasks")
                        details["tasks" if phase == "unseen" else "all_tasks"].update(tasks)
                        requests = parse_probe_log(Path(env["CONTEXTFLOW_PROBE_LOG"]))
                        details["trials"][phase].extend(collect_trials(trial_log, tasks, requests, used_ids))
                        atomic_json(out / "details.json", details)
                    number += 1
                    if server.poll() is not None:
                        raise RuntimeError("Policy server exited during evaluation")
        finally:
            stop_process(server)
            server_log.write(f"server_exit_code={server.returncode} (runner shutdown)\n")
            details["server"] = {"exit_code": server.returncode, "JAX_DEFAULT_MATMUL_PRECISION": "float32"}
            atomic_json(out / "details.json", details)
    with step(out, "12-metrics") as log:
        checked_checkout(repo, protocol["baseline"]["commit"], log)
        if set(parse_probe_log(Path(env["CONTEXTFLOW_PROBE_LOG"]))) != used_ids:
            raise ValueError("Unattributed server requests invalidate the diagnostics")
        if checkpoint_inventory(checkpoint) != details["checkpoint_files"]:
            raise ValueError("Evaluated checkpoint changed after copy verification")
        details["no_successful_unseen_episodes"] = not any(t["success"] for t in details["trials"]["unseen"])
        atomic_json(out / "details.json", details)
        write_metrics(out / "metrics.json", details["tasks"], train_seconds/3600, peak,
                      details["all_tasks"], details["trials"]["unseen"])
        log.write("metrics.json written from official client output\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--job", help="Dry-run job file (default: seed-specific job)")
    parser.add_argument("--run-dir", help="Dry-run evidence directory; use a fresh directory")
    args = parser.parse_args()
    if args.job and not args.dry_run:
        parser.error("--job is for dry-run; normal runs read the launcher manifest")
    def interrupted(signum, frame):
        raise InterruptedError(f"Runner received signal {signum}")
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, interrupted)
    try:
        run(args)
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(f"BLOCKED/FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
