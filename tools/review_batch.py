#!/usr/bin/env python3
"""Prepare one code-review session with separate, hash-bound job attestations.

No reviewer is called and no job is launched. RESULTS.json is an object mapping
each index package_id to a completed copy of that package's result template.
Evidence paths in each result are relative to RESULTS.json's directory.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

import evidence
from contracts import project_path
from gates import ProjectError, digest, known_identity, load_json
from run_evidence import execution_binding


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ProjectError(f"Duplicate JSON key: {key}")
        value[key] = item
    return value


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, ValueError) as exc:
        raise ProjectError(f"Cannot read batch JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProjectError(f"Expected JSON object: {path}")
    return value


def _inside(base: Path, ref: str) -> Path:
    if not isinstance(ref, str) or not ref or Path(ref).is_absolute():
        raise ProjectError("Batch paths must be nonempty relative paths")
    return project_path(base, ref)


def _operator_fields(job: dict, job_ref: str) -> None:
    for name in ("environment_id", "resource_id"):
        if not isinstance(job.get(name), str) or not job[name].strip():
            raise ProjectError(f"{job_ref}: finalize {name} BEFORE preparing code review")
    identity = job.get("executor_identity")
    if not isinstance(identity, dict) or not known_identity(identity):
        raise ProjectError(f"{job_ref}: establish executor_identity BEFORE preparing code review")


def prepare(root: Path, idea: str, jobs_glob: str, out: Path) -> dict:
    root = root.resolve()
    out = out.resolve()
    if out.exists():
        raise ProjectError(f"Batch output already exists; preserve it: {out}")
    if Path(jobs_glob).is_absolute() or ".." in Path(jobs_glob).parts:
        raise ProjectError("--jobs-glob must stay inside the project")
    jobs = []
    skipped = []
    for path in sorted(root.glob(jobs_glob)):
        path = project_path(root, path)
        job_ref = path.relative_to(root).as_posix()
        job = _load(path)
        # The requested phase-2 *.json glob also matches the generation metadata.
        if path.name == "job-params.json" and "command" not in job and "operator_fields" in job:
            skipped.append(job_ref)
            continue
        if job.get("idea_id") != idea:
            raise ProjectError(f"Job is for another idea or is not a job: {job_ref}")
        _operator_fields(job, job_ref)
        jobs.append((job_ref, job))
    if not jobs:
        raise ProjectError("--jobs-glob matched no jobs")
    # Preflight ALL registrations/bindings before creating official packages.
    bindings = [evidence.execution_binding_hash(execution_binding(root, job)) for _, job in jobs]
    if len(set(bindings)) != len(bindings):
        raise ProjectError("Jobs contain duplicate execution bindings; use one package per binding")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".review-batch-", dir=out.parent) as temp:
        stage = Path(temp) / "batch"
        stage.mkdir()
        rows, templates = [], {}
        for (job_ref, job), binding_hash in zip(jobs, bindings):
            original = evidence.context_pack(root, idea, "code-review", job_ref=job_ref)
            manifest = _load(original / "manifest.json")
            if evidence.execution_binding_hash(manifest.get("execution_binding")) != binding_hash:
                raise ProjectError(f"Job binding changed during preparation: {job_ref}")
            package_id = original.name
            package_ref = f"packages/{package_id}"
            shutil.copytree(original, stage / package_ref)
            manifest_hash = digest(original / "manifest.json")
            row = {"package_id": package_id, "job_path": job_ref, "package_path": package_ref,
                   "source_package_path": evidence.rel(root, original),
                   "binding_sha256": binding_hash, "package_manifest_sha256": manifest_hash}
            rows.append(row)
            templates[package_id] = {**_load(original / "result-template.json"),
                                     "binding_sha256": binding_hash,
                                     "package_manifest_sha256": manifest_hash}
        index = {"schema_version": 1, "idea_id": idea, "purpose": "code-review",
                 "packages": rows, "skipped_metadata": skipped}
        evidence.write_json(stage / "index.json", index)
        evidence.write_json(stage / "results-template.json", templates)
        (stage / "REQUEST.md").write_text(
            "# Batch code review / 批量代码评审\n\n"
            "Use one new independent reviewer session for all indexed code-review packages. "
            "Read each package's REQUEST.md, manifest.json and ALL scoped files. "
            "每包单独填写 results-template.json 中对应的 result；不得用汇总结论替代逐包评审。\n\n"
            "Return RESULTS.json with exactly the indexed package IDs as keys. Preserve each "
            "binding_sha256 and package_manifest_sha256; attest direct_reads, actual identity, "
            "executor identity, round and fresh_context separately for EACH package. "
            "fresh_context attests this new batch session, not a separate session per code package. "
            "Evidence paths are relative to RESULTS.json. Retain the complete raw response and "
            "genuine identity evidence; do not invent identity or authorship metadata. "
            "Each receipt counts separately against any numeric review-call limit.\n\n"
            "Code authorship: Codex/OpenAI under project supervision; the bridge did not record "
            "the exact model. executor_identity names the actual operator, not the code author.\n\n"
            "Operator: keep the original project handoffs/ packages and generated files unchanged; "
            "the normal importer verifies their bytes as well as these portable copies. "
            "仅在真实 imported receipt 为 accepted PASS 时回填对应 job 的 code_review_receipt。\n",
            encoding="utf-8")
        stage.rename(out)
    return index


def import_batch(root: Path, directory: Path, results_path: Path) -> dict:
    root, directory, results_path = root.resolve(), directory.resolve(), results_path.resolve()
    index = _load(directory / "index.json")
    rows = index.get("packages")
    if index.get("schema_version") != 1 or index.get("purpose") != "code-review" or not isinstance(rows, list) or not rows:
        raise ProjectError("Invalid code-review batch index")
    if (directory / "receipts.json").exists():
        raise ProjectError("Batch import was already attempted; preserve receipts.json and existing receipts")
    if any(not isinstance(row, dict) or not isinstance(row.get("package_id"), str) or not row["package_id"] for row in rows):
        raise ProjectError("Invalid package ID in index")
    ids = [row["package_id"] for row in rows]
    if len(set(ids)) != len(ids):
        raise ProjectError("Duplicate package IDs in index")
    expected_packages = {_inside(directory, row.get("package_path")) for row in rows}
    package_root = directory / "packages"
    actual_packages = set()
    if package_root.is_dir():
        for path in package_root.iterdir():
            if path.is_symlink() or not path.is_dir():
                raise ProjectError("Batch packages must be ordinary package directories")
            actual_packages.add(path.resolve())
    if actual_packages != expected_packages:
        raise ProjectError("Batch package directories are missing or extra relative to index.json")
    results = _load(results_path)
    if set(results) != set(ids):
        raise ProjectError(f"Results must contain exactly one result per package; missing={sorted(set(ids)-set(results))}, extra={sorted(set(results)-set(ids))}")
    pending, packages, jobs, bindings = [], set(), set(), set()
    # Validate the complete package/result set before importing ANY receipt.
    for row in rows:
        package_id = row["package_id"]
        package = _inside(directory, row.get("package_path"))
        job_path = _inside(root, row.get("job_path"))
        manifest_hash = digest(package / "manifest.json")
        manifest = _load(package / "manifest.json")
        binding_hash = evidence.execution_binding_hash(manifest.get("execution_binding"))
        result = results[package_id]
        if (binding_hash is None or not isinstance(result, dict)
                or result.get("binding_sha256") != binding_hash or row.get("binding_sha256") != binding_hash
                or result.get("package_manifest_sha256") != manifest_hash or row.get("package_manifest_sha256") != manifest_hash):
            raise ProjectError(f"Result/package hash binding mismatch: {package_id}")
        if manifest.get("purpose") != "code-review" or manifest.get("idea_id") != index.get("idea_id"):
            raise ProjectError(f"Package scope differs from batch: {package_id}")
        if package in packages or job_path in jobs or binding_hash in bindings:
            raise ProjectError("Duplicate package, job or execution binding in batch")
        packages.add(package)
        jobs.add(job_path)
        bindings.add(binding_hash)
        job = _load(job_path)
        _operator_fields(job, row["job_path"])
        if job.get("idea_id") != index.get("idea_id") or evidence.execution_binding_hash(execution_binding(root, job)) != binding_hash:
            raise ProjectError(f"Current job binding changed since preparation: {row['job_path']}")
        for entry in manifest["files"]:
            if (digest(_inside(package, entry["packaged_path"])) != entry["sha256"]
                    or digest(root / entry["path"]) != entry["sha256"]):
                raise ProjectError(f"Review material/source changed: {package_id}: {entry['path']}")
        pending.append((row, package, result))
    policy = load_json(root / "configs/models.json").get("policy", {})
    limit = policy.get("max_review_calls", 24)
    if limit is not None and len(list((root / "reviews/receipts").glob("*/receipt.json"))) + len(rows) > limit:
        raise ProjectError("Global review call budget cannot cover every per-package receipt")
    report = {"schema_version": 1, "status": "importing", "results_sha256": digest(results_path), "receipts": []}
    # Keep temporary per-package result files BESIDE RESULTS so relative evidence
    # references retain precisely the normal import-review interpretation.
    try:
        for row, package, result in pending:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".review-result-", suffix=".json",
                                             dir=results_path.parent) as stream:
                json.dump(result, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                receipt_path = evidence.import_review(root, package, Path(stream.name))
            receipt = _load(receipt_path)
            report["receipts"].append({"package_id": row["package_id"], "job_path": row["job_path"],
                                       "binding_sha256": row["binding_sha256"],
                                       "receipt_path": evidence.rel(root, receipt_path),
                                       "verdict": receipt["verdict"], "acceptance_status": receipt["acceptance_status"]})
            evidence.write_json(directory / "receipts.json", report)
    except (ProjectError, OSError, ValueError, KeyError, TypeError) as exc:
        report.update(status="BLOCKED", error=str(exc))
        evidence.write_json(directory / "receipts.json", report)
        raise ProjectError(f"Batch import stopped; preserve receipts.json and any imported receipts: {exc}") from exc
    report["status"] = "imported"
    evidence.write_json(directory / "receipts.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("prepare")
    pack.add_argument("--idea", required=True)
    pack.add_argument("--jobs-glob", required=True)
    pack.add_argument("--out", required=True, type=Path)
    imp = commands.add_parser("import")
    imp.add_argument("--dir", required=True, type=Path)
    imp.add_argument("--results", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            value = prepare(args.root, args.idea, args.jobs_glob, args.out)
        else:
            value = import_batch(args.root, args.dir, args.results)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0
    except (ProjectError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
