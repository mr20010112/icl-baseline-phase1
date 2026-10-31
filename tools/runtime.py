#!/usr/bin/env python3
"""Bounded, restart-safe local experiment launcher; stdlib only.

Execution status is never a scientific acceptance verdict. The project launch
ledger does not duplicate ARIS's workflow phase state.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import time
from typing import Any, Iterator

try:
    from contracts import ProjectError, load, atomic_json, sha, verify
except ImportError:
    from .contracts import ProjectError, load, atomic_json, sha, verify

from run_evidence import execution_binding, execution_command, check_snapshots

ACTIVE = {"queued", "running", "unconfirmed"}
TERMINAL = {"completed", "failed", "timeout", "stalled", "interrupted"}
# Process handles are kept only while this launcher Python session is alive.
# Durable ownership and recovery continue to use manifests, never this cache.
_children: dict[int, subprocess.Popen[Any]] = {}


def _reap_children() -> None:
    for pid, process in list(_children.items()):
        if process.poll() is not None:
            del _children[pid]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def inside(root: Path, path: str | Path) -> Path:
    p = (root / path).resolve()
    if not p.is_relative_to(root.resolve()):
        raise ProjectError(f"path outside project: {path}")
    return p


def ident(task: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", task):
        raise ProjectError("task_id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,100}")
    return task


@contextmanager
def lock(root: Path) -> Iterator[None]:
    try:
        import fcntl
    except ImportError as exc:
        raise ProjectError("local launcher requires POSIX flock; remote jobs use handoff") from exc
    p = root / ".aris/project-runtime/launch.lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def start_identity(pid: int | None) -> str | None:
    """Linux process start ticks avoid treating a reused PID as our worker."""
    if not pid:
        return None
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        fields = raw[raw.rfind(")") + 2:].split()
        if fields[0] == "Z":
            return None
        return fields[19]  # field 22, after the comm field
    except (FileNotFoundError, ProcessLookupError, IndexError, PermissionError):
        return None


def process_observation(pid: int | None, identity: str | None) -> dict[str, Any]:
    """Observe existence without equating an unavailable /proc with death.

    kill(pid, 0) cannot prove identity, and is never grounds for success or
    killing a process. Resume only observes and never submits another worker.
    """
    if not pid:
        return {"exists": False, "identity_verified": False, "warning": "no process registered"}
    current = start_identity(pid)
    if identity is not None and current is not None:
        if current == identity:
            return {"exists": True, "identity_verified": True}
        return {"exists": False, "identity_verified": True, "warning": "PID was reused; recorded process has exited"}
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return {"exists": False, "identity_verified": False, "warning": "process is definitely absent"}
    except PermissionError:
        return {"exists": True, "identity_verified": False, "warning": "process exists but identity is not verifiable (permission denied)"}
    except OSError as exc:
        return {"exists": None, "identity_verified": False, "warning": f"process existence unknown: {exc}"}
    return {"exists": True, "identity_verified": False, "warning": "process exists; start identity unavailable, e.g. /proc is not mounted"}


def alive(pid: int | None, identity: str | None) -> bool:
    observation = process_observation(pid, identity)
    return observation["exists"] is True


def manifests(root: Path) -> list[dict[str, Any]]:
    result = []
    for p in sorted((root / "runs").glob("*/manifest.json")):
        result.append(load(p))
    return result


def number(value: Any, name: str, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ProjectError(f"{name} must be finite numeric")
    if value < 0 or (positive and value <= 0):
        raise ProjectError(f"{name} outside permitted range")
    return float(value)


def validate_job(job: dict[str, Any]) -> None:
    for key in ("task_id", "kind", "stage", "idea_id", "contract", "command", "config", "seed", "dataset_id", "environment_id", "resource_id", "estimated", "timeout_seconds", "stall_seconds", "required_metrics", "code_paths"):
        if key not in job:
            raise ProjectError(f"job missing {key}")
    ident(job["task_id"])
    if job["kind"] not in {"toy", "real"}:
        raise ProjectError("job kind must be toy or real")
    if job["stage"] not in {"baseline", "sanity", "pilot", "formal", "analysis"}:
        raise ProjectError("unknown experiment stage")
    if not isinstance(job["command"], list) or not job["command"] or any(not isinstance(x, str) for x in job["command"]):
        raise ProjectError("command must be a non-empty argv list; shell strings unsupported")
    if not isinstance(job["seed"], int) or isinstance(job["seed"], bool):
        raise ProjectError("seed must be integer")
    if not isinstance(job["code_paths"], list) or not job["code_paths"]:
        raise ProjectError("code_paths must identify the implementation")
    if not isinstance(job["required_metrics"], list) or not job["required_metrics"] or any(not isinstance(m, str) or not m for m in job["required_metrics"]):
        raise ProjectError("required_metrics must be a non-empty list of metric names")
    number(job["timeout_seconds"], "timeout_seconds", True)
    number(job["stall_seconds"], "stall_seconds", True)
    number(job.get("cpus", 1), "cpus", True)
    number(job.get("gpus", 0), "gpus")
    if not isinstance(job.get("cpus", 1), int) or not isinstance(job.get("gpus", 0), int):
        raise ProjectError("cpus/gpus must be integers")
    number(job.get("cost_per_hour", 0), "cost_per_hour")
    for key in ("cpu_seconds", "gpu_hours", "cost_usd"):
        number(job["estimated"].get(key), f"estimated.{key}")


def reservation(job: dict[str, Any]) -> dict[str, float]:
    timeout = float(job["timeout_seconds"])
    return {
        "cpu_seconds": max(job["estimated"]["cpu_seconds"], timeout * job.get("cpus", 1)),
        "gpu_hours": max(job["estimated"]["gpu_hours"], timeout * job.get("gpus", 0) / 3600),
        "cost_usd": max(job["estimated"]["cost_usd"], timeout * job.get("cost_per_hour", 0) / 3600),
    }


def check_budget(root: Path, job: dict[str, Any], reserve: dict[str, float]) -> dict[str, Any]:
    global_cfg = load(root / "configs/budget.json")
    if job["kind"] == "real" and global_cfg.get("real_enabled") is not True:
        raise ProjectError("real experiment budget is not enabled")
    all_existing = manifests(root)
    scope_cfg = global_cfg.get("scopes", {}).get(job["kind"], global_cfg)
    scope_existing = [m for m in all_existing if m.get("kind") == job["kind"]]
    # A per-kind allowance never enlarges the overall project budget.
    for scope, cfg, existing in (("global", global_cfg, all_existing), (job["kind"], scope_cfg, scope_existing)):
        attempts = cfg.get("max_attempts")
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
            raise ProjectError(f"{scope}.max_attempts must be a nonnegative integer")
        if len(existing) >= attempts:
            raise ProjectError(f"budget exhausted: {scope}.max_attempts (all attempts count)")
        for key, value in reserve.items():
            cap = number(cfg.get(f"max_{key}"), f"{scope}.max_{key}")
            used = sum(x["reservation"][key] for x in existing)
            if used + value > cap + 1e-12:
                raise ProjectError(f"budget exceeded: {scope}.{key}: reserved={used}, next={value}, cap={cap}")
    if job.get("retry_of"):
        prior = next((x for x in scope_existing if x["task_id"] == job["retry_of"]), None)
        if prior is None or prior["status"] not in {"failed", "timeout", "stalled", "interrupted"}:
            raise ProjectError("retry_of must refer to a confirmed failed/timeout/stalled/interrupted task")
        origin = prior.get("retry_origin", prior["task_id"])
        count = sum(x.get("retry_origin") == origin for x in scope_existing)
        if count >= min(global_cfg["max_retries"], scope_cfg["max_retries"]):
            raise ProjectError("bounded retry limit reached")
        return {"retry_origin": origin, "retry_index": count + 1}
    return {}


def metric_names(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return set().union(*(metric_names(x) for x in value)) if value else set()
    if isinstance(value, dict):
        if isinstance(value.get("name"), str):
            return {value["name"]}
        return set(value)
    raise ProjectError("frozen metrics must use names or {name: ...} records")


def bind_config(job: dict[str, Any], config: dict[str, Any], protocol: dict[str, Any]) -> None:
    if config.get("hyperparameters") != protocol["hyperparameters"]:
        raise ProjectError("configuration hyperparameters differ from frozen protocol; create a new version")
    data = protocol["data"]
    dataset = data.get("dataset_id", data.get("id"))
    if not dataset or job["dataset_id"] != dataset or config.get("dataset_id") != dataset:
        raise ProjectError("job/config dataset_id differs from frozen protocol")
    if config.get("split") != data["split"]:
        raise ProjectError("configuration split differs from frozen protocol")
    if config.get("seed") != job["seed"] and job["seed"] not in config.get("seeds", []):
        raise ProjectError("configuration seed differs from job seed")
    names = metric_names(protocol["metrics"]["primary"]) | metric_names(protocol["metrics"]["secondary"])
    if set(job["required_metrics"]) != names:
        raise ProjectError("required_metrics must match every frozen primary and secondary metric name")
    stopping = protocol["stopping"]
    if isinstance(stopping, dict):
        for field in ("timeout_seconds", "stall_seconds"):
            if field in stopping and job[field] > number(stopping[field], "stopping." + field, True):
                raise ProjectError(f"job {field} exceeds frozen stopping policy")


def check_protocol_budget(root: Path, job: dict[str, Any], protocol: dict[str, Any], reserve: dict[str, float]) -> None:
    cfg = protocol["budget"]
    existing = [r for r in manifests(root) if r.get("contract", {}).get("path") == inside(root, job["contract"]).relative_to(root).as_posix()]
    for key, value in reserve.items():
        cap_key = "max_" + key
        if cap_key not in cfg:
            raise ProjectError(f"frozen protocol budget requires {cap_key}")
        cap = number(cfg[cap_key], "protocol budget." + cap_key)
        if sum(r["reservation"][key] for r in existing) + value > cap + 1e-12:
            raise ProjectError(f"frozen protocol budget exceeded: {key}")
    if "max_attempts" not in cfg or len(existing) >= cfg["max_attempts"]:
        raise ProjectError("frozen protocol max_attempts exhausted or unspecified")


def resource_snapshots(root: Path, job: dict[str, Any]) -> dict[str, Any]:
    registry = load(root / "configs/resources.json")
    result = {}
    for group, key in (("data", "dataset_id"), ("environments", "environment_id"), ("compute", "resource_id")):
        result[group] = next(x for x in registry[group] if x["id"] == job[key])
    result["weights"] = [x for x in registry.get("weights", []) if x["id"] in job.get("weight_ids", [])]
    return result


def snapshot_code(root: Path, run_dir: Path, paths: list[str]) -> list[dict[str, str]]:
    files: set[Path] = set()
    for rel in paths:
        p = inside(root, rel)
        if not p.exists():
            raise ProjectError(f"implementation does not exist: {rel}")
        if p.is_dir():
            files.update(x for x in p.rglob("*") if x.is_file() and "__pycache__" not in x.parts and ".git" not in x.parts)
        else:
            files.add(p)
    if not files or sum(p.stat().st_size for p in files) > 16 * 1024 * 1024:
        raise ProjectError("code snapshot must be nonempty and <=16MiB; data/weights belong outside code_paths")
    entries = []
    for p in sorted(files):
        rel = p.relative_to(root).as_posix()
        dest = run_dir / "code" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(p.read_bytes())
        entries.append({"path": rel, "sha256": sha(dest), "snapshot": dest.relative_to(run_dir).as_posix()})
    return entries


def env_record() -> dict[str, Any]:
    return {
        "python": sys.version, "executable": sys.executable,
        "platform": platform.platform(), "machine": platform.machine(),
        "packages": sorted({f"{d.metadata.get('Name', '?')}=={d.version}" for d in importlib.metadata.distributions()}),
        "thread_environment": {k: os.environ[k] for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "CUDA_VISIBLE_DEVICES") if k in os.environ},
    }


def run(root: Path | str, job_path: Path | str, foreground: bool = False) -> dict[str, Any]:
    root = Path(root).resolve()
    job_file = inside(root, job_path)
    job = load(job_file)
    validate_job(job)
    task = job["task_id"]
    out = root / "runs" / task
    with lock(root):
        if (out / "manifest.json").exists():
            return {**load(out / "manifest.json"), "duplicate": True, "note": "existing task is never resubmitted; use an explicit new task_id for a bounded retry"}
        if out.exists():
            raise ProjectError(f"incomplete launch directory already exists: {out}; inspect before retry")
        protocol = inside(root, job["contract"])
        binding = verify(root, protocol)
        contract = load(protocol)
        if contract["kind"] != job["kind"] or contract["idea_id"] != job["idea_id"]:
            raise ProjectError("job kind/idea_id mismatches frozen protocol")
        seeds = contract["seeds"] if isinstance(contract["seeds"], list) else contract["seeds"].get("values", contract["seeds"].get("seeds", []))
        if job["seed"] not in seeds:
            raise ProjectError("seed not in frozen protocol")
        try:
            try:
                from gates import check_job
            except ImportError:
                from .gates import check_job
            check_job(root, job)
        except ValueError as exc:
            raise ProjectError(str(exc)) from exc
        reserve = reservation(job)
        retry = check_budget(root, job, reserve)
        check_protocol_budget(root, job, contract, reserve)
        cfg_path = inside(root, job["config"])
        if not cfg_path.is_file():
            raise ProjectError("experiment configuration file missing")
        # Validate parseability; retain exact bytes for reproducibility.
        config = load(cfg_path)
        bind_config(job, config, contract)
        out.mkdir(parents=True)
        try:
            (out / "contract.yaml").write_bytes(protocol.read_bytes())
            (out / "config.json").write_bytes(cfg_path.read_bytes())
            binding_execution = execution_binding(root, job)
            code = snapshot_code(root, out, job["code_paths"])
            cmd = execution_command(root, out, binding_execution, sys.executable)
            record: dict[str, Any] = {
                "schema_version": 1, "task_id": task, "kind": job["kind"], "stage": job["stage"], "idea_id": job["idea_id"],
                "status": "queued", "execution_binding": binding_execution, "job": job, "job_source": job_file.relative_to(root).as_posix(), "command": cmd,
                "contract": {"path": protocol.relative_to(root).as_posix(), "sha256": sha(protocol), "snapshot": "contract.yaml", "frozen_at": binding.get("frozen_at")},
                "config": {"path": cfg_path.relative_to(root).as_posix(), "sha256": sha(cfg_path), "snapshot": "config.json"},
                "code": code, "seed": job["seed"], "dataset_id": job["dataset_id"], "environment_id": job["environment_id"], "resource_id": job["resource_id"],
                "environment": env_record(), "resources": resource_snapshots(root, job), "reservation": reserve, "created_at": now(), "execution_only": True, "scientific_acceptance": "not_assessed", **retry,
            }
            atomic_json(out / "manifest.json", record)
            if not foreground:
                with (out / "worker.log").open("ab", buffering=0) as log:
                    p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--root", str(root), "worker", "--task", task], cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                _reap_children()
                _children[p.pid] = p
                record["worker_pid"] = p.pid
                record["worker_start"] = start_identity(p.pid)
                atomic_json(out / "manifest.json", record)
        except BaseException:
            # Never erase evidence or a launch reservation after a possible spawn.
            if not (out / "manifest.json").exists():
                atomic_json(out / "manifest.json", {"schema_version": 1, "task_id": task, "kind": job["kind"], "job": job, "status": "failed", "reason": "snapshot preparation failed", "reservation": reserve, "created_at": now()})
            raise
    if foreground:
        return worker(root, task)
    return record


def save_record(root: Path, task: str, updates: dict[str, Any]) -> dict[str, Any]:
    with lock(root):
        path = root / "runs" / task / "manifest.json"
        record = load(path)
        record.update(updates)
        atomic_json(path, record)
        return record


def artifact_index(out: Path) -> list[dict[str, Any]]:
    # Snapshots, logs and raw metrics all get durable checksums. The live manifest
    # and this index itself are excluded to avoid circular digests.
    return [{"path": p.relative_to(out).as_posix(), "sha256": sha(p), "bytes": p.stat().st_size} for p in sorted(out.rglob("*")) if p.is_file() and p.name not in {"manifest.json", "artifacts.json", "worker.log"}]


def metric_values(path: Path, required: list[str]) -> dict[str, float]:
    if not path.is_file():
        raise ProjectError("process exited without metrics.json; no values inferred")
    metrics = load(path)
    if not isinstance(metrics, dict):
        raise ProjectError("metrics.json must be an object of finite numeric scalar values")
    for key in required:
        if key not in metrics:
            raise ProjectError(f"missing required metric: {key}")
    for key, value in metrics.items():
        number(value, f"metrics.{key}") if isinstance(value, (int, float)) and value >= 0 else _signed_metric(value, key)
    return metrics


def _signed_metric(value: Any, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ProjectError(f"metric {key} must be a finite numeric scalar")


def terminate_group(p: subprocess.Popen[Any]) -> None:
    if p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait(timeout=3)


def worker(root: Path | str, task: str) -> dict[str, Any]:
    root = Path(root).resolve()
    ident(task)
    out = root / "runs" / task
    p: subprocess.Popen[Any] | None = None
    started = time.monotonic()
    interrupted = False
    claimed = False

    def stop(_signum: int, _frame: Any) -> None:
        nonlocal interrupted
        interrupted = True

    old_handlers = {s: signal.signal(s, stop) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        with lock(root):
            record = load(out / "manifest.json")
            if record["status"] != "queued":
                raise ProjectError("worker refuses duplicate execution of a non-queued task")
            check_snapshots(root, record)
            if execution_binding(root, record["job"]) != record["execution_binding"]:
                raise ProjectError("Execution inputs changed before worker start")
            # Re-validate frozen binding immediately before spawning.
            verify(root, record["contract"]["path"])
            for entry in record["code"]:
                if sha(root / entry["path"]) != entry["sha256"]:
                    raise ProjectError(f"implementation changed before worker start: {entry['path']}")
            claimed = True
            record.update({"status": "running", "started_at": now(), "heartbeat_at": now(), "worker_pid": os.getpid(), "worker_start": start_identity(os.getpid())})
            atomic_json(out / "manifest.json", record)
        job = record["job"]
        env = os.environ.copy()
        env["RESEARCH_RUN_DIR"] = str(out)
        env["RESEARCH_SEED"] = str(job["seed"])
        env["RESEARCH_CONFIG"] = str(out / "config.json")
        env["OMP_NUM_THREADS"] = str(job.get("cpus", 1))
        env["PYTHONPATH"] = str(out / "code") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        with (out / "stdout.log").open("wb", buffering=0) as stdout, (out / "stderr.log").open("wb", buffering=0) as stderr:
            p = subprocess.Popen(record["command"], cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True)
            started = time.monotonic()
            save_record(root, task, {"child_pid": p.pid, "child_start": start_identity(p.pid)})
            last_progress = time.monotonic()
            sizes = (-1, -1, -1)
            status_value = "failed"
            reason = "process exited nonzero"
            while p.poll() is None:
                elapsed = time.monotonic() - started
                current = tuple((out / n).stat().st_mtime_ns if (out / n).exists() else 0 for n in ("stdout.log", "stderr.log", "progress.json"))
                if current != sizes:
                    sizes = current
                    last_progress = time.monotonic()
                save_record(root, task, {"heartbeat_at": now(), "wall_seconds": elapsed, "progress_age_seconds": time.monotonic() - last_progress})
                if interrupted:
                    status_value, reason = "interrupted", "worker received interrupt"
                    terminate_group(p)
                    break
                if elapsed > job["timeout_seconds"]:
                    status_value, reason = "timeout", "hard wall-clock timeout"
                    terminate_group(p)
                    break
                if time.monotonic() - last_progress > job["stall_seconds"]:
                    status_value, reason = "stalled", "no log/progress output within stall_seconds"
                    terminate_group(p)
                    break
                time.sleep(0.2)
            rc = p.wait()
            if status_value == "failed" and time.monotonic() - started > job["timeout_seconds"]:
                status_value, reason = "timeout", "process exceeded hard timeout before observed exit"
        updates: dict[str, Any] = {"status": status_value, "reason": reason, "exit_code": rc}
        if rc == 0 and status_value not in {"interrupted", "timeout", "stalled"}:
            try:
                verify(root, record["contract"]["path"])
                for entry in record["code"]:
                    if sha(root / entry["path"]) != entry["sha256"]:
                        raise ProjectError(f"implementation changed while running: {entry['path']}")
                check_snapshots(root, record)
                if execution_binding(root, record["job"]) != record["execution_binding"]:
                    raise ProjectError("Execution inputs changed while running")
                values = metric_values(out / "metrics.json", job["required_metrics"])
                updates.update({"status": "completed", "reason": "exit 0 and required raw metrics validated; scientific hypothesis not assessed", "metrics": {"path": "metrics.json", "sha256": sha(out / "metrics.json"), "values": values}})
            except (ProjectError, ValueError, OSError, KeyError) as exc:
                updates.update({"status": "failed", "reason": f"invalid evidence: {exc}"})
        elif rc < 0 and status_value == "failed":
            updates.update({"status": "interrupted", "reason": f"child terminated by signal {-rc}"})
        updates.update({"finished_at": now(), "wall_seconds": time.monotonic() - started, "heartbeat_at": now()})
        atomic_json(out / "artifacts.json", {"schema_version": 1, "files": artifact_index(out)})
        return save_record(root, task, updates)
    except BaseException as exc:
        if p is not None:
            terminate_group(p)
        if claimed and (out / "manifest.json").exists():
            atomic_json(out / "artifacts.json", {"schema_version": 1, "files": artifact_index(out)})
            save_record(root, task, {"status": "failed", "reason": f"worker error: {type(exc).__name__}: {exc}", "finished_at": now(), "wall_seconds": time.monotonic() - started})
        raise
    finally:
        for sig, old in old_handlers.items():
            signal.signal(sig, old)


def status(root: Path | str, task: str | None = None) -> dict[str, Any]:
    _reap_children()
    root = Path(root).resolve()
    with lock(root):
        records = [load(root / "runs" / ident(task) / "manifest.json")] if task else manifests(root)
        for record in records:
            if record["status"] in ACTIVE:
                worker = process_observation(record.get("worker_pid"), record.get("worker_start"))
                child = process_observation(record.get("child_pid"), record.get("child_start"))
                record["process_observation"] = {"worker": worker, "child": child}
                record["process_identity_verified"] = worker["identity_verified"]
                record["observed_worker_alive"] = worker["exists"]
                record["observed_child_alive"] = child["exists"]
                # A queued worker may not have registered yet. In particular,
                # lack of /proc must never convert a live queue entry into a
                # non-queued entry that its worker would then refuse to run.
                if record.get("worker_pid") and worker["exists"] is False and child["exists"] is False:
                    record["status"] = "unconfirmed"
                    record["reason"] = "worker and child are definitely absent; exit/result evidence is unconfirmed; inspect before explicit retry"
                elif not worker["identity_verified"]:
                    record["observation_warning"] = worker.get("warning", "worker identity is unavailable; existing task is not resubmitted")
                elif worker["exists"] is False:
                    record["observation_warning"] = "worker is absent but child remains alive/unknown; no resubmission or process termination"
                atomic_json(root / "runs" / record["task_id"] / "manifest.json", record)
        return {"schema_version": 1, "runs": records, "reserved": {k: sum(r["reservation"][k] for r in manifests(root)) for k in ("cpu_seconds", "gpu_hours", "cost_usd")}}


def resume(root: Path | str) -> dict[str, Any]:
    report = status(root)
    report["resubmitted"] = 0
    report["next_action"] = "read current native research_contract and frozen protocol; reconcile unconfirmed workers; explicit new retry task only after confirmed termination"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    sub = parser.add_subparsers(dest="action", required=True)
    r = sub.add_parser("run")
    r.add_argument("--job", required=True)
    r.add_argument("--foreground", action="store_true")
    s = sub.add_parser("status")
    s.add_argument("--task")
    sub.add_parser("resume")
    w = sub.add_parser("worker")
    w.add_argument("--task", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "run":
            result = run(args.root, args.job, args.foreground)
        elif args.action == "worker":
            result = worker(args.root, args.task)
        elif args.action == "status":
            result = status(args.root, args.task)
        else:
            result = resume(args.root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") not in {"failed", "timeout", "stalled", "interrupted"} else 1
    except (ProjectError, ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
