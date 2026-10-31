#!/usr/bin/env python3
"""Validate and freeze experiment protocols without changing their bytes.

Protocol files use JSON syntax, a strict subset of YAML 1.2. No parser or
commercial service is required. The registry detects accidental modification;
it is a cooperative research audit trail, not a defense against local tampering.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterator


class ProjectError(RuntimeError):
    """A missing prerequisite or an invalid research artifact."""


def load(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProjectError(f"Cannot read JSON-compatible YAML/JSON: {path}: {exc}") from exc


def atomic_json(path: str | Path, obj: Any) -> None:
    """Write a complete JSON document atomically in the destination directory."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{dest.name}.", dir=dest.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(obj, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, dest)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def sha(path: str | Path) -> str:
    try:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError as exc:
        raise ProjectError(f"Cannot fingerprint {path}: {exc}") from exc


def project_path(root: str | Path, path: str | Path) -> Path:
    base = Path(root).resolve()
    candidate = Path(path)
    resolved = (candidate if candidate.is_absolute() else base / candidate).resolve()
    if not resolved.is_relative_to(base):
        raise ProjectError(f"Path must stay inside project: {path}")
    return resolved


def _relative(root: Path, path: str | Path) -> str:
    return project_path(root, path).relative_to(root.resolve()).as_posix()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _version(value: Any) -> int:
    if isinstance(value, bool):
        raise ProjectError("version must be a positive integer or vN")
    match = re.fullmatch(r"v?([1-9][0-9]*)", str(value))
    if not match:
        raise ProjectError("version must be a positive integer or vN")
    return int(match.group(1))


def _meaningful(value: Any) -> bool:
    if value is None or value == "" or value == [] or value == {}:
        return False
    if isinstance(value, str):
        if value.strip().lower() in {"todo", "tbd", "unknown", "pending", "待填写", "待配置", "待确定", "null"}:
            return False
        if value.strip().startswith(("<", "TODO", "TBD")):
            return False
    return True


def _require(obj: dict[str, Any], key: str, prefix: str = "") -> Any:
    if key not in obj or not _meaningful(obj[key]):
        raise ProjectError(f"Protocol field is required and cannot be a placeholder: {prefix}{key}")
    return obj[key]


def _read_registry(root: Path) -> dict[str, Any]:
    path = root / "contracts/.registry.json"
    if not path.exists():
        return {"schema_version": 1, "contracts": {}}
    registry = load(path)
    if not isinstance(registry, dict) or registry.get("schema_version") != 1 or not isinstance(registry.get("contracts"), dict):
        raise ProjectError("Invalid contracts/.registry.json")
    return registry


@contextmanager
def _registry_lock(root: Path) -> Iterator[None]:
    directory = root / "contracts"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".registry.lock").open("a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _known_runs(root: Path, idea_id: str) -> set[str]:
    """Conservatively treat existing result files as already observed evidence."""
    runs: set[str] = set()
    for path in sorted((root / "runs").glob("*/manifest.json")):
        manifest = load(path)
        if manifest.get("idea_id") != idea_id:
            # Some runtime versions retain the job as an object in the manifest.
            if manifest.get("job", {}).get("idea_id") != idea_id:
                continue
        # Failure, interruption, and a partial log are evidence too. A protocol
        # cannot become "preregistered" merely because a failed attempt did not
        # emit a final metrics file. A never-started queued attempt is excluded.
        terminal_or_observed = {
            "completed", "failed", "timeout", "stalled", "interrupted",
            "unconfirmed", "lost", "running",
        }
        logs_observed = any(
            candidate.is_file() and candidate.stat().st_size > 0
            for candidate in (path.parent / "stdout.log", path.parent / "stderr.log")
        )
        if (
            (path.parent / "metrics.json").exists()
            or manifest.get("started_at")
            or manifest.get("status") in terminal_or_observed
            or logs_observed
        ):
            runs.add(path.parent.name)
    return runs


def _run_ids(root: Path, values: Any, field: str) -> set[str]:
    if not isinstance(values, list) or any(not isinstance(x, str) for x in values):
        raise ProjectError(f"{field} must be a list of actual run IDs")
    if len(set(values)) != len(values):
        raise ProjectError(f"{field} contains duplicate run IDs")
    for run_id in values:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id):
            raise ProjectError(f"Invalid run ID in {field}: {run_id}")
        if not (root / "runs" / run_id / "manifest.json").is_file():
            raise ProjectError(f"Unknown run in {field}: {run_id}")
    return set(values)


def validate(root: str | Path, path: str | Path) -> dict[str, Any]:
    """Return a validated protocol. This does not mean the hypothesis is true."""
    base = Path(root).resolve()
    protocol_path = project_path(base, path)
    protocol = load(protocol_path)
    if not isinstance(protocol, dict):
        raise ProjectError("Protocol must be a mapping")
    for key in ("idea_id", "version", "kind", "question", "hypothesis", "method", "metrics", "data", "baseline", "hyperparameters", "seeds", "success_signals", "failure_signals", "inconclusive_signals", "ablations", "budget", "stopping", "provenance"):
        _require(protocol, key)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", str(protocol["idea_id"])):
        raise ProjectError("idea_id must be a safe nonempty identifier")
    version = _version(protocol["version"])
    expected = Path("contracts") / protocol["idea_id"] / f"v{version}.yaml"
    if protocol_path.relative_to(base) != expected:
        raise ProjectError(f"Protocol must live at {expected.as_posix()}")
    if protocol["kind"] not in {"toy", "real", "mock"}:
        raise ProjectError("kind must be toy, mock, or real")
    if protocol["kind"] == "real":
        statistics = _require(protocol, "statistics")
        if not isinstance(statistics, dict):
            raise ProjectError("statistics must define the prespecified comparison")
        for key in ("metric", "aggregation", "statistical_rule", "hardware_scope"):
            _require(statistics, key, "statistics.")
        for key in ("atol", "rtol"):
            value = statistics.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ProjectError(f"statistics.{key} must be a finite nonnegative tolerance")
    method = protocol["method"]
    if not isinstance(method, dict):
        raise ProjectError("method must be a mapping")
    _require(method, "description", "method.")
    implementation = _require(method, "implementation", "method.")
    if not isinstance(implementation, list):
        raise ProjectError("method.implementation must be a list of file paths or {path, symbol} mappings")
    for entry in implementation:
        source = entry.get("path") if isinstance(entry, dict) else entry
        if not isinstance(source, str) or not _meaningful(source):
            raise ProjectError(f"Invalid method implementation location: {source}")
        # Locations are planned before implementation. The launch gate checks
        # actual files and the runtime snapshots them before starting a job.
        project_path(base, source)
    metrics = protocol["metrics"]
    if not isinstance(metrics, dict):
        raise ProjectError("metrics must contain primary and secondary")
    _require(metrics, "primary", "metrics.")
    if "secondary" not in metrics or not isinstance(metrics["secondary"], (list, dict, str)):
        raise ProjectError("metrics.secondary is required; [] is allowed")
    data = protocol["data"]
    if not isinstance(data, dict):
        raise ProjectError("data must be a mapping containing dataset identity and split")
    _require(data, "split", "data.")
    if len(data) < 2:
        raise ProjectError("data must identify a dataset in addition to split")
    seeds = protocol["seeds"]
    # A seed scheme is explicit even if not every seed is yet enumerated.
    if isinstance(seeds, dict):
        seeds = seeds.get("values", seeds.get("seeds"))
    if not isinstance(seeds, list) or not seeds or any(isinstance(x, bool) or not isinstance(x, int) for x in seeds):
        raise ProjectError("seeds must enumerate at least one integer (or use {values: [...]})")
    if len(set(seeds)) != len(seeds):
        raise ProjectError("seeds must be unique")
    if protocol["failure_signals"] == protocol["success_signals"]:
        raise ProjectError("failure_signals must be independently defined, not copied success signals")
    for key in ("success_signals", "failure_signals", "inconclusive_signals", "ablations"):
        if not isinstance(protocol[key], (list, dict)):
            raise ProjectError(f"{key} must be a list or mapping with explicit criteria")
    if not isinstance(protocol["budget"], dict) or not isinstance(protocol["stopping"], (dict, list)):
        raise ProjectError("budget must be a mapping; stopping must be a mapping or list")
    provenance = protocol["provenance"]
    if not isinstance(provenance, dict) or provenance.get("mode") not in {"preregistered", "exploratory"}:
        raise ProjectError("provenance.mode must be preregistered or exploratory")
    observed = _run_ids(base, provenance.get("observed_runs"), "provenance.observed_runs")
    # New protocols must distinguish results used to form the hypothesis from
    # background observations or an independently specified confirmation study.
    # This dependency crosses idea boundaries; changing idea_id cannot erase it.
    basis = _run_ids(base, provenance.get("hypothesis_basis_runs"), "provenance.hypothesis_basis_runs")
    if not basis.issubset(observed):
        raise ProjectError("hypothesis_basis_runs must also be disclosed in observed_runs")
    if basis and provenance["mode"] != "exploratory":
        raise ProjectError("A hypothesis derived from observed results must be marked exploratory")
    known = _known_runs(base, protocol["idea_id"])
    if not known.issubset(observed):
        raise ProjectError(f"Existing evidence must be disclosed in observed_runs: {sorted(known - observed)}")
    if known and provenance["mode"] != "exploratory":
        raise ProjectError("A protocol written after results for this idea must be marked exploratory")
    if version > 1:
        amendment = protocol.get("amendment")
        if not isinstance(amendment, dict):
            raise ProjectError("A new protocol version requires amendment metadata")
        for key in ("previous", "reason", "created_at", "impact"):
            _require(amendment, key, "amendment.")
        expected_previous = f"contracts/{protocol['idea_id']}/v{version - 1}.yaml"
        if _relative(base, amendment["previous"]) != expected_previous:
            raise ProjectError(f"amendment.previous must refer to {expected_previous}")
        previous_record = verify(base, amendment["previous"])
        seen = _run_ids(base, amendment.get("seen_results"), "amendment.seen_results")
        if seen != observed:
            raise ProjectError("amendment.seen_results must match provenance.observed_runs")
        try:
            created = datetime.fromisoformat(amendment["created_at"].replace("Z", "+00:00"))
            previous_time = datetime.fromisoformat(previous_record["frozen_at"].replace("Z", "+00:00"))
            if created.tzinfo is None or created > datetime.now(timezone.utc) or created < previous_time:
                raise ValueError("time must have timezone, follow previous freeze, and not be in the future")
        except (ValueError, TypeError) as exc:
            raise ProjectError(f"Invalid amendment.created_at: {exc}") from exc
    from results import validate_signals
    validate_signals(protocol)
    # Compare every earlier frozen version to prevent reusing a retired ID.
    for old_path, record in _read_registry(base)["contracts"].items():
        if record.get("idea_id") == protocol["idea_id"] and _version(record["version"]) < version:
            verify(base, old_path)
            validate_signals(protocol, load(base / old_path))
    return protocol


def verify(root: str | Path, path: str | Path | None = None) -> dict[str, Any]:
    """Verify byte identity against the registry; never reclassify old runs."""
    base = Path(root).resolve()
    registry = _read_registry(base)
    records = registry["contracts"]
    selected = [_relative(base, path)] if path is not None else sorted(records)
    for relative in selected:
        record = records.get(relative)
        if record is None:
            raise ProjectError(f"Protocol is not frozen: {relative}")
        if sha(project_path(base, relative)) != record.get("sha256"):
            raise ProjectError(f"Frozen protocol was modified: {relative}; restore original bytes or create a new version")
    if path is not None:
        return {**records[selected[0]], "path": selected[0]}
    return {"all_verified": True, "count": len(selected), "paths": selected}


def freeze(root: str | Path, path: str | Path) -> dict[str, Any]:
    """Register original protocol bytes exactly once. Repeating is idempotent."""
    base = Path(root).resolve()
    relative = _relative(base, path)
    with _registry_lock(base):
        registry = _read_registry(base)
        if relative in registry["contracts"]:
            return verify(base, relative)
        protocol = validate(base, relative)
        # Enforce contiguous versions and one canonical path per idea/version.
        version = _version(protocol["version"])
        for record in registry["contracts"].values():
            if record.get("idea_id") == protocol["idea_id"] and _version(record.get("version")) >= version:
                raise ProjectError("Protocol versions must increase; an existing version cannot be replaced")
        record = {"sha256": sha(project_path(base, relative)), "frozen_at": _now(), "idea_id": protocol["idea_id"], "version": version, "kind": protocol["kind"]}
        registry["contracts"][relative] = record
        atomic_json(base / "contracts/.registry.json", registry)
        return {**record, "path": relative}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("validate", "freeze", "verify"):
        child = sub.add_parser(name)
        child.add_argument("--contract", required=name != "verify")
    args = parser.parse_args(argv)
    try:
        result = {"validate": validate, "freeze": freeze, "verify": verify}[args.action](Path(args.root), args.contract)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ProjectError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
