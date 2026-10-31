#!/usr/bin/env python3
"""Project entry point. POSIX + Python >=3.10; offline checks use only stdlib."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from contracts import ProjectError, atomic_json, load, sha, verify


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def upstream_check(root: Path) -> dict:
    lock = load(root / "configs/upstream-lock.json")
    base = root / "vendor/aris"
    changed = [p for p, digest in lock["files"].items()
               if not (base / p).is_file() or sha(base / p) != digest]
    if changed:
        raise ProjectError(f"Upstream snapshot changed: {changed[:10]}")
    if sha(root / "docs/source/AI科研指南.md") != lock["guide_sha256"]:
        raise ProjectError("Original attached guide was changed")
    return {"commit": lock["commit"], "license": lock["license"], "verified_files": len(lock["files"])}


def install(root: Path) -> dict:
    from installation import reconcile
    return reconcile(root, _native_install, upstream_check)


def _native_install(root: Path) -> dict:
    """Run unmodified upstream installers only in an isolated staging root."""
    provenance = upstream_check(root)
    inventory = load(root / "configs/resources.json")
    logs = root / "reports/install"
    logs.mkdir(parents=True, exist_ok=True)
    tmp = root / ".aris/tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    installer_results = []
    for host, script in (("claude", "install_aris.sh"), ("codex", "install_aris_codex.sh")):
        native_lock = root / ".aris" / (".install.lock.d" if host == "claude" else ".install-codex.lock.d")
        lock_existed = native_lock.exists()
        cmd = ["bash", str(root / "vendor/aris/tools" / script), str(root),
               "--all", "--quiet", "--no-doc"]
        result = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=120,
                                env={**os.environ, "TMPDIR": str(tmp)})
        if "/dev/fd/" in result.stderr and not lock_existed and native_lock.exists():
            # Bash can abort before its EXIT trap in this restricted host. Only
            # remove the lock created by the child that has just returned.
            shutil.rmtree(native_lock)
        (logs / f"{host}.log").write_text(result.stdout + result.stderr)
        fallback = False
        fallback_method = None
        if result.returncode:
            # This restricted host has no /dev/fd. The mainline installer may
            # finish installation and fail only its final process-substitution
            # check. Verify every manifest entry directly without editing it.
            manifest = root / ".aris" / ("installed-skills.txt" if host == "claude" else "installed-skills-codex.txt")
            if "/dev/fd/" in result.stderr and manifest.is_file():
                entries = [line.split("\t") for line in manifest.read_text().splitlines()
                           if line.startswith(("skill\t", "support\t"))]
                fallback = bool(entries) and all(len(row) == 5 and (root / row[3]).is_dir()
                           and (root / row[3]).resolve() == (root / "vendor/aris" / row[2]).resolve()
                           for row in entries)
                fallback_method = "direct manifest verification after native installation"
            elif "/dev/fd/" in result.stderr and host == "codex":
                # Codex's inventory itself uses process substitution. In this
                # environment use the documented complete-pack flat layout,
                # preserving its native manifest schema and every source byte.
                base = root / "vendor/aris/skills/skills-codex"
                dest = root / ".agents/skills"
                dest.mkdir(parents=True, exist_ok=True)
                entries = []
                for source in sorted(base.iterdir()):
                    if not source.is_dir() or not ((source / "SKILL.md").is_file() or source.name == "shared-references"):
                        continue
                    link = dest / source.name
                    if link.exists() and not link.is_symlink():
                        raise ProjectError(f"Refuse to overwrite unmanaged skill: {link}")
                    if link.is_symlink():
                        if link.resolve() != source.resolve():
                            raise ProjectError(f"Conflicting skill link: {link}")
                        link.unlink()
                    link.symlink_to(os.path.relpath(source, link.parent))
                    entries.append(["support" if source.name == "shared-references" else "skill", source.name,
                                    source.relative_to(root / "vendor/aris").as_posix(),
                                    link.relative_to(root).as_posix(), "symlink"])
                text = "version\t1\nrepo_root\t" + str(root / "vendor/aris") + "\nproject_root\t" + str(root) + "\nkind\tname\tsource_rel\ttarget_rel\tmode\n"
                (root / ".aris/installed-skills-codex.txt").write_text(text + "".join("\t".join(row) + "\n" for row in entries))
                fallback = bool(entries) and all((root / row[3] / ("reviewer-independence.md" if row[0] == "support" else "SKILL.md")).is_file() for row in entries)
                fallback_method = "documented complete Codex pack flat links; native manifest schema"
            if not fallback:
                raise ProjectError(f"ARIS {host} install failed: reports/install/{host}.log")
        installer_results.append({"host": host, "exit_code": result.returncode,
                                  "project_manifest_verified": True,
                                  "dev_fd_fallback": fallback,
                                  "fallback_method": fallback_method})
    # Preserve upstream sources. Only project links are made relative so the
    # delivered folder can move. Rerunning the native installer remains valid.
    count = 0
    links = []
    for top in (root / ".claude", root / ".agents", root / ".aris", root / ".github"):
        for p in top.rglob("*"):
            if p.is_symlink():
                dest = p.resolve()
                if dest.is_relative_to(root):
                    p.unlink()
                    p.symlink_to(os.path.relpath(dest, p.parent))
                    links.append({"path": p.relative_to(root).as_posix(), "source": dest.relative_to(root).as_posix()})
                    count += 1
    record = {"status": "PASS", "upstream": provenance,
              "installation": "native project installers + relative project links",
              "relative_links": count, "at": datetime.now(timezone.utc).isoformat(),
              "links": links,
              "resources_checked": {group: len(inventory.get(group, [])) for group in ("data", "weights", "environments", "compute")},
              "installer_results": installer_results,
              "commands": ["bash vendor/aris/tools/install_aris.sh . --all --quiet --no-doc",
                           "bash vendor/aris/tools/install_aris_codex.sh . --all --quiet --no-doc"],
              "external_integrations": "UNVERIFIED"}
    atomic_json(root / ".aris/installation.json", record)
    if not (root / "research-wiki/index.md").exists() and not (root / "research-wiki/INDEX.md").exists():
        result = subprocess.run([sys.executable, str(root / "vendor/aris/tools/research_wiki.py"),
                                 "init", str(root / "research-wiki")], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise ProjectError("Native research wiki initialization failed: " + result.stderr)
    state = root / ".aris/runs/project.json"
    if not state.exists():
        result = subprocess.run([sys.executable, str(root / "vendor/aris/tools/run_state.py"),
                                 "start", str(root), "project", "--phases", "setting,literature,baseline,W1,W1.5,W2,W3", "--executor", "unconfigured"],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise ProjectError("Native phase state initialization failed: " + result.stderr)
    return {key: value for key, value in record.items() if key != "links"}


def doctor(root: Path) -> dict:
    if sys.version_info < (3, 10):
        raise ProjectError("Python >=3.10 is required")
    # Deliberately do not install/download anything or inspect credential values.
    report = {"status": "PASS", "python": sys.version, "platform": platform.platform(),
              "execution_backend": "local Linux/POSIX", "gpu_required_for_offline": False,
              "at": datetime.now(timezone.utc).isoformat(), "executable": sys.executable,
              "host_features": {"proc": Path("/proc/self/stat").is_file(), "dev_fd": Path("/dev/fd").is_dir()},
              "dependencies": {x: shutil.which(x) for x in ("python3", "bash", "git", "tmux", "nvidia-smi", "claude", "codex", "gemini", "agy")},
              "model_accounts": "UNVERIFIED; no authentication attempted",
              "remote_compute": "UNVERIFIED; tmux/scheduler handoff only",
              "upstream": upstream_check(root)}
    from installation import preserve_file
    preserve_file(root / "reports/doctor.json")
    atomic_json(root / "reports/doctor.json", report)
    return report


def validate(root: Path, real: bool = False) -> dict:
    for name in ("research", "resources", "models", "budget", "checks"):
        cfg = load(root / f"configs/{name}.json")
        if not isinstance(cfg, dict):
            raise ProjectError(f"configs/{name}.json must be an object")
    checks = load(root / "configs/checks.json")
    for key in ("require_frozen_protocol", "require_code_review_for_training", "require_baseline_before_idea_pilot", "require_raw_metrics", "no_toy_in_paper"):
        if checks.get(key) is not True:
            raise ProjectError(f"Mandatory rule cannot be disabled: checks.{key}")
    resources = load(root / "configs/resources.json")
    for group in ("data", "environments", "compute", "weights"):
        items = resources.get(group)
        if not isinstance(items, list) or any(not isinstance(x, dict) or not x.get("id") for x in items):
            raise ProjectError(f"Invalid resource registry group: {group}")
        if len({x["id"] for x in items}) != len(items):
            raise ProjectError(f"Duplicate resource IDs in {group}")
    budget = load(root / "configs/budget.json")
    for k in ("max_cpu_seconds", "max_gpu_hours", "max_cost_usd", "max_attempts", "max_retries"):
        if isinstance(budget.get(k), bool) or not isinstance(budget.get(k), (int, float)) or budget[k] < 0:
            raise ProjectError(f"Invalid budget.{k}")
    research = load(root / "configs/research.json")
    missing = [k for k in ("question", "setting", "data_id", "environment_id", "resource_id") if not research.get(k)]
    baseline = research.get("baseline", {})
    missing += [f"baseline.{k}" for k in ("paper_source", "repo", "repo_path", "commit", "validation_record") if not baseline.get(k)]
    if not budget.get("real_enabled"):
        missing.append("budget.real_enabled")
    for p in (root / ".claude/skills/idea-discovery/SKILL.md", root / ".agents/skills/idea-discovery/SKILL.md", root / ".aris/tools/run_state.py"):
        if not p.is_file():
            raise ProjectError(f"ARIS install missing: {p.relative_to(root)}; run init")
    from installation import validate_installation
    installation = validate_installation(root)
    models = load(root / "configs/models.json")
    routes = {"status": "legacy configuration; route integration not declared"}
    if models.get("schema_version", 1) >= 2:
        from model_routes import validate_routes
        routes = validate_routes(root)
    result = {"status": "BLOCKED" if real and missing else "PASS", "scope": "real" if real else "offline-engineering",
              "installation": installation, "model_routes": routes,
              "frozen_protocols": verify(root), "upstream": upstream_check(root),
              "research_readiness": "BLOCKED" if missing else "requires baseline-preflight + review + frozen protocol",
              "unconfigured": missing}
    if real and missing:
        raise ProjectError("Real research is BLOCKED: " + ", ".join(missing))
    return result


def baseline_preflight(root: Path) -> dict:
    from gates import check_baseline, resource
    research = load(root / "configs/research.json")
    for group, key in (("data", "data_id"), ("environments", "environment_id"), ("compute", "resource_id")):
        resource(root, group, research.get(key), "real")
    check_baseline(root, research, reproduced=False)
    return {"status": "PASS", "scope": "baseline-preparation-only",
            "next": "freeze baseline protocol, import code review, then run --job experiments/baseline.json",
            "reproduction": "not certified by preflight"}


def smoke(root: Path) -> dict:
    """Compute actual toy outputs in a fresh workspace; never consumes real budget."""
    from contracts import freeze
    from runtime import run
    from gates import digest
    with tempfile.TemporaryDirectory(prefix="auto-research-smoke-", dir=root / ".aris") as tmp:
        work = Path(tmp)
        for directory in ("configs", "examples/toy", "tools"):
            shutil.copytree(root / directory, work / directory, ignore=shutil.ignore_patterns("__pycache__"))
        (work / "contracts/toy-linear").mkdir(parents=True)
        shutil.copyfile(root / "examples/toy/contract.yaml", work / "contracts/toy-linear/v1.yaml")
        # Generate a machine-specific toy resource witness from this invocation.
        witness = {"kind": "toy", "source": "local smoke invocation", "python": sys.version,
                   "scope": "engineering verification only"}
        atomic_json(work / "examples/toy/resource-witness.json", witness)
        resources = {"data": [{"id": "toy-generator", "status": "verified", "kind": "toy", "path": "examples/toy/data-spec.json", "version": "synthetic-v1", "fingerprint": digest(work / "examples/toy/data-spec.json"), "split": "fixed synthetic train/test generator", "verification": {"evidence_file": "examples/toy/resource-witness.json"}}],
                     "environments": [{"id": "toy-python", "status": "verified", "kind": "toy", "path": sys.executable, "version": platform.python_version(), "verification": {"command": [sys.executable, "--version"], "evidence_file": "examples/toy/resource-witness.json"}}],
                     "compute": [{"id": "toy-cpu", "status": "verified", "kind": "toy", "backend": "local", "cpus": 1, "gpus": 0, "verification": {"evidence_file": "examples/toy/resource-witness.json"}}], "weights": []}
        atomic_json(work / "configs/resources.json", resources)
        freeze(work, "contracts/toy-linear/v1.yaml")
        result = run(work, "examples/toy/job.json", foreground=True)
        if result.get("status") != "completed":
            raise ProjectError(f"Toy failed: {result.get('status')}: {result.get('reason')}")
        # Keep the full evidence subtree, including the frozen source and registry.
        dest = root / "reports/toy-smoke"
        if dest.exists():
            archive = root / "reports" / ("toy-smoke-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f"))
            dest.rename(archive)
        for directory in ("contracts", "runs", "configs", "examples/toy"):
            shutil.copytree(work / directory, dest / directory)
        report = {"status": "PASS", "kind": "toy", "scientific_evidence": False,
                  "run": "runs/toy-linear-seed7/manifest.json", "metrics": result.get("metrics"),
                  "trace_root": "reports/toy-smoke", "replay": "python3 tools/research.py smoke",
                  "historical_command": "manifest.command retains the actual temporary execution path; job.command is its portable template; replay makes a fresh evidence subtree",
                  "limitations": "synthetic CPU chain only; no real baseline or scientific hypothesis was validated"}
        atomic_json(dest / "report.json", report)
        return report


def recovery(root: Path) -> dict:
    from runtime import resume
    runtime = resume(root)
    research = load(root / "configs/research.json")
    selected = research.get("selected_idea")
    registry_path = root / "contracts/.registry.json"
    protocols = load(registry_path).get("contracts", {}) if registry_path.exists() else {}
    active = [x for x in runtime.get("runs", []) if x.get("status") in ("queued", "running", "unconfirmed")]
    if not selected:
        selected = active[-1].get("idea_id") if active else ("baseline" if any(rec.get("idea_id") == "baseline" for rec in protocols.values()) else None)
    current = sorted([p for p, rec in protocols.items() if rec.get("idea_id") == selected],
                     key=lambda p: int(protocols[p]["version"]))
    native = []
    for path in sorted((root / ".aris/runs").glob("*.json")):
        state = load(path)
        phases = state.get("phases", [])
        pending = next((x for x in phases if x.get("status") not in ("accepted", "skipped")), None)
        brief_phase = {k: pending.get(k) for k in ("phase", "status", "artifact", "acceptance_status")} if pending else None
        native.append({"state": path.relative_to(root).as_posix(), "next_phase": brief_phase,
                       "note": "done/provisional is not cross-family accepted"})
    blockers = [f"configs/research.json:{key}" for key in ("question", "setting", "data_id", "environment_id", "resource_id") if not research.get(key)]
    budget = load(root / "configs/budget.json")
    if not budget.get("real_enabled"):
        blockers.append("real compute budget is not authorized/configured")
    shown = active + [x for x in runtime.get("runs", []) if x not in active][-10:]
    compact_runs = [{"task_id": x["task_id"], "stage": x.get("stage"), "status": x["status"],
                     "protocol": x.get("contract", {}).get("path"), "reason": x.get("reason"),
                     "manifest": f"runs/{x['task_id']}/manifest.json"} for x in shown]
    runtime_view = {"reserved": runtime["reserved"], "total_runs": len(runtime["runs"]),
                    "runs": compact_runs, "resubmitted": 0, "history": "full history via status and runs/*/manifest.json"}
    next_phase = next((x["next_phase"]["phase"] for x in native if x["next_phase"]), None)
    next_action = ("Inspect active/unconfirmed tasks before any launch" if active else
                   "Fill minimum configuration and run python3 tools/research.py baseline-preflight" if blockers else
                   f"Continue native phase {next_phase}; check its evidence gate and current protocol before proceeding" if next_phase else
                   "Review evidence audit and remaining scientific obligations before paper acceptance")
    result = {"status": "BLOCKED" if blockers else "REVIEW_REQUIRED", "selected_idea": selected,
              "current_protocol": active[-1].get("contract", {}).get("path") if active else (current[-1] if current else None),
              "working_contract": "idea-stage/docs/research_contract.md", "native_state": native,
              "runtime": runtime_view, "blockers": blockers, "next": next_action,
              "resubmitted": 0}
    text = "# 会话恢复入口（生成视图）\n\n此文件从原生状态、配置和运行清单生成，不作为第二套状态。\n\n```json\n" + json.dumps(result, ensure_ascii=False, indent=2) + "\n```\n\n先读当前 working contract 和所引用冻结协议；候选池/历史按需检索。\n"
    (root / ".aris/RECOVERY.md").write_text(text)
    return result


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = ROOT
    if args[:1] == ["--root"]:
        root = Path(args[1]).resolve()
        args = args[2:]
    if not args:
        args = ["--help"]
    action, *rest = args
    if action == "contract":
        from contracts import main as contract_main
        return contract_main(["--root", str(root), *rest])
    if action == "resume":
        try:
            emit(recovery(root))
            return 0
        except (ProjectError, OSError, ValueError) as exc:
            emit({"status": "BLOCKED", "reason": str(exc)})
            return 2
    if action in {"run", "status"}:
        from runtime import main as runtime_main
        return runtime_main(["--root", str(root), action, *rest])
    if action in {"context-pack", "import-review", "audit"}:
        from evidence import main as evidence_main
        return evidence_main(["--root", str(root), action, *rest])
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("init", "doctor", "smoke", "baseline-preflight"):
        sub.add_parser(name)
    sub.add_parser("validate").add_argument("--real", action="store_true")
    sub.add_parser("help").add_argument("topic", nargs="?")
    opts = parser.parse_args(args)
    try:
        if opts.action == "help":
            emit({"terminal_commands": ["init", "doctor", "validate [--real]", "smoke", "baseline-preflight", "contract validate|freeze --contract PATH", "contract verify [--contract PATH]", "run --job PATH [--foreground]", "status [--task ID]", "resume", "context-pack --idea ID --purpose PURPOSE", "import-review --package PATH --result PATH", "audit [--paper]"], "agent_slash_skills": "See docs/workflow.md; slash skills are agent prompts, not shell executables"})
        else:
            fn = {"init": install, "doctor": doctor, "validate": validate, "smoke": smoke, "baseline-preflight": baseline_preflight}[opts.action]
            emit(fn(root, opts.real) if opts.action == "validate" else fn(root))
        return 0
    except (ProjectError, OSError, ValueError, subprocess.SubprocessError) as exc:
        emit({"status": "BLOCKED", "reason": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
