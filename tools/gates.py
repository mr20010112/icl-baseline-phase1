"""Research gates: structural/evidence checks, never a scientific truth oracle."""
from __future__ import annotations
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from contracts import ProjectError
except ImportError:
    class ProjectError(ValueError):
        pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProjectError(f"Cannot read JSON {path}: {exc}") from exc


def resolve(root: Path, value: str | None, *, file: bool = True) -> Path:
    if not isinstance(value, str) or not value:
        raise ProjectError("Required evidence path is unset")
    p = Path(value)
    p = p if p.is_absolute() else root / p
    if not p.exists() or (file and not p.is_file()):
        raise ProjectError(f"Missing evidence: {value}")
    return p


def digest(path: Path) -> str:
    """SHA256 bytes, or sorted relative-path + file-hash tree (no symlink dirs)."""
    if path.is_file():
        h = hashlib.sha256()
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()
    h = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        h.update(item.relative_to(path).as_posix().encode("utf-8") + b"\0")
        h.update(digest(item).encode("ascii") + b"\n")
    return h.hexdigest()


def nonempty_evidence(root: Path, value: str | None) -> Path:
    p = resolve(root, value)
    if p.stat().st_size == 0:
        raise ProjectError(f"Empty evidence: {value}")
    return p


def resource(root: Path, group: str, ident: str, kind: str) -> dict:
    registry = load_json(root / "configs/resources.json")
    matches = [x for x in registry.get(group, []) if x.get("id") == ident]
    if len(matches) != 1:
        raise ProjectError(f"Missing or duplicate {group} resource: {ident}")
    item = matches[0]
    if item.get("status") != "verified" or item.get("kind") != kind:
        raise ProjectError(f"Resource {ident} is not verified {kind}")
    nonempty_evidence(root, item.get("verification", {}).get("evidence_file"))
    if group in ("data", "weights"):
        p = resolve(root, item.get("path"), file=False)
        if not item.get("version") or not item.get("split") or item.get("fingerprint") != digest(p):
            raise ProjectError(f"Data version/split/fingerprint missing or stale: {ident}")
    elif group == "environments":
        resolve(root, item.get("path"), file=False)
        if not item.get("version") or not item.get("verification", {}).get("command"):
            raise ProjectError(f"Environment version/witness command missing: {ident}")
    elif group == "compute":
        if item.get("backend", "local") != "local":
            raise ProjectError("This runner supports only local compute; remote/scheduler handoff is unverified")
        if not isinstance(item.get("cpus"), int) or item["cpus"] < 1:
            raise ProjectError("Compute cpus must be a positive integer")
        if not isinstance(item.get("gpus"), int) or item["gpus"] < 0:
            raise ProjectError("Compute gpus must be a non-negative integer")
    return item


def known_identity(identity: dict) -> bool:
    if identity.get("actor_type") == "human":
        return bool(identity.get("person") and identity.get("identity_source"))
    return all(identity.get(k) and str(identity[k]).lower() not in ("unknown", "pending", "unset")
               for k in ("provider", "model", "model_family", "identity_source"))


def independence(executor: dict, reviewer: dict) -> str:
    if not known_identity(executor) or not known_identity(reviewer):
        return "unknown"
    if reviewer.get("actor_type") == "human":
        if executor.get("actor_type") == "human" and executor.get("person") == reviewer.get("person"):
            return "same-person"
        return "human-review"
    if executor.get("actor_type") == "human":
        return "cross-family"
    return "cross-family" if executor["model_family"].casefold() != reviewer["model_family"].casefold() else "same-family"


def check_receipt(root: Path, receipt_ref: str | None, purpose: str, job: dict) -> dict:
    receipt = load_json(resolve(root, receipt_ref))
    if receipt.get("completion") != "complete" or receipt.get("verdict") != "PASS":
        raise ProjectError(f"Required {purpose} review is not complete/PASS")
    scope = receipt.get("scope", {})
    if scope.get("purpose") != purpose or scope.get("idea_id") != job.get("idea_id"):
        raise ProjectError(f"Wrong review scope: {purpose}")
    if purpose == "code-review" and scope.get("contract") != job.get("contract"):
        raise ProjectError("Review did not cover this frozen protocol version")
    if receipt.get("fresh_context") is not True:
        raise ProjectError("Required review lacks a fresh isolated context")
    declared_executor = receipt.get("executor_identity", {})
    actual_executor = job.get("executor_identity", declared_executor)
    if purpose == "idea-review":
        card = load_json(resolve(root, f"idea-stage/ideas/{job['idea_id']}.json"))
        actual_executor = card.get("proposer_identity", {})
    if actual_executor != declared_executor:
        raise ProjectError("Review executor identity differs from run executor")
    actual = independence(declared_executor, receipt.get("actual_identity", {}))
    policy = load_json(root / "configs/models.json").get("policy", {})
    allowed = actual == "cross-family" or (actual == "human-review" and policy.get("accept_human_reviews", True))
    if not allowed or receipt.get("independence") != actual:
        raise ProjectError(f"Required independent review unavailable ({actual}); cannot pass by role switch")
    if receipt.get("acceptance_status") != "accepted":
        raise ProjectError("Required review receipt has not been accepted")
    package_binding = receipt.get("package_manifest", {})
    package_path = nonempty_evidence(root, package_binding.get("path"))
    if digest(package_path) != package_binding.get("sha256"):
        raise ProjectError("Review package manifest missing or changed")
    package = load_json(package_path)
    for key in ("purpose", "idea_id", "contract", "files", "input_bindings", "execution_binding", "analysis", "runs"):
        default = [] if key in ("input_bindings", "runs") else None
        if scope.get(key, default) != package.get(key, default):
            raise ProjectError("Review receipt scope differs from original package: " + key)
    if package.get("executor_identity") != declared_executor:
        raise ProjectError("Review executor differs from original package")
    files = scope.get("files", [])
    if not files:
        raise ProjectError("Review has no direct artifact scope")
    reads = set(receipt.get("direct_reads", []))
    for entry in files:
        if entry.get("path") not in reads or digest(resolve(root, entry.get("path"))) != entry.get("sha256"):
            raise ProjectError(f"Stale or unread review artifact: {entry.get('path')}")
    for entry in scope.get("input_bindings", []):
        if digest(resolve(root, entry.get("path"))) != entry.get("sha256"):
            raise ProjectError("Reviewed idea source changed after isolation")
    identity = receipt.get("identity_evidence", {})
    if digest(nonempty_evidence(root, identity.get("path"))) != identity.get("sha256"):
        raise ProjectError("Actual reviewer identity lacks preserved evidence")
    raw = receipt.get("raw_response", {})
    if digest(nonempty_evidence(root, raw.get("path"))) != raw.get("sha256"):
        raise ProjectError("Review raw response missing or changed")
    if purpose == "code-review":
        from run_evidence import execution_binding
        if scope.get("execution_binding") != execution_binding(root, job):
            raise ProjectError("Reviewed execution binding differs from job/command/config/code")
        covered = {x["path"] for x in files}
        for code in job.get("code_paths", []):
            p = resolve(root, code, file=False)
            children = [p] if p.is_file() else [x for x in p.rglob("*") if x.is_file()]
            for child in children:
                rel = child.relative_to(root).as_posix() if child.is_relative_to(root) else str(child)
                if rel not in covered:
                    raise ProjectError(f"Code not directly reviewed: {rel}")
        for ref in (job.get("contract"), job.get("config")):
            if ref not in covered:
                raise ProjectError(f"Contract/config not directly reviewed: {ref}")
    return receipt


def check_baseline(root: Path, research: dict, *, reproduced: bool) -> None:
    baseline = research.get("baseline", {})
    nonempty_evidence(root, baseline.get("paper_source"))
    if not baseline.get("repo") or len(str(baseline.get("commit", ""))) != 40:
        raise ProjectError("Baseline repository and exact commit are required")
    repo = resolve(root, baseline.get("repo_path"), file=False)
    try:
        actual = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                                capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProjectError(f"Baseline code revision cannot be verified: {exc}") from exc
    if actual != baseline["commit"]:
        raise ProjectError("Baseline checkout differs from configured commit")
    validation = load_json(resolve(root, baseline.get("validation_record")))
    if validation.get("kind") != "real" or validation.get("baseline_commit") != actual:
        raise ProjectError("Baseline preflight is stale or not real")
    for name in ("data", "environment", "evaluation"):
        check = validation.get("checks", {}).get(name, {})
        if check.get("status") != "pass":
            raise ProjectError(f"Baseline preflight incomplete: {name}")
        nonempty_evidence(root, check.get("evidence_file"))
    if reproduced:
        from run_evidence import check_run_evidence
        from results import check_analysis, check_result_review
        from statistics import mean, median
        import math
        rep = validation.get("reproduction", {})
        run_ids = rep.get("run_ids", [rep.get("run_id")])
        if not isinstance(run_ids, list) or not run_ids or any(not isinstance(x, str) or not x for x in run_ids) or len(set(run_ids)) != len(run_ids):
            raise ProjectError("Baseline reproduction needs unique run_ids")
        data = resource(root, "data", research.get("data_id"), "real")
        rows, protocols, seeds = [], [], []
        contract_ref = None
        for task in run_ids:
            from contracts import project_path
            manifest = load_json(project_path(root, "runs/" + task) / "manifest.json")
            if manifest.get("task_id") != task or manifest.get("kind") != "real" or manifest.get("stage") != "baseline" or manifest.get("idea_id") != "baseline":
                raise ProjectError("Baseline requires a real baseline run")
            rows.append(check_run_evidence(root, manifest))
            ref = manifest["contract"]["path"]
            if contract_ref is not None and ref != contract_ref:
                raise ProjectError("Baseline runs must bind one frozen protocol")
            contract_ref = ref
            protocol = load_json(resolve(root, ref))
            protocols.append(protocol)
            seeds.append(manifest["seed"])
            if manifest.get("environment_id") != research.get("environment_id"):
                raise ProjectError("Baseline reproduction environment differs")
            recorded = manifest.get("resources", {}).get("data", {})
            if manifest.get("dataset_id") != data["id"] or recorded.get("fingerprint") != data["fingerprint"]:
                raise ProjectError("Baseline data fingerprint differs from current registered data")
            for key in ("version", "split", "fingerprint"):
                if protocol.get("data", {}).get(key) != data.get(key):
                    raise ProjectError("Baseline frozen data differs: " + key)
            if protocol.get("baseline", {}).get("commit") != actual:
                raise ProjectError("Baseline reproduction code revision differs")
        protocol = protocols[0]
        expected_seeds = protocol["seeds"]
        if isinstance(expected_seeds, dict):
            expected_seeds = expected_seeds.get("values", expected_seeds.get("seeds", []))
        if len(seeds) != len(set(seeds)) or set(seeds) != set(expected_seeds):
            raise ProjectError("Baseline reproduction must cover every frozen seed exactly once")
        analysis_ref = rep.get("analysis_file")
        analysis = check_analysis(root, analysis_ref, contract_ref=contract_ref, runs=run_ids)
        check_result_review(root, analysis_ref, analysis, rep.get("result_review_receipt"))
        if analysis.get("kind") != "real" or analysis.get("decision") != "pass" or analysis.get("outcome") != "success":
            raise ProjectError("Baseline analysis has not passed")
        tolerance, statistics = analysis.get("tolerance", {}), protocol.get("statistics", {})
        for key in ("metric", "atol", "rtol", "statistical_rule", "aggregation"):
            if key not in tolerance or tolerance[key] != statistics.get(key):
                raise ProjectError("Baseline comparison changed frozen statistics: " + key)
        metric = statistics["metric"]
        if any(metric not in row for row in rows):
            raise ProjectError("Baseline metric missing from raw measurements")
        comparison = analysis.get("comparison", {})
        paper_value, reproduced_value = comparison.get("paper_reported"), comparison.get("reproduced")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (paper_value, reproduced_value)):
            raise ProjectError("Baseline comparison needs finite paper_reported and reproduced values")
        if not comparison.get("paper_source") or resolve(root, comparison["paper_source"]).resolve() != resolve(root, baseline["paper_source"]).resolve():
            raise ProjectError("Baseline paper value lacks original paper binding")
        from contracts import sha
        reported = protocol.get("baseline", {}).get("reported_metrics", [])
        matches = [x for x in reported if isinstance(x, dict) and x.get("metric") == metric]
        if len(matches) != 1 or matches[0].get("value") != paper_value:
            raise ProjectError("Baseline paper_reported value differs from frozen source measurement")
        source = matches[0]
        if (not source.get("source") or resolve(root, source["source"]).resolve() != resolve(root, baseline["paper_source"]).resolve()
                or source.get("source_sha256") != sha(resolve(root, baseline["paper_source"]))):
            raise ProjectError("Baseline paper source differs from frozen source fingerprint")
        aggregation = statistics["aggregation"]
        if aggregation not in ("mean", "median"):
            raise ProjectError("Baseline automatic aggregation supports mean/median; register a supported comparison")
        value = (mean if aggregation == "mean" else median)(row[metric] for row in rows)
        if not math.isclose(value, reproduced_value, rel_tol=1e-12, abs_tol=1e-12):
            raise ProjectError("Baseline reproduced aggregate differs from raw metrics")
        if not math.isclose(value, paper_value, rel_tol=statistics["rtol"], abs_tol=statistics["atol"]):
            raise ProjectError("Baseline aggregate does not satisfy frozen reproduction tolerance")


def check_run_metrics(root: Path, manifest: dict) -> dict:
    import math
    metrics = manifest.get("metrics", {})
    p = root / "runs" / manifest["task_id"] / metrics.get("path", "metrics.json")
    if not p.is_file() or digest(p) != metrics.get("sha256"):
        raise ProjectError(f"Run metrics missing or changed: {manifest.get('task_id')}")
    values = load_json(p)
    if values != metrics.get("values") or not values:
        raise ProjectError("Run raw metrics differ from recorded values")
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in values.values()):
        raise ProjectError("Run metrics are not finite numeric measurements")
    return values


def check_novelty(root: Path, job: dict) -> dict:
    """Targeted novelty search must be a recorded, attributable search, not a bare go."""
    novelty = load_json(resolve(root, job.get("novelty_record")))
    if (novelty.get("idea_id") != job["idea_id"] or not novelty.get("queries")
            or not novelty.get("sources") or not novelty.get("checked_at")
            or novelty.get("decision") != "go"):
        raise ProjectError("Targeted novelty search is incomplete")
    if not known_identity(novelty.get("executor_identity", {})):
        raise ProjectError("Novelty search lacks a known executor identity")
    for key, label in (("raw_response", "raw response"), ("identity_evidence", "identity evidence")):
        binding = novelty.get(key, {})
        if (not isinstance(binding, dict) or not binding.get("path")
                or digest(nonempty_evidence(root, binding["path"])) != binding.get("sha256")):
            raise ProjectError(f"Novelty search {label} missing or changed")
    for source in novelty["sources"]:
        if not source.get("url") or not source.get("locator"):
            raise ProjectError("Novelty sources lack real URL/locator")
        nonempty_evidence(root, source.get("artifact"))
    return novelty


def check_job(root: Path, job: dict) -> None:
    kind = job.get("kind")
    if kind not in ("toy", "real"):
        raise ProjectError("kind must explicitly be toy or real")
    protocol = load_json(resolve(root, job.get("contract")))
    if protocol.get("kind") != kind:
        raise ProjectError("Toy/real protocol mismatch")
    registered = {}
    for group, key in (("data", "dataset_id"), ("environments", "environment_id"), ("compute", "resource_id")):
        registered[group] = resource(root, group, job.get(key), kind)
    environment_python = resolve(root, registered["environments"].get("path"), file=True)
    if not environment_python.samefile(sys.executable):
        raise ProjectError("Local runner must itself run in the registered Python environment; activate it and invoke that Python")
    command = job.get("command", [])
    if not command or command[0] not in ("{python}", sys.executable):
        raise ProjectError("Local runner requires command[0]={python}; shell/conda/container commands use an unverified handoff")
    from run_evidence import execution_binding
    execution_binding(root, job)
    for field in ("cpus", "gpus"):
        requested = job.get(field, 1 if field == "cpus" else 0)
        if not isinstance(requested, int) or requested < (1 if field == "cpus" else 0) or requested > registered["compute"][field]:
            raise ProjectError(f"Requested {field} exceeds registered resource or is invalid")
    data = protocol.get("data", {})
    data_id = data.get("dataset_id", data.get("id"))
    if data_id != job.get("dataset_id"):
        raise ProjectError("Protocol dataset does not match job dataset")
    for key in ("version", "split"):
        if data.get(key) != registered["data"].get(key):
            raise ProjectError(f"Protocol data {key} does not match registered data")
    for ident in job.get("weight_ids", []):
        resource(root, "weights", ident, kind)
    if kind == "toy":
        return
    if job.get("stage") == "baseline" and job.get("idea_id") != "baseline":
        raise ProjectError("Real baseline training must use idea_id=baseline; method sanity cannot be relabeled baseline")
    research = load_json(root / "configs/research.json")
    if protocol.get("data", {}).get("fingerprint") != registered["data"].get("fingerprint"):
        raise ProjectError("Real protocol must freeze the verified data fingerprint")
    if not research.get("question") or not research.get("setting"):
        raise ProjectError("Research question/setting are unset")
    if not protocol.get("method", {}).get("implementation") or not job.get("code_paths"):
        raise ProjectError("Method-to-code mapping missing")
    reviewed_roots = [resolve(root, code, file=False).resolve() for code in job["code_paths"]]
    for code in protocol["method"]["implementation"]:
        location = resolve(root, code.get("path") if isinstance(code, dict) else code, file=False).resolve()
        if not any(location == base or (base.is_dir() and location.is_relative_to(base)) for base in reviewed_roots):
            raise ProjectError("Method implementation is outside the run's code snapshot/review scope")
    protocol_baseline = protocol.get("baseline", {})
    if not isinstance(protocol_baseline, dict) or protocol_baseline.get("commit") != research.get("baseline", {}).get("commit"):
        raise ProjectError("Frozen baseline commit differs from research configuration")
    # Baseline preparation/training has its own frozen protocol. Any other
    # real training stage, including a method's "sanity", requires the anchor.
    check_baseline(root, research, reproduced=job.get("stage") != "baseline")
    check_receipt(root, job.get("code_review_receipt"), "code-review", job)
    if job.get("stage") != "baseline":
        if research.get("selected_idea") != job.get("idea_id"):
            raise ProjectError("Run idea is not the architect's selected idea")
        check_receipt(root, job.get("idea_review_receipt"), "idea-review", job)
        from selection import check_selection
        check_selection(root, job)
        check_novelty(root, job)
