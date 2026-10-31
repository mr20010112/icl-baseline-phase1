"""Isolated artifact handoffs, imported review receipts, and claim evidence audit."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import uuid
from typing import Any
from contracts import verify as verify_contract
from gates import (ProjectError, check_receipt, check_run_metrics, digest,
                   independence, known_identity, load_json, nonempty_evidence, resolve)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(root: Path, path: Path) -> str:
    path = path.resolve()
    return path.relative_to(root.resolve()).as_posix() if path.is_relative_to(root.resolve()) else str(path)


IDEA_FIELDS = ("id", "idea_id", "question", "hypothesis", "description", "novelty_evidence",
               "compatibility", "implementation_cost", "expected_signal", "risks")


def execution_binding_hash(binding: dict | None) -> str | None:
    """Stable job scope shared by single-package and batch review imports."""
    if binding is None:
        return None
    return hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def context_pack(root: Path, idea: str, purpose: str, *, job_ref: str | None = None,
                 contract_ref: str | None = None, runs: list[str] | None = None,
                 analysis_ref: str | None = None) -> Path:
    if not idea or not all(c.isalnum() or c in "_-" for c in idea):
        raise ProjectError("Use a simple idea id")
    research = load_json(root / "configs/research.json")
    if purpose == "implementation" and research.get("selected_idea") != idea:
        raise ProjectError("Implementation may load only the selected idea")
    analysis = None
    if purpose == "result-review":
        from results import check_analysis
        if not analysis_ref:
            raise ProjectError("Result review requires --analysis")
        analysis = check_analysis(root, analysis_ref, contract_ref=contract_ref, runs=runs or None)
        contract_ref, runs = analysis["contract"], analysis["runs"]
        protocol = load_json(resolve(root, contract_ref))
        if protocol["idea_id"] != idea:
            raise ProjectError("Analysis belongs to another idea")
        card = {"idea_id": idea, "hypothesis": protocol["hypothesis"]}
        original = None
    else:
        original = root / "idea-stage/ideas" / f"{idea}.json"
        if purpose == "code-review" and idea == "baseline" and not original.exists():
            baseline_job = load_json(resolve(root, job_ref))
            baseline_protocol = load_json(resolve(root, baseline_job["contract"]))
            card = {"idea_id": idea, "hypothesis": baseline_protocol["hypothesis"]}
            original = None
        else:
            card = load_json(original)
    clean = {k: card[k] for k in IDEA_FIELDS if k in card}
    clean["idea_id"] = idea
    if not clean.get("hypothesis"):
        raise ProjectError("Idea card needs a hypothesis")
    base = resolve(root, research.get("baseline", {}).get("paper_source"))
    job = load_json(resolve(root, job_ref)) if job_ref else {}
    if job and job.get("idea_id") != idea:
        raise ProjectError("Job is for another idea")
    if purpose == "code-review" and not job:
        raise ProjectError("Code review requires --job to bind code/config/protocol")
    protocol_ref = contract_ref or job.get("contract")
    folder = root / "handoffs" / idea / purpose / uuid.uuid4().hex[:12]
    files = folder / "files"
    files.mkdir(parents=True)
    entries: list[dict] = []
    bindings = [{"path": rel(root, original), "sha256": digest(original)}] if original else []

    def generated(name: str, value: Any) -> None:
        dest = files / name
        write_json(dest, value)
        entries.append({"path": rel(root, dest), "packaged_path": rel(folder, dest),
                        "sha256": digest(dest), "generated": True})

    def add(ref: str) -> None:
        src = resolve(root, ref)
        source = rel(root, src)
        if source in {e["path"] for e in entries}:
            return
        dest = files / f"{len(entries):03d}-{src.name}"
        shutil.copyfile(src, dest)
        entries.append({"path": source, "packaged_path": rel(folder, dest), "sha256": digest(dest)})

    generated("idea.json", clean)
    generated("constraints.json", {
        "question": research.get("question"), "setting": research.get("setting"),
        "resource_constraints": load_json(root / "configs/resources.json"),
        "budget": load_json(root / "configs/budget.json"),
        "note": "Source familiarity gives no extra evidential weight. No model capability ranking is assumed."
    })
    add(rel(root, base))
    execution = None
    if purpose == "code-review":
        from run_evidence import execution_binding
        execution = execution_binding(root, job)
        generated("execution.json", execution)
    if analysis is not None:
        add(analysis_ref)
    if purpose != "idea-review":
        working = root / "idea-stage/docs/research_contract.md"
        if working.exists() and purpose != "result-review":
            add(rel(root, working))
        if protocol_ref:
            verify_contract(root, protocol_ref)
            protocol = load_json(resolve(root, protocol_ref))
            if protocol.get("idea_id") != idea:
                raise ProjectError("Protocol belongs to another idea")
            add(protocol_ref)
        elif purpose in ("implementation", "code-review"):
            raise ProjectError("Implementation/code review needs a frozen protocol reference")
        if job:
            add(job["config"])
            for ref in job.get("code_paths", []):
                src = resolve(root, ref, file=False)
                for child in ([src] if src.is_file() else sorted(x for x in src.rglob("*") if x.is_file())):
                    add(rel(root, child))
        for task in runs or []:
            run_dir = root / "runs" / task
            manifest = load_json(run_dir / "manifest.json")
            if manifest.get("idea_id") != idea:
                raise ProjectError("Analysis scope contains a different idea")
            for child in sorted(x for x in run_dir.rglob("*") if x.is_file()):
                add(rel(root, child))
    manifest = {
        "schema_version": 1, "created_at": now(), "idea_id": idea, "purpose": purpose,
        "contract": protocol_ref if purpose != "idea-review" else None,
        "files": entries, "input_bindings": bindings,
        "executor_identity": analysis["analyst_identity"] if analysis is not None else job.get("executor_identity", card.get("proposer_identity", {})),
        "execution_binding": execution,
        "analysis": {"path": rel(root, resolve(root, analysis_ref)), "sha256": digest(resolve(root, analysis_ref))} if analysis is not None else None,
        "runs": runs or [],
        "boundary": "fresh_session_only; no candidate pool, generation transcripts, rankings or architect preferences"
    }
    write_json(folder / "manifest.json", manifest)
    request = (
        "# 独立交接请求\n\n在新的独立会话/空工作区中仅打开本包 files/ 内的材料。"
        "不要访问候选池、生成讨论或主 architect 的偏好。逐一读取原文、契约、代码与原始运行材料；"
        "不以执行者总结替代直接检查。每个 idea-review 包须使用独立上下文。\n\n"
        f"目的：{purpose}；当前 idea：{idea}。manifest.json 列出来源路径与副本路径。\n\n"
        "将结论写为 result-template.json 的一个副本；actual_identity 必须来自实际 provider/CLI/MCP 元数据，"
        "并提供 identity_evidence 文件。人工评审显式 actor_type=human，不填虚构 model ID。"
        "direct_reads 使用 manifest 中的 path。raw_response_file 应保存完整原始回答。"
        "同一模型换角色仅为 same-family，不能完成跨模型门禁。\n\n"
        "评审只提出当前研究所需的修正。verdict=PASS 不代表实证成功；缺材料填 BLOCKED。"
        "科学 claim 必须指向真实运行和分析。\n"
    )
    if analysis is not None:
        request += "\n逐项核对 signal_results 的判定与原始证据；核查统计方案、全部 seeds 和每个 signal 的依据。PASS 表示判定有证据支持，包括 failure/inconclusive，不表示实验成功。\n"
    (folder / "REQUEST.md").write_text(request, encoding="utf-8")
    write_json(folder / "result-template.json", {
        "completion": "pending", "verdict": "BLOCKED", "fresh_context": False,
        "round": 1, "dispatch_mode": "manual_handoff", "reported_cost_usd": None,
        "actual_identity": {"actor_type": "model", "provider": None, "model": None,
                            "model_family": None, "identity_source": None},
        "identity_evidence_file": None, "executor_identity": manifest["executor_identity"],
        "direct_reads": [], "raw_response_file": None,
        "findings": [], "limitations": ["尚未完成实际评审"]
    })
    if purpose == "idea-review":
        template = load_json(folder / "result-template.json")
        template["scorecard"] = {"scores": {key: None for key in ("novelty", "feasibility", "compatibility", "complexity", "expected_gain")}, "recommendation": None, "reasons": [], "revision_requests": []}
        write_json(folder / "result-template.json", template)
    return folder


def _import_review(root: Path, package: Path, result_path: Path) -> Path:
    manifest = load_json(package / "manifest.json")
    result = load_json(result_path)
    if result.get("completion") != "complete" or result.get("verdict") not in ("PASS", "WARN", "FAIL", "BLOCKED", "ERROR", "NOT_APPLICABLE"):
        raise ProjectError("Import requires a completed review with a six-state verdict")
    if result.get("fresh_context") is not True:
        raise ProjectError("Fresh review context has not been attested")
    policy = load_json(root / "configs/models.json").get("policy", {})
    round_no = result.get("round")
    if not isinstance(round_no, int) or not 1 <= round_no <= policy.get("max_review_rounds", 2):
        raise ProjectError("Review round budget exhausted or unspecified")
    reviewer = result.get("actual_identity", {})
    executor = manifest.get("executor_identity", {})
    if not known_identity(reviewer) or not known_identity(executor):
        raise ProjectError("Actual executor/reviewer identities are not established")
    if result.get("executor_identity") != executor:
        raise ProjectError("Executor identity differs from handoff manifest")
    if manifest["purpose"] == "idea-review":
        from selection import validate_scorecard
        validate_scorecard(result.get("scorecard"))
    for item in manifest["files"]:
        if digest(resolve(package, item["packaged_path"])) != item["sha256"]:
            raise ProjectError("Handoff material was modified")
        if digest(resolve(root, item["path"])) != item["sha256"]:
            raise ProjectError(f"Review source has changed: {item['path']}")
    for item in manifest.get("input_bindings", []):
        if digest(resolve(root, item["path"])) != item["sha256"]:
            raise ProjectError("Idea changed after isolated handoff was prepared")
    required = {item["path"] for item in manifest["files"]}
    if not required.issubset(set(result.get("direct_reads", []))):
        raise ProjectError("Reviewer has not attested direct reads of all scoped artifacts")
    raw = nonempty_evidence(result_path.parent, result.get("raw_response_file"))
    identity_raw = nonempty_evidence(result_path.parent, result.get("identity_evidence_file"))
    all_receipts = list((root / "reviews/receipts").glob("*/receipt.json"))
    call_limit = policy.get("max_review_calls", 24)
    if call_limit is not None and len(all_receipts) >= call_limit:
        raise ProjectError("Global review call budget exhausted")
    existing = []
    for old_path in (root / "reviews/receipts").glob("*/receipt.json"):
        old = load_json(old_path)
        scope = old.get("scope", {})
        if old.get("package_manifest", {}).get("sha256") == digest(package / "manifest.json"):
            raise ProjectError("This package was already imported; preserve the receipt instead of duplicating it")
        if (scope.get("idea_id"), scope.get("purpose"), scope.get("contract")) == (manifest["idea_id"], manifest["purpose"], manifest.get("contract")):
            binding = manifest.get("execution_binding")
            if binding is None or execution_binding_hash(scope.get("execution_binding")) == execution_binding_hash(binding):
                existing.append(old)
    if round_no != len(existing) + 1:
        raise ProjectError(f"Review round must be {len(existing) + 1}; prior reviews cannot be reset")
    review_allowed = independence(executor, reviewer) == "cross-family" or (independence(executor, reviewer) == "human-review" and policy.get("accept_human_reviews", True))
    if manifest["purpose"] == "result-review":
        from results import check_analysis
        analysis = check_analysis(root, manifest["analysis"]["path"], contract_ref=manifest["contract"], runs=manifest["runs"])
        if analysis["kind"] == "real":
            for task in analysis["runs"]:
                actor = load_json(root / "runs" / task / "manifest.json").get("job", {}).get("executor_identity", {})
                relation = independence(actor, reviewer)
                review_allowed = review_allowed and (relation == "cross-family" or (relation == "human-review" and policy.get("accept_human_reviews", True)))
    receipt_id = uuid.uuid4().hex[:12]
    dest = root / "reviews/receipts" / receipt_id
    dest.mkdir(parents=True)
    shutil.copyfile(raw, dest / "response.txt")
    shutil.copyfile(identity_raw, dest / "identity.txt")
    receipt = {
        **result, "schema_version": 1, "imported_at": now(),
        "budget_note": "Import does not make a paid model call. External model payment/cost is unverified unless independently accounted; null is not zero.",
        "actual_identity": reviewer, "executor_identity": executor,
        "independence": independence(executor, reviewer),
        "scope": {"purpose": manifest["purpose"], "idea_id": manifest["idea_id"],
                  "contract": manifest.get("contract"), "files": manifest["files"],
                  "input_bindings": manifest.get("input_bindings", []),
                  "execution_binding": manifest.get("execution_binding"),
                  "analysis": manifest.get("analysis"), "runs": manifest.get("runs", [])},
        "raw_response": {"path": rel(root, dest / "response.txt"), "sha256": digest(dest / "response.txt")},
        "identity_evidence": {"path": rel(root, dest / "identity.txt"), "sha256": digest(dest / "identity.txt")},
        "package_manifest": {"path": rel(root, package / "manifest.json"), "sha256": digest(package / "manifest.json")},
        "acceptance_status": "accepted" if review_allowed and result["verdict"] == "PASS" else "provisional"
    }
    path = dest / "receipt.json"
    write_json(path, receipt)
    return path


def import_review(root: Path, package: Path, result_path: Path) -> Path:
    lock_path = root / "reviews/.import.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            return _import_review(root, package, result_path)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def check_venue_code(record: dict) -> None:
    """Venue and code availability are screening factors; unknown must be explicit."""
    venue = record.get("venue")
    if not isinstance(venue, str) or not venue.strip():
        raise ProjectError("Verified literature needs venue (exact venue+year, 'arXiv preprint' or 'unresolved')")
    code = record.get("code_url")
    if not isinstance(code, str) or not (code.startswith(("https://", "http://")) or code in ("none", "unresolved")):
        raise ProjectError("Verified literature needs code_url (URL, 'none' or 'unresolved')")


def audit(root: Path, paper: bool = False) -> dict:
    errors: list[str] = []
    checked = {"literature_records": 0, "claims": 0, "empirical_claims": 0}
    literature = root / "idea-stage/literature/evidence.jsonl"
    if literature.exists():
        for line_no, line in enumerate(literature.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                checked["literature_records"] += 1
                cls = record.get("classification")
                if cls not in ("verified", "author_opinion", "model_inference", "hypothesis"):
                    raise ProjectError("Unclassified literature statement")
                if not record.get("source") or not record.get("locator"):
                    raise ProjectError("Literature statement needs source and locator")
                if cls == "verified":
                    if not record.get("url", "").startswith(("https://", "http://")) or not record.get("checked_at"):
                        raise ProjectError("Verified statement lacks URL/check time")
                    check_venue_code(record)
                    src = nonempty_evidence(root, record.get("artifact"))
                    if record.get("artifact_sha256") != digest(src):
                        raise ProjectError("Verified literature source fingerprint missing/stale")
            except (ProjectError, ValueError, KeyError, OSError) as exc:
                errors.append(f"literature:{line_no}: {exc}")
    claim_path = root / "paper/claims.json"
    if claim_path.exists():
        container = load_json(claim_path)
        claims = container if isinstance(container, list) else container.get("claims", [])
        for claim in claims:
            checked["claims"] += 1
            if claim.get("type") != "empirical":
                continue
            checked["empirical_claims"] += 1
            try:
                if claim.get("kind") not in ("real", "toy"):
                    raise ProjectError("Empirical claim requires explicit kind")
                if paper and claim.get("kind") != "real":
                    raise ProjectError("Toy/mock result is forbidden in the formal paper evidence set")
                if not claim.get("metrics") or not isinstance(claim["metrics"], list):
                    raise ProjectError("Empirical claim must identify at least one measured metric")
                if not claim.get("hypothesis") or not claim.get("contract") or not claim.get("runs"):
                    raise ProjectError("Claim lacks hypothesis/protocol/run linkage")
                verify_contract(root, claim["contract"])
                protocol = load_json(resolve(root, claim["contract"]))
                if claim["hypothesis"] != protocol.get("hypothesis"):
                    raise ProjectError("Claim hypothesis does not match its frozen protocol")
                if protocol.get("kind") != claim["kind"]:
                    raise ProjectError("Claim/protocol kind mismatch")
                from results import check_analysis, check_result_review, validate_signals
                analysis = check_analysis(root, claim.get("analysis_file"), contract_ref=claim["contract"])
                check_result_review(root, claim["analysis_file"], analysis, claim.get("result_review_receipt"))
                signal_ids = claim.get("signal_ids")
                signals = validate_signals(protocol)
                if not isinstance(signal_ids, list) or not signal_ids or any(not isinstance(x, str) for x in signal_ids) or len(set(signal_ids)) != len(signal_ids) or not set(signal_ids) <= set(signals):
                    raise ProjectError("Claim must bind existing unique signal_ids")
                selected = [x for x in analysis["signal_results"] if x["signal_id"] in signal_ids]
                pairs = {(item["run_id"], item["metric"]) for result in selected for item in result["evidence"] if "metric" in item}
                if not {(task, metric) for task in claim["runs"] for metric in claim["metrics"]} <= pairs:
                    raise ProjectError("Claim run/metric references are not covered by its signals")
                if analysis.get("contract") != claim["contract"]:
                    raise ProjectError("Analysis lacks the exact bound protocol reference")
                if analysis.get("kind") != claim["kind"] or analysis.get("outcome") not in ("success", "failure", "inconclusive"):
                    raise ProjectError("Analysis kind or scientific outcome missing")
                if not analysis.get("decision") or "limitations" not in analysis:
                    raise ProjectError("Analysis needs decision and limitations")
                for task in claim["runs"]:
                    manifest = load_json(root / "runs" / task / "manifest.json")
                    if manifest.get("status") != "completed" or manifest.get("kind") != claim["kind"]:
                        raise ProjectError("Claim cites an incomplete or wrong-kind run")
                    binding = manifest.get("contract", {})
                    if binding.get("path") != claim["contract"] or digest(resolve(root, binding.get("path"))) != binding.get("sha256"):
                        raise ProjectError("Claim changed its experiment's frozen protocol")
                    if digest(root / "runs" / task / binding.get("snapshot", "contract.yaml")) != binding["sha256"]:
                        raise ProjectError("Bound protocol snapshot was modified")
                    run_dir = root / "runs" / task
                    config = manifest.get("config", {})
                    if not config.get("snapshot") or digest(run_dir / config["snapshot"]) != config.get("sha256"):
                        raise ProjectError("Run configuration snapshot missing or modified")
                    code = manifest.get("code", [])
                    if not code:
                        raise ProjectError("Run lacks implementation snapshots")
                    for entry in code:
                        if digest(run_dir / entry["snapshot"]) != entry.get("sha256"):
                            raise ProjectError("Run implementation snapshot modified")
                    index = load_json(run_dir / "artifacts.json")
                    indexed = index.get("files", [])
                    paths = {entry.get("path") for entry in indexed}
                    required_artifacts = {binding.get("snapshot", "contract.yaml"), config["snapshot"], manifest.get("metrics", {}).get("path", "metrics.json")}
                    required_artifacts.update(entry["snapshot"] for entry in code)
                    if not required_artifacts.issubset(paths):
                        raise ProjectError("Artifact index does not cover protocol/config/code/raw metrics")
                    for entry in indexed:
                        artifact = run_dir / entry["path"]
                        if not artifact.is_file() or digest(artifact) != entry.get("sha256") or artifact.stat().st_size != entry.get("bytes"):
                            raise ProjectError(f"Indexed run artifact missing or modified: {entry.get('path')}")
                    values = check_run_metrics(root, manifest)
                    if task not in analysis.get("runs", []):
                        raise ProjectError("Analysis does not cover the cited run")
                    for metric in claim.get("metrics", []):
                        if metric not in values:
                            raise ProjectError(f"Claim metric has no raw measurement: {metric}")
                    if claim.get("baseline_value_source") == "paper_reported" and claim.get("baseline_label") == "reproduced":
                        raise ProjectError("Paper-reported baseline cannot be labeled reproduced")
            except (ProjectError, ValueError, KeyError, OSError) as exc:
                errors.append(f"claim:{claim.get('id', '?')}: {exc}")
    return {"status": "FAIL" if errors else "PASS", "checked": checked, "errors": errors,
            "scope": "structural evidence audit; semantic/scientific audit remains required",
            "empty_evidence": checked["empirical_claims"] == 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    pack = sub.add_parser("context-pack")
    pack.add_argument("--idea", required=True)
    pack.add_argument("--purpose", required=True, choices=("idea-review", "implementation", "analysis", "code-review", "result-review"))
    pack.add_argument("--job")
    pack.add_argument("--contract")
    pack.add_argument("--run", action="append", default=[])
    pack.add_argument("--analysis")
    imp = sub.add_parser("import-review")
    imp.add_argument("--package", required=True)
    imp.add_argument("--result", required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--paper", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if args.command == "context-pack":
            result = {"package": str(context_pack(root, args.idea, args.purpose, job_ref=args.job, contract_ref=args.contract, runs=args.run, analysis_ref=args.analysis)),
                      "status": "HANDOFF_PENDING", "integration_verified": False}
        elif args.command == "import-review":
            result = {"receipt": str(import_review(root, resolve(root, args.package, file=False), resolve(root, args.result)))}
        else:
            result = audit(root, args.paper)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("status") == "FAIL" else 0
    except (ProjectError, ValueError, KeyError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
