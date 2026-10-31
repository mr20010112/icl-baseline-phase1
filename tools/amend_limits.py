#!/usr/bin/env python3
"""Offline, disclosed limit successors; never edits frozen protocol bytes.

plan is read-only. apply preflights the entire chain in a temporary directory,
then uses contracts.freeze unchanged. Original jobs/configs are retained;
review the new jobs under experiments/limit-deviations/<batch>/jobs/*.json.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile

import contracts
from contracts import ProjectError, project_path

AUTHORIZATION = "docs/operator-limit-authorization.md"
KIND = "operator-limit-deviation"
POST_HOC = "post-hoc, exploratory; results are not preregistered"
BASES = {1: (2,), 2: (3, 4, 5, 6)}
ALLOWED = {("version",), ("amendment",), ("stopping", "timeout_seconds"),
           ("stopping", "stall_seconds"), ("budget", "max_cpu_seconds"),
           ("budget", "max_gpu_hours"), ("budget", "max_cost_usd"),
           ("provenance", "mode"), ("provenance", "observed_runs")}


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def _sha(contents):
    return hashlib.sha256(contents).hexdigest()


def spans(contents):
    """Locate JSON value tokens, retaining original spelling/formatting bytes."""
    text = contents.decode("utf-8")
    decoder = json.JSONDecoder()
    found = {}

    def whitespace(pos):
        while pos < len(text) and text[pos].isspace():
            pos += 1
        return pos

    def value(pos, path):
        pos = whitespace(pos)
        start = pos
        if text[pos] == "{":
            pos = whitespace(pos + 1)
            keys = set()
            while text[pos] != "}":
                key, end = decoder.raw_decode(text, pos)
                if not isinstance(key, str) or key in keys:
                    raise ProjectError("Protocol JSON has invalid/duplicate object keys")
                keys.add(key)
                pos = whitespace(end)
                if text[pos] != ":":
                    raise ProjectError("Invalid protocol JSON")
                pos = whitespace(value(pos + 1, path + (key,)))
                if text[pos] == ",":
                    pos = whitespace(pos + 1)
                elif text[pos] != "}":
                    raise ProjectError("Invalid protocol JSON")
            end = pos + 1
        else:
            _, end = decoder.raw_decode(text, pos)
        found[path] = (start, end)
        return end

    end = value(0, ())
    if text[end:].strip():
        raise ProjectError("Unexpected trailing protocol JSON")
    return text, found


def patch(contents, changes):
    text, locations = spans(contents)
    edits = []
    for path, value in changes.items():
        if path not in locations:
            raise ProjectError("Missing protocol field: " + ".".join(path))
        start, end = locations[path]
        edits.append((start, end, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)))
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text.encode("utf-8")


def assert_only_changes(original, successor):
    """Byte-compare every subtree except the explicit metadata/limit allowlist."""
    left, a = spans(original)
    right, b = spans(successor)

    def check(path):
        if path in ALLOWED:
            return
        if not any(allowed[:len(path)] == path for allowed in ALLOWED):
            if left[slice(*a[path])] != right[slice(*b[path])]:
                raise ProjectError("Non-limit scientific field differs in bytes: " + ".".join(path))
            return
        ak = {p for p in a if len(p) == len(path) + 1 and p[:-1] == path}
        bk = {p for p in b if len(p) == len(path) + 1 and p[:-1] == path}
        if ak != bk:
            raise ProjectError("Protocol field inventory differs: " + ".".join(path))
        for child in ak:
            check(child)
    check(())


def _base(version):
    return f"contracts/baseline/v{version}.yaml"


def validate_deviation(root, ref):
    """Verify an approved successor, its scientific parent and arithmetic."""
    root = Path(root).resolve()
    record = contracts.verify(root, ref)
    target = project_path(root, ref).read_bytes()
    protocol = json.loads(target)
    amendment = protocol.get("amendment", {})
    if amendment.get("kind") != KIND:
        raise ProjectError("Not an operator-limit-deviation: " + ref)
    source = amendment["original"]["path"]
    parent = contracts.verify(root, source)
    if (parent["sha256"] != amendment["original"]["sha256"] or parent["version"] != amendment["original"]["version"]
            or parent["version"] >= record["version"]):
        raise ProjectError("Limit amendment original version/hash differs")
    original = project_path(root, source).read_bytes()
    old = json.loads(original)
    assert_only_changes(original, target)
    origin = amendment["origin"]
    if source != origin:
        if old.get("amendment", {}).get("kind") != KIND or validate_deviation(root, source) != origin:
            raise ProjectError("Limit amendment scientific lineage differs")
    if origin not in {_base(v) for v in (2, 3, 4, 5, 6)}:
        raise ProjectError("Unknown limit amendment origin")
    if amendment["previous"] != _base(record["version"] - 1):
        raise ProjectError("Limit amendment is outside the linear chain")
    contracts.verify(root, amendment["previous"])
    arithmetic = amendment["arithmetic"]
    if arithmetic["attempts"] != old["budget"]["max_attempts"]:
        raise ProjectError("Limit amendment changes the attempt allowance")
    timeout, stall = (protocol["stopping"][key] for key in ("timeout_seconds", "stall_seconds"))
    if any(type(value) is not int or value <= 0 for value in (timeout, stall)) or stall > timeout:
        raise ProjectError("Invalid amended timeout/stall")
    expected = {"max_cpu_seconds": arithmetic["attempts"] * timeout * arithmetic["cpus"],
                "max_gpu_hours": arithmetic["attempts"] * timeout * arithmetic["gpus"] / 3600,
                "max_cost_usd": arithmetic["attempts"] * timeout * arithmetic["cost_per_hour"] / 3600}
    if any(protocol["budget"][key] != value for key, value in expected.items()):
        raise ProjectError("Limit amendment budget arithmetic differs")
    values = {"stopping." + key: old["stopping"][key] for key in ("timeout_seconds", "stall_seconds")}
    values.update({"budget." + key: old["budget"][key] for key in expected})
    new = {key: protocol[key.split(".")[0]][key.split(".")[1]] for key in values}
    if amendment["old_values"] != values or amendment["new_values"] != new:
        raise ProjectError("Limit amendment old/new disclosure differs")
    if not amendment.get("allow_lower") and any(new[key] < value for key, value in values.items()):
        raise ProjectError("Lower limit requires --allow-lower")
    provenance = protocol["provenance"]
    if amendment.get("provenance_before") != old["provenance"] or amendment.get("provenance_after") != provenance:
        raise ProjectError("Limit amendment provenance disclosure differs")
    if amendment.get("post_hoc"):
        if (not provenance["observed_runs"] or provenance["mode"] != "exploratory" or amendment.get("classification") != POST_HOC
                or not set(old["provenance"]["observed_runs"]).issubset(provenance["observed_runs"])):
            raise ProjectError("Post-hoc amendment must disclose exploratory provenance")
    elif provenance != old["provenance"]:
        raise ProjectError("Pre-run amendment changes provenance")
    if amendment.get("seen_results") != provenance["observed_runs"]:
        raise ProjectError("Limit amendment seen_results/provenance differ")
    auth = amendment["owner_authorization"]
    if contracts.sha(project_path(root, auth["path"])) != auth["sha256"]:
        raise ProjectError("Owner authorization text changed")
    evaluation = amendment.get("evaluation_params")
    if evaluation and contracts.sha(project_path(root, evaluation["path"])) != evaluation["sha256"]:
        raise ProjectError("Scientific evaluation-params hash changed")
    return origin


def export_protocols(root, phase):
    """Base phase inventory plus verified successors and their linear ancestors."""
    root = Path(root).resolve()
    selected = {_base(v) for v in range(1, 3 if phase == 1 else 7)}
    registry = contracts.load(root / "contracts/.registry.json")["contracts"]
    origins = {_base(v) for v in ((2,) if phase == 1 else (2, 3, 4, 5, 6))}
    for ref in registry:
        if not ref.startswith("contracts/baseline/") or ref in selected:
            continue
        if phase == 1 and not project_path(root, ref).is_file():
            continue  # Unselected phase-2 registrations are not phase-1 payload.
        protocol = contracts.load(project_path(root, ref))
        if protocol.get("amendment", {}).get("kind") == KIND:
            origin = validate_deviation(root, ref)
            if origin in origins:
                selected.add(ref)
                for version in range(1, protocol["version"]):
                    ancestor = _base(version)
                    if phase == 1 and version > 2:
                        prior = contracts.load(project_path(root, ancestor))
                        if prior.get("amendment", {}).get("kind") != KIND or validate_deviation(root, ancestor) != _base(2):
                            raise ProjectError("Phase-1 export would require phase-2 chain ancestors; export from the phase-1 package")
                    selected.add(ancestor)
    return tuple(sorted(selected, key=lambda ref: int(Path(ref).stem[1:])))


def make_plan(root, phase, timeout_seconds, *, stall_seconds=None, reason, authorization_ref=AUTHORIZATION, allow_lower=False):
    root = Path(root).resolve()
    if phase not in BASES or type(timeout_seconds) is not int or timeout_seconds <= 0:
        raise ProjectError("Use --phase 1|2 and a positive integer timeout")
    if not reason or not reason.strip():
        raise ProjectError("A nonempty deviation reason is required")
    if stall_seconds is not None and (type(stall_seconds) is not int or stall_seconds <= 0):
        raise ProjectError("stall-seconds must be a positive integer")
    contracts.verify(root)
    auth_path = project_path(root, authorization_ref)
    if not auth_path.read_text(encoding="utf-8").strip():
        raise ProjectError("Owner authorization text is empty")
    authorization_ref = auth_path.relative_to(root).as_posix()
    registry = contracts.load(root / "contracts/.registry.json")["contracts"]
    latest = max(row["version"] for row in registry.values() if row["idea_id"] == "baseline")
    sources = {_base(v): _base(v) for v in BASES[phase]}
    for ref, record in sorted(registry.items(), key=lambda item: item[1]["version"]):
        if record["idea_id"] != "baseline":
            continue
        candidate = contracts.load(root / ref)
        if candidate.get("amendment", {}).get("kind") == KIND:
            origin = validate_deviation(root, ref)
            if origin in sources:
                sources[origin] = ref
    batch = f"phase{phase}-v{latest+1}-v{latest+len(sources)}"
    folder = f"experiments/limit-deviations/{batch}"
    observed = sorted(contracts._known_runs(root, "baseline"))
    files, proposals, inputs = {}, [], {}

    def input_file(ref):
        path = project_path(root, ref)
        data = path.read_bytes()
        inputs[path.relative_to(root).as_posix()] = _sha(data)
        return data

    input_file("contracts/.registry.json")
    input_file(authorization_ref)
    for ref in registry:
        input_file(ref)
    canonical = ([f"experiments/baseline-seed{seed}.json" for seed in (42, 43, 44)] if phase == 1 else
                 [p.relative_to(root).as_posix() for p in sorted((root / "experiments/phase2").glob("*.json")) if p.name != "job-params.json"])
    canonical_jobs = {ref: json.loads(input_file(ref)) for ref in canonical}
    expected_counts = {2: 3, 3: 36, 4: 9, 5: 9, 6: 6}
    for index, (origin, source) in enumerate(sources.items(), latest + 1):
        contents = input_file(source)
        original = json.loads(contents)
        source_jobs = {ref: ref for ref, job in canonical_jobs.items() if job["contract"] == origin}
        if len(source_jobs) != expected_counts[int(Path(origin).stem[1:])]:
            raise ProjectError("Original protocol/job inventory differs: " + origin)
        if source != origin:
            inherited = original["amendment"]["jobs"]
            if set(inherited) != set(source_jobs):
                raise ProjectError("Successor job inventory differs")
            source_jobs = inherited
        jobs = {ref: json.loads(input_file(path)) for ref, path in source_jobs.items()}
        if any(job[field] != original["stopping"][field] for job in jobs.values() for field in ("timeout_seconds", "stall_seconds")):
            raise ProjectError("Source job limits differ from their bound frozen protocol")
        dimensions = {(job["cpus"], job["gpus"], job.get("cost_per_hour", 0)) for job in jobs.values()}
        if len(dimensions) != 1 or any(job["contract"] != source for job in jobs.values()):
            raise ProjectError("Jobs do not share one bound protocol/resource reservation")
        cpus, gpus, cost = dimensions.pop()
        if any((job["cpus"], job["gpus"]) != (canonical_jobs[ref]["cpus"], canonical_jobs[ref]["gpus"]) for ref, job in jobs.items()):
            raise ProjectError("CPU/GPU assignment changed outside the sanctioned limit route")
        stall = original["stopping"]["stall_seconds"] if stall_seconds is None else stall_seconds
        if stall > timeout_seconds:
            raise ProjectError("stall-seconds exceeds timeout-seconds")
        attempts = original["budget"]["max_attempts"]
        changes = {("version",): index, ("stopping", "timeout_seconds"): timeout_seconds, ("stopping", "stall_seconds"): stall,
                   ("budget", "max_cpu_seconds"): attempts * timeout_seconds * cpus,
                   ("budget", "max_gpu_hours"): attempts * timeout_seconds * gpus / 3600,
                   ("budget", "max_cost_usd"): attempts * timeout_seconds * cost / 3600}
        old_values = {".".join(path): original[path[0]][path[1]] for path in changes if len(path) == 2}
        new_values = {".".join(path): value for path, value in changes.items() if len(path) == 2}
        if not allow_lower and any(new_values[key] < value for key, value in old_values.items()):
            raise ProjectError("Refusing to lower a limit/budget below its original; use --allow-lower")
        if new_values == old_values:
            raise ProjectError("No limit change requested")
        job_map, job_changes = {}, []
        for original_ref, job in jobs.items():
            job_ref = f"{folder}/jobs/{Path(original_ref).name}"
            config_ref = f"{folder}/configs/{Path(original_ref).name}"
            config_bytes = input_file(job["config"])
            config = json.loads(config_bytes)
            from runtime import bind_config, validate_job
            validate_job(job)
            bind_config(job, config, original)
            amended_job = copy.deepcopy(job)
            amended_job.update(task_id=f"{job['task_id']}-limits-v{index}", contract=_base(index), config=config_ref,
                               timeout_seconds=timeout_seconds, stall_seconds=stall, code_review_receipt=None,
                               estimated={"cpu_seconds": timeout_seconds * cpus, "gpu_hours": timeout_seconds * gpus / 3600,
                                          "cost_usd": timeout_seconds * cost / 3600})
            amended_job["command"] = [job_ref if value == source_jobs[original_ref] else value for value in job["command"]]
            if "contract" in config:
                config_bytes = patch(config_bytes, {("contract",): _base(index)})
            files[job_ref] = encode(amended_job).decode()
            files[config_ref] = config_bytes.decode()
            job_map[original_ref] = job_ref
            job_changes.append({"source": source_jobs[original_ref], "job": job_ref,
                                "config_source": job["config"], "config": config_ref,
                                "values": {key: {"old": job.get(key), "new": value}
                                           for key, value in amended_job.items() if value != job.get(key)},
                                "config_contract": {"old": config.get("contract"), "new": _base(index)} if "contract" in config else None})
        provenance = copy.deepcopy(original["provenance"])
        if observed:
            provenance.update(mode="exploratory", observed_runs=sorted(set(provenance["observed_runs"]) | set(observed)))
            changes[("provenance", "mode")] = provenance["mode"]
            changes[("provenance", "observed_runs")] = provenance["observed_runs"]
        evaluation = original["hyperparameters"].get("evaluation", {})
        evaluation_record = None
        if evaluation.get("evaluation_params_file"):
            ref = evaluation["evaluation_params_file"]
            sha = _sha(input_file(ref))
            if sha != evaluation["evaluation_params_sha256"]:
                raise ProjectError("Scientific evaluation-params hash changed")
            evaluation_record = {"path": ref, "sha256": sha}
        amendment = {"kind": KIND, "previous": _base(index-1), "original": {"path": source, "version": original["version"], "sha256": _sha(contents)},
                     "origin": origin, "old_values": old_values, "new_values": new_values,
                     "reason": reason, "created_at": now(), "owner_authorization": {"path": authorization_ref, "sha256": inputs[authorization_ref]},
                     "impact": "Disclosed operator limit deviation; fresh batch code review required. Original runs/protocols are retained; no extra attempts or retry allowance.",
                     "seen_results": provenance["observed_runs"], "post_hoc": bool(observed),
                     "classification": POST_HOC if observed else "pre-run limit-only; scientific preregistration unchanged",
                     "provenance_before": original["provenance"], "provenance_after": provenance,
                     "arithmetic": {"attempts": attempts, "cpus": cpus, "gpus": gpus, "cost_per_hour": cost},
                     "allow_lower": allow_lower, "evaluation_params": evaluation_record, "jobs": job_map}
        changes[("amendment",)] = amendment
        successor = patch(contents, changes)
        assert_only_changes(contents, successor)
        files[_base(index)] = successor.decode()
        proposals.append({"origin": origin, "source": source, "successor": _base(index), "old_values": old_values, "new_values": new_values,
                          "classification": amendment["classification"], "provenance_before": original["provenance"], "provenance_after": provenance,
                          "jobs": job_map, "job_changes": job_changes, "amendment_before": original.get("amendment")})
    return {"schema_version": 1, "phase": phase, "batch": batch, "created_at": now(), "reason": reason,
            "classification": POST_HOC if observed else "pre-run limit-only; provenance unchanged", "observed_runs": observed,
            "owner_authorization": {"path": authorization_ref, "sha256": inputs[authorization_ref]},
            "protocols": proposals, "inputs": inputs, "files": files,
            "notice": "Original attempt/retry limits remain binding across the deviation. Do not restart completed jobs or create extra attempts. Global budget/resource authorization remains required."}


def summary(plan):
    return {key: value for key, value in plan.items() if key != "files"}


def _check_inputs(root, plan):
    for ref, sha in plan["inputs"].items():
        if contracts.sha(project_path(root, ref)) != sha:
            raise ProjectError("Input changed while planning: " + ref)
    if sorted(contracts._known_runs(root, "baseline")) != plan["observed_runs"]:
        raise ProjectError("Observed-run ledger changed while planning; prepare a fresh plan")
    for ref in plan["files"]:
        if project_path(root, ref).exists():
            raise ProjectError("Refusing to overwrite a successor/job/config: " + ref)


def apply_limits(root, phase, timeout_seconds, **options):
    root = Path(root).resolve()
    plan = make_plan(root, phase, timeout_seconds, **options)
    _check_inputs(root, plan)
    # Exercise unchanged contract rules for the WHOLE chain before real writes.
    with tempfile.TemporaryDirectory(prefix="limit-freeze-preflight-") as temp:
        stage = Path(temp)
        for ref in plan["inputs"]:
            if ref.startswith("contracts/"):
                path = stage / ref
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(project_path(root, ref).read_bytes())
        if (root / "runs").exists():
            (stage / "runs").symlink_to(root / "runs", target_is_directory=True)
        for row in plan["protocols"]:
            ref = row["successor"]
            contents = patch(plan["files"][ref].encode(), {("amendment", "created_at"): now()})
            path = stage / ref
            path.write_bytes(contents)
            contracts.freeze(stage, ref)
    _check_inputs(root, plan)
    for row in plan["protocols"]:
        ref = row["successor"]
        contents = patch(plan["files"][ref].encode(), {("amendment", "created_at"): now()})
        with project_path(root, ref).open("xb") as stream:
            stream.write(contents)
        row["registration"] = contracts.freeze(root, ref)
        validate_deviation(root, ref)
        plan["files"][ref] = contents.decode()
    for ref, text in plan["files"].items():
        if ref.startswith("contracts/"):
            continue
        path = project_path(root, ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(text.encode())
    result = summary(plan)
    result["status"] = "applied; fresh batch review required"
    result["output_sha256"] = {ref: _sha(text.encode()) for ref, text in plan["files"].items()}
    manifest = root / f"experiments/limit-deviations/{plan['batch']}/manifest.json"
    manifest.write_bytes(encode(result))
    lines = [f"\n## {plan['batch']} ({now()})\n", plan["classification"], "\nReason: " + plan["reason"],
             "\nOwner authorization: " + json.dumps(plan["owner_authorization"]), "\n" + plan["notice"],
             "\nOriginal numeric budget/stopping prose remains historical; the successor's structured limits and this disclosure record the effective deviation."]
    for row in plan["protocols"]:
        lines += [f"\n### {row['source']} -> {row['successor']}\n", "| Field | Before | After |", "|---|---|---|"]
        lines.append(f"| version | {Path(row['source']).stem[1:]} | {Path(row['successor']).stem[1:]} |")
        for key, value in row["old_values"].items():
            lines.append(f"| {key} | {value} | {row['new_values'][key]} |")
        lines += ["\nProvenance before: `" + json.dumps(row["provenance_before"], ensure_ascii=False) + "`",
                  "\nProvenance after: `" + json.dumps(row["provenance_after"], ensure_ascii=False) + "`",
                  "\nBinding changes: new version/amendment, contract/config paths and hashes; new unique task IDs and (phase 2) --job paths; updated reservation estimates; code_review_receipt cleared. Other job/config fields are retained."]
        lines += ["\nEvery job/config value changed (paths are source-relative):\n```json",
                  json.dumps(row["job_changes"], ensure_ascii=False, indent=2), "```",
                  "\nComplete successor amendment metadata (including timestamp and original hash):\n```json",
                  json.dumps(contracts.load(root / row["successor"])["amendment"], ensure_ascii=False, indent=2), "```"]
        lines += ["\nPrevious amendment metadata:\n```json", json.dumps(row["amendment_before"], ensure_ascii=False, indent=2), "```"]
    lines += ["\nMachine-readable manifest: `" + manifest.relative_to(root).as_posix() + "`",
              "\nEvery output file SHA256:\n```json", json.dumps(result["output_sha256"], indent=2), "```"]
    report = root / "reports/third-party/limit-deviation.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    with (root / "OPERATOR_LOG.md").open("a", encoding="utf-8") as stream:
        stream.write(f"\n## Disclosed limit deviation: {plan['batch']}\n{plan['classification']}\nReason: {plan['reason']}\nSee reports/third-party/limit-deviation.md and {manifest.relative_to(root)}. Fresh batch review is required before launch. This tool entry must be checked and included in the final return.\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "apply"):
        child = sub.add_parser(command)
        child.add_argument("--phase", type=int, choices=(1, 2), required=True)
        child.add_argument("--timeout-seconds", type=int, required=True)
        child.add_argument("--stall-seconds", type=int)
        child.add_argument("--reason", required=True)
        child.add_argument("--authorization-ref", default=AUTHORIZATION)
        child.add_argument("--allow-lower", action="store_true")
    args = parser.parse_args(argv)
    try:
        options = {"stall_seconds": args.stall_seconds, "reason": args.reason,
                   "authorization_ref": args.authorization_ref, "allow_lower": args.allow_lower}
        value = (summary(make_plan(args.root, args.phase, args.timeout_seconds, **options)) if args.command == "plan" else
                 apply_limits(args.root, args.phase, args.timeout_seconds, **options))
        print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ProjectError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
