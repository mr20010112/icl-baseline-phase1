#!/usr/bin/env python3
"""Export the ContextFlow baseline v2 package without executing research.

Only the standard library is used. SOURCE_DATE_EPOCH fixes the export timestamp
and Git dates for reproducible output given identical inputs and Git identity.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import amend_limits

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "contracts/baseline/v2.yaml"
FROZEN_PROTOCOL = "contracts/baseline/v1.yaml"
PAPER = "reports/imported-icl/source/literature/robot-icl/sources/step35-root/contextflow.txt"
PAPER_SHA256 = "1152159e626fa4a0f68a639b5f2b22708e2a20c402676ab7fb4275ec9518d223"
CHECKOUT = "<OPERATOR_CONTEXTFLOW_CHECKOUT>"
COMMIT_MESSAGE = "ContextFlow baseline reproduction package (active frozen protocol baseline v2)"
CONFIGURATION = """# 独立包配置 / Standalone package configuration

完整步骤见 [第三方操作指南](../handoffs/third-party/README.md)。v1 和 v2 均已冻结；
v2 是当前执行协议，v1 仅保留版本链。操作员不得手工创建、修改或重新冻结任何协议；唯一例外是负责人授权的 tools/amend_limits.py 后继时限版本，须披露并重新批量代码评审；
其他必要变更均退回项目负责人，以新版本处理。保留原冻结协议字节，仅由授权工具追加后继登记。使用
`experiments/baseline-seed42.json`、seed43、seed44 三个 job。

Follow the [operator guide](../handoffs/third-party/README.md). Both protocols are
already frozen: v2 is active; v1 is retained only for the version chain. Operators
must not create, edit or re-freeze any protocol by hand. The sole owner-authorized exception is a disclosed limit successor created by tools/amend_limits.py; fresh batch code review is required. Return every other needed change to the
project owner as a new version. Preserve all existing frozen protocol bytes; only the sanctioned tool appends successor registry entries.
Resource, review and budget gates still apply. Use the three exported
seed jobs. This package contains no historical registrations or reproduction results.

- `configs/research.json`: replace `baseline.repo_path=<OPERATOR_CONTEXTFLOW_CHECKOUT>`
  with your verified official checkout's absolute path; preserve the pinned commit
  and paper source. The preflight record belongs at
  `reports/third-party/baseline-preflight.json`, based on the supplied template.
- `configs/resources.json`: all four groups start empty. Register your own verified
  data, training interpreter, local compute and initialization weights; synchronize
  their IDs with research.json and all three jobs.
- `configs/budget.json`: real execution starts disabled with zero real limits.
  The resource owner sets authorized values following the protocol and guide.
- `configs/checks.json`: retain mandatory gates. `configs/models.json` retains
  review policy; `init` rebases portable `.mcp.json` and generates reviewer/install
  metadata. The operator uses the manual review round-trip in the guide.

只把实际检查通过且有真实证据的项写成 pass。baseline-preflight 不证明复现成功；
每个 seed 需要自己的 accepted code-review receipt，执行 completed 也不等于科学接受。
Preserve genuine verification evidence. Preflight does not certify reproduction;
each seed needs its own accepted code-review receipt. Completed execution still
requires result analysis and independent result review.
"""
TREES = ("tools", "tests", "templates", "docs", "examples", "baseline/runner",
         "handoffs/remote", "vendor/aris")
FILES = ("contracts/README.md", "contracts/.registry.json", FROZEN_PROTOCOL, PROTOCOL, PAPER,
         "tools/amend_limits.py", "tools/review_batch.py", "docs/operator-limit-authorization.md",
         "handoffs/third-party/README.md",
         "baseline/data/libero-hf-manifest.json", "experiments/baseline-config.json",
         *(f"experiments/baseline-seed{seed}.json" for seed in (42, 43, 44)),
         *(f"configs/{name}.json" for name in ("resources", "budget", "research", "models",
                                             "checks", "upstream-lock", "local-overrides")),
         ".mcp.json")
# Construct audit literals so this source is itself portable when exported.
LOCAL_PATH = re.compile(re.escape(b"/" + b"home/a/"))
HOME_PATH = re.compile(rb"/home/[A-Za-z0-9_.-]+(?:/[^\s\x00<>`\"']*)?")
USERS_PATH = b"/" + b"Users/"
PROJECT_PATH = re.compile(rb"/[^\n\x00<>`\"']{0,512}auto-research[ ]icl")
DRIVE_PATH = re.compile(rb"(?<![A-Za-z0-9])[A-Za-z]:[\\/][A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_. -]+)*")
PHASE2_TREES = ("experiments/phase2", "eval", "baseline/phase2", "baseline/adapters", "baseline/data",
                "reports/phase2-integration-20261030/manifests",
                "reports/phase2-integration-20261030/sources")
ENV_ROOT = "reports/shared-eval-env-20261030"
PHASE2_GUIDE = "handoffs/third-party/PHASE2.md"
PHASE2_NOTICE = """# Phase-2 benchmark package / 第二阶段评测包

**RELEASE CONDITION:** No phase-2 job may be started before the project owner's
written release after phase-1 acceptance. The launch gate does not check this
release condition. 任何第二阶段 job 必须等第一阶段验收和项目负责人的书面放行；
启动门禁不检查这项条件，不得用门禁通过代替书面放行。

Both v1–v6 protocols are already frozen. v2 governs phase 1; v3–v6 govern phase 2;
v1 is retained only for the version chain. Operators must not create, edit or re-freeze any protocol by hand. Only owner-authorized limit successors via tools/amend_limits.py are permitted; fresh batch review is required. Return every other needed change to the project owner as a new
version. All resource, review and budget gates remain mandatory.

Follow [the complete bilingual phase-2 guide](handoffs/third-party/PHASE2.md),
including environment setup, data/weights, registration, one review receipt per
job, release, execution and complete evidence return. The phase-1 guide below
applies to phase 1 only. Environments, downloads, real schemas, model loading,
physics, training, evaluation, timings and storage remain UNVERIFIED by export
checks; CPU fixtures only establish engineering behavior.

"""
EXCLUSIONS = [
    {"path": "reports/** (except the protocol-bound paper)", "reason": "owner history and results"},
    {"path": "runs/** (except .gitkeep)", "reason": "no execution evidence is shipped"},
    {"path": ".aris/**, .claude/**, .agents/**, .github/**", "reason": "init generates host installation and state"},
    {"path": "skills/**", "reason": "optional owner-specific agent workflows; baseline CLI and native init need no local skill overrides"},
    {"path": "idea-stage/**, refine-logs/**, research-wiki/**, analysis/**, paper/**", "reason": "outside baseline reproduction scope"},
    {"path": "handoffs/** except third-party/** and remote/**", "reason": "private role and review history"},
    {"path": "contracts/** except README.md, .registry.json, baseline/v1.yaml, baseline/v2.yaml and validated limit-successor chain", "reason": "phase-1 frozen lineage, including sanctioned limit amendments"},
    {"path": "baseline/checks/**, baseline/legacy-evidence.json, baseline/README.md", "reason": "unreferenced local checks and historical evidence"},
    {"path": "experiments/** except baseline-config.json, baseline-seed{42,43,44}.json and selected limit-deviation manifests/jobs/configs", "reason": "only phase-1 jobs and their sanctioned limit copies"},
    {"path": "**/.git/**, **/__pycache__/**, **/*.py[cod], **/.pytest_cache/**", "reason": "repository metadata and caches"},
    {"path": "**/.env*, **/*.private.json (except upstream-pinned public *.example)", "reason": "private configuration; public pinned templates retained unchanged"},
    {"path": "all other source paths", "reason": "explicit allowlist; not required for this standalone baseline"},
]
GITIGNORE = """# Generated evidence and operator resources; the bound paper remains tracked.
/runs/*
!/runs/.gitkeep
/reports/
/data/
/weights/
/checkpoints/
**/.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.cache/
.env*
!*.example
*.private.json
.aris/
.claude/
.agents/
.github/
research-wiki/
contracts/.registry.lock
reviews/.import.lock
*.pt
*.pth
*.ckpt
"""
PHASE2_GITIGNORE = """
# Operator-owned regenerated/conversion payloads and runtime caches.
/phase2-pinned/
/phase2-renders/
/phase2-converted/
/phase2-staging/
/checkpoint-scratch/
/clip-cache/
/openpi-cache/
*.hdf5
*.zarr/
*.zarr.zip
*.parquet
*.partial
*.part
**/.mujoco/
**/.numba/
"""
README = """# ContextFlow baseline reproduction / ContextFlow 基线复现

中文：这是供第三方在自己的机器上运行的独立仓库，包含项目执行门禁和已冻结的 v1、v2。
`contracts/baseline/v2.yaml` 是当前执行协议；v1 仅保留版本链。操作员不得手工创建、修改或重新冻结任何协议；只可用 tools/amend_limits.py 生成已授权的时限后继版并重新批量评审；其他必要变更均退回项目负责人，以新版本处理。原冻结协议字节保留，仅由授权工具追加后继登记。
官方 ContextFlow checkout、数据、权重、环境和运行结果不包含在内。本次打包未执行
训练、评测或下载；CPU 单元测试和 dry-run 不能作为复现结果。

English: both baseline protocols are already frozen. v2 is active; v1 is retained
only for the version chain. Operators must not create, edit or re-freeze any protocol by hand. Only owner-authorized limit successors via tools/amend_limits.py are permitted; fresh batch review is required. Return every other needed change to the project owner as a new version. Existing frozen protocol bytes are preserved; only the sanctioned tool appends successor registry entries. Resource, review and budget gates
still apply. Supply your own official checkout, data, weights,
environments and compute. Packaging performs no training, evaluation or downloads.
CPU fixtures and dry-runs are not reproduction results.

中文：完整快速开始、环境准备、资源登记、预算和三 seed 执行步骤见
[第三方操作指南](handoffs/third-party/README.md)。Linux/POSIX、Python ≥3.10、bash、git
可完成下面的离线工程检查。`init` 在本机生成安装清单、状态和绝对路径，并更新
portable `.mcp.json`；这些生成值不代表外部模型已登录或被调用。

English: follow the [bilingual operator guide](handoffs/third-party/README.md) for
setup, registration, budgets and the three seed jobs. The offline checks below
need Linux/POSIX, Python ≥3.10, bash and git. Run from this repository root.
`init` generates local installation/state and rebases the portable MCP settings.
External model tools are optional for this manual review workflow; CLI availability
does not establish authentication or reviewer identity.

```bash
timeout 600 python3 tools/research.py init
timeout 600 python3 tools/research.py doctor
timeout 600 python3 tools/research.py validate
timeout 600 python3 tools/research.py contract verify
timeout 600 env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

中文：首次 dry-run 预期以 exit 2 报告
`Missing evidence: <OPERATOR_CONTEXTFLOW_CHECKOUT>`；请在
`configs/research.json` 中把 `baseline.repo_path` 替换成你已核实的官方 checkout
绝对路径。随后仍须登记自己的 data/environments/compute/weights、真实验证证据、
执行者身份与预算。资源四组初始为空，真实预算关闭；此包不能直接启动训练。

English: an initial dry-run is expected to exit 2 with
`Missing evidence: <OPERATOR_CONTEXTFLOW_CHECKOUT>`. Set
`configs/research.json:baseline.repo_path` to your verified official checkout's
absolute path. Then register your resources and genuine verification records,
implementer identity and authorized budget. All four resource groups start empty
and real execution is disabled.

```bash
# Use a new evidence directory for every attempt.
timeout 600 python3 baseline/runner/contextflow_repro.py --seed 42 --dry-run \\
  --run-dir /tmp/contextflow-dry-run-UNIQUE
```

中文：评审往返：本机设置定稿 → 对每个 seed 用 `context-pack --purpose code-review`
导出完整包 → 发给项目负责人 → 负责人返回完整评审原文、真实身份凭据和 result JSON
→ 本机 `import-review` → 将 accepted PASS receipt 填入对应 job。每个 seed 分别评审，
seed42 的 receipt 不能复用给 43/44。具体命令见操作指南第 5 节。

English: finalize local settings, export a separate code-review context package
for each seed, and send each complete package to the project owner. The owner
returns the raw independent review, identity evidence and result JSON. Import
them locally with `import-review` and attach the accepted PASS receipt to that
seed's job. See section 5 of the operator guide for exact commands.

中文：返回每次尝试（含失败）的完整 run、配置、资源验证、冻结 registry、评审包/
receipts/身份原文和环境日志；大 checkpoint/video 先商定传输，不以汇总代替原始证据。
详细清单见操作指南第 7 节。发送前检查密钥，不发送认证缓存。

English: return complete evidence for every attempt, including failures: run
directories, actual configs, resource checks, frozen registry, review packages,
receipts, raw identities and environment logs. Arrange transfer of large
checkpoints/videos; retain raw evidence. See section 7 of the guide.

`EXPORT_MANIFEST.json` records every payload hash (excluding its own hash), all
sanitizations and exclusion rules. The owner-path audit covers committed files
(`git ls-files`), not files generated by local `init`/`doctor` or operator setup.
The pinned upstream public `.env.example` is included unchanged; real secrets
and private configuration are excluded. `vendor/aris/` is needed by init/doctor;
installed `.claude/`, `.agents/` and `.aris/` are generated. Owner-specific skills
are omitted and `configs/local-overrides.json` has empty customization lists;
the baseline CLI workflow uses the unmodified native installation and project gates.
Broader project documentation describes workflows outside this package; the
operator guide and baseline v2 protocol govern this reproduction.

For deterministic re-export, set `SOURCE_DATE_EPOCH` to an integer Unix timestamp
and use the same source files and Git identity. No remote is added or pushed.
"""


LIMIT_NOTICE = """
## Authorized limit deviations / 已授权时限偏差

Owner decision 2026-10-31: ONLY `tools/amend_limits.py plan|apply` may append
disclosed limit successors. Existing frozen files, evaluation-params and all
scientific settings remain immutable. `tools/review_batch.py` is included in both
phases for the required fresh per-job review round trip after a binding change.
Before observed runs provenance is unchanged; afterwards the unchanged contract
gate requires **post-hoc, exploratory; results are not preregistered** disclosure.
Record OPERATOR_LOG.md and return reports/third-party/limit-deviation.md plus the
entire old/new chain and evidence. Numeric review-call limits still count every
receipt. See the operator guide section 9 and docs/operator-limit-authorization.md.
负责人授权仅经工具追加时限后继版，必须披露并重新批量评审；原冻结文件不原地修改，
任何已观察运行后的新版本均按既有门禁标记 exploratory；其他科研设置不变。
"""
CONFIGURATION += LIMIT_NOTICE
README += LIMIT_NOTICE


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(root: Path, relative: str) -> dict:
    value = json.loads((root / relative).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {relative}")
    return value


def timestamp() -> str:
    value = os.environ.get("SOURCE_DATE_EPOCH")
    seconds = int(value) if value is not None else int(datetime.now(timezone.utc).timestamp())
    if seconds < 0:
        raise ValueError("SOURCE_DATE_EPOCH must be nonnegative")
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def protocol_paths(phase: int) -> tuple[str, ...]:
    if phase not in (1, 2):
        raise ValueError("phase must be 1 or 2")
    return tuple(f"contracts/baseline/v{version}.yaml" for version in range(1, 3 if phase == 1 else 7))


def phase2_artifact(relative: str) -> bool:
    if relative == PHASE2_GUIDE or relative.startswith(("experiments/phase2/", "baseline/phase2/",
            "baseline/adapters/", "eval/", "reports/phase2", ENV_ROOT + "/")):
        return True
    return relative.startswith("contracts/baseline/") and relative not in (FROZEN_PROTOCOL, PROTOCOL)


def phase2_test(relative: str, data: bytes) -> bool:
    return relative.startswith("tests/") and (Path(relative).name.startswith(("test_phase2", "test_shared", "test_bpp"))
        or any(fragment in data for fragment in (b"baseline.phase2", b"baseline.adapters", b"eval.shared_client")))


def audit_path(relative: str, data: bytes, *, root: Path, pinned: dict[str, str]) -> dict | None:
    """Check every payload byte; generic examples exempt only in verified vendor.

    Binary assets are checked for concrete host strings too. Drive-path matching
    on binary data requires readable path-shaped text, avoiding random PDF bytes.
    """
    vendor = relative.startswith("vendor/") and pinned.get(relative) == digest(data)
    users = list(re.finditer(re.escape(USERS_PATH) + rb"[^\s\x00<>`\"']*", data))
    generic_users = (b"...", b"yourname/", "你的用户名/".encode(), b"me/", b"<name>")
    concrete_users = [match for match in users if not vendor or not (
        not match.group()[len(USERS_PATH):] or match.group()[len(USERS_PATH):].startswith(generic_users))]
    concrete = (LOCAL_PATH.search(data) or concrete_users
                or (b"auto-research icl" in data and PROJECT_PATH.search(data))
                or str(root).encode() in data)
    if concrete:
        raise ValueError(f"Required file contains machine-local absolute paths: {relative}")
    homes = list(HOME_PATH.finditer(data))
    drives = list(DRIVE_PATH.finditer(data))
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        # Isolated drive-prefix coincidences in compressed bytes are not filesystem
        # paths; retain multi-component/readable names as audit candidates.
        drives = [match for match in drives if len(match.group()[3:]) >= 3 or
                  b"/" in match.group()[3:] or b"\\" in match.group()[3:]]
    matches = homes + users + drives
    if not matches:
        return None
    home_examples = (b"user", b"username", b"YOUR_USERNAME", b"u", "用户名".encode())
    nongeneric_homes = [m for m in homes if m.group().split(b"/")[2] not in home_examples]
    nongeneric_drives = [m for m in drives if not m.group()[3:].lower().startswith((b"path\\to\\", b"path/to/"))]
    if vendor and not nongeneric_homes and not nongeneric_drives:
        return {"path": relative, "sha256": digest(data),
                "reason": "generic example path in byte-verified pinned vendor; concrete host paths remain forbidden",
                "matched_examples_hex": sorted({match.group().hex() for match in matches}),
                "example_encoding": "hex preserves exact matched example bytes without embedding a forbidden path in this project manifest"}
    raise ValueError(f"Required file contains nonportable home/drive paths: {relative}")


def portable_source_pins(root: Path, relative: str, data: bytes) -> bytes:
    """Relocate unfrozen source evidence; retain repository commits/file hashes."""
    pins = read_json(root, ENV_ROOT + "/SOURCE_PINS.json")
    substitutions = {}
    for row in pins["sources"]:
        variable = {"libero": "PHASE2_LIBERO_ROOT", "behavior_prompting": "PHASE2_BPP_ROOT"}.get(row["name"])
        if variable and row.get("read_only_root"):
            substitutions[row["read_only_root"]] = "${" + variable + "}"
    substitutions[str(root)] = "${PROJECT_DIR}"
    records = json.loads(data)
    if isinstance(records, list):
        for row in records:
            path = row.get("path", "")
            if "/ContextFlow/" in path:
                substitutions[path.split("/ContextFlow/", 1)[0] + "/ContextFlow"] = "${CONTEXTFLOW_SOURCE}"
            marker = "/" + "auto-research icl/"
            if marker in path:
                substitutions[path.split(marker, 1)[0] + marker.rstrip("/")] = "${PROJECT_DIR}"
    # Longer LIBERO nested roots must win over their BPP parent.
    value = records
    def relocate(item):
        if isinstance(item, str):
            for original, replacement in sorted(substitutions.items(), key=lambda pair: -len(pair[0])):
                if item == original or item.startswith(original + "/"):
                    return replacement + item[len(original):]
            return item
        if isinstance(item, dict):
            return {key: relocate(member) for key, member in item.items()}
        if isinstance(item, list):
            return [relocate(member) for member in item]
        return item
    return encoded(relocate(value))


def phase2_environment_files(root: Path) -> set[str]:
    pins = read_json(root, ENV_ROOT + "/SOURCE_PINS.json")
    names = {"SOURCE_PINS.json", pins["source_file_hashes"]}
    for entry in pins["package_locks"].values():
        names.update(entry.values())
    names.update(pins.get("alternate_package_locks", []))
    files = {ENV_ROOT + "/" + name for name in names}
    files.update(p.relative_to(root).as_posix() for p in (root / ENV_ROOT / "inputs").rglob("*.in"))
    return files


def exclusion_rules(phase: int) -> list[dict[str, str]]:
    rules = [dict(row) for row in EXCLUSIONS]
    if phase == 2:
        replacements = {
            "reports/": {
                "path": "reports/** except the protocol-bound paper, phase2-integration-20261030/manifests/** and sources/**, and required shared-eval-env-20261030 source pins, source manifest, package locks and inputs/*.in",
                "reason": "only phase-2 runtime/source/environment evidence is included; historical reports and logs are excluded"},
            "contracts/": {
                "path": "contracts/** except README.md, .registry.json and baseline/v1.yaml through baseline/v6.yaml plus validated limit-successor chains",
                "reason": "six original frozen protocols and sanctioned limit amendments"},
            "experiments/": {
                "path": "experiments/** except baseline-config.json, baseline-seed{42,43,44}.json, phase2/** and selected limit-deviation manifests/jobs/configs",
                "reason": "phase-1 reproduction plus all phase-2 jobs, separate configs and parameters"},
            "handoffs/": {
                "path": "handoffs/** except third-party/README.md, third-party/PHASE2.md and remote/**",
                "reason": "operator guides only; implementation and private review handoffs are excluded"},
        }
        for index, row in enumerate(rules):
            for prefix, replacement in replacements.items():
                if row["path"].startswith(prefix):
                    rules[index] = replacement
                    break
    rules.append({"path": "**/*.lock except byte-verified pinned vendor lockfiles",
                  "reason": "operator/runtime lock files are not export payload"})
    return rules


def plan(root: Path, exported_at: str, *, phase: int) -> dict[str, bytes]:
    """Preflight all bindings and assemble a sorted, path-free payload in memory."""
    root = root.resolve()
    registry = read_json(root, "contracts/.registry.json")
    selected = protocol_paths(phase)
    if not set(selected).issubset(registry.get("contracts", {})):
        raise ValueError(f"Registry must contain every selected frozen protocol for phase {phase}")
    try:
        selected = amend_limits.export_protocols(root, phase)
    except (amend_limits.ProjectError, OSError, KeyError) as exc:
        raise ValueError(f"Invalid amended protocol chain: {exc}") from exc
    protocol_files = {}
    for relative in selected:
        entry = registry["contracts"][relative]
        if not isinstance(entry.get("frozen_at"), str) or not entry["frozen_at"].strip():
            raise ValueError(f"Protocol lacks frozen_at registration: {relative}")
        data = (root / relative).read_bytes()
        if digest(data) != entry.get("sha256"):
            raise ValueError(f"Frozen protocol differs from registry: {relative}; refusing export")
        protocol_files[relative] = data
    frozen_bytes = protocol_files[FROZEN_PROTOCOL]
    protocol_bytes = protocol_files[PROTOCOL]
    protocol = json.loads(protocol_bytes)
    if protocol.get("version") != 2 or protocol.get("amendment", {}).get("previous") != FROZEN_PROTOCOL:
        raise ValueError("Active protocol must be baseline v2 amending frozen v1")
    if (protocol["baseline"]["paper_source"] != PAPER
            or digest((root / PAPER).read_bytes()) != PAPER_SHA256
            or not protocol["baseline"]["reported_metrics"]
            or any(row.get("source_sha256") != PAPER_SHA256
                   for row in protocol["baseline"]["reported_metrics"])):
        raise ValueError("Protocol/paper SHA256 binding differs; refusing export")
    lock = read_json(root, "configs/upstream-lock.json")
    pinned = {"vendor/aris/" + name: value for name, value in lock["files"].items()}
    for relative, expected in pinned.items():
        if digest((root / relative).read_bytes()) != expected:
            raise ValueError(f"Pinned upstream file missing or changed: {relative}")
    if digest((root / "docs/source/AI科研指南.md").read_bytes()) != lock["guide_sha256"]:
        raise ValueError("Pinned guide differs from upstream lock")

    candidates = set(FILES) | set(selected)
    for relative in selected:
        amendment = read_json(root, relative).get("amendment", {})
        if amendment.get("kind") == amend_limits.KIND:
            for job_ref in amendment["jobs"].values():
                candidates.add(job_ref)
                candidates.add(read_json(root, job_ref)["config"])
                candidates.add((Path(job_ref).parent.parent / "manifest.json").as_posix())
    trees = TREES
    if phase == 2:
        if not (root / PHASE2_GUIDE).is_file():
            raise ValueError("Phase 2 requires handoffs/third-party/PHASE2.md; supply the project owner's complete guide")
        candidates.add(PHASE2_GUIDE)
        candidates.update(phase2_environment_files(root))
        trees += PHASE2_TREES
        # Include exactly every reviewed scope member, even if it is outside the
        # conventional trees. Refuse unsafe/missing paths before staging output.
        params = read_json(root, "experiments/phase2/job-params.json")
        for ref in params["protocol_implementation"]:
            path = root / ref
            if path.is_dir():
                trees += (ref,)
            else:
                candidates.add(ref)
    exclusions = exclusion_rules(phase)
    for tree in trees:
        directory = root / tree
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError(f"Required source directory missing or linked: {tree}")
        for current, dirs, names in os.walk(directory, followlinks=False):
            dirs[:] = sorted(name for name in dirs if name not in
                             {".git", "__pycache__", ".pytest_cache", ".cache", ".venv"})
            for name in sorted(dirs):
                if (Path(current) / name).is_symlink():
                    raise ValueError("Linked source directories are not exportable")
            candidates.update((Path(current) / name).relative_to(root).as_posix() for name in names)

    payload = {}
    sanitizations = []
    exemptions = []
    for relative in sorted(candidates):
        path = root / relative
        name = path.name
        public_template = relative in pinned and name.endswith(".example")
        private = ((name.startswith(".env") or name.endswith(".private.json")) and not public_template)
        runtime_lock = name.endswith(".lock") and relative not in pinned
        if private or runtime_lock or name.endswith((".pyc", ".pyo", ".pyd")) or name == ".DS_Store":
            if relative in pinned or relative in FILES:
                raise ValueError(f"Required file conflicts with exclusion rules: {relative}")
            exclusions.append({"path": relative, "reason": "private configuration or generated cache"})
            continue
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError(f"Required export file missing or unsafe: {relative}")
        data = path.read_bytes()
        if phase == 1 and phase2_test(relative, data):
            exclusions.append({"path": relative, "reason": "phase-2-only tests excluded from phase 1"})
            continue
        if relative == "contracts/.registry.json":
            data = encoded(dict(registry, contracts={ref: registry["contracts"][ref] for ref in selected}))
            reason = "Filter registry to selected already-frozen protocols; each protocol's original bytes and registration are preserved."
        elif relative in protocol_files:
            data = protocol_files[relative]
            reason = None
        elif relative == "configs/local-overrides.json":
            data = encoded({"schema_version": 1, "overrides": [], "project_skills": []})
            reason = "Omit optional owner-specific scout/workflow skills and their installation registrations; native init defaults suffice for the baseline CLI. Research gate and model-review policies unchanged."
        elif relative == "docs/configuration.md":
            data = (CONFIGURATION + ("\nPhase 2: follow [PHASE2.md](../handoffs/third-party/PHASE2.md). "
                    "No phase-2 job before the owner's written release after phase-1 acceptance; the launch gate does not check this.\n"
                    if phase == 2 else "")).encode()
            reason = "Replace historical/general setup instructions with standalone baseline-v2 configuration and operator-guide link."
        elif relative == "configs/resources.json":
            data = encoded({group: [] for group in ("data", "environments", "compute", "weights")})
            reason = "Replace all machine resource registrations with four empty groups."
        elif relative == "configs/budget.json":
            cfg = json.loads(data)
            cfg["real_enabled"] = False
            for key in cfg["scopes"]["real"]:
                if key.startswith("max_"):
                    cfg["scopes"]["real"][key] = 0
            data = encoded(cfg)
            reason = "Keep budget structure and toy/global limits; disable real execution and zero real limits for operator authorization."
        elif relative == "configs/research.json":
            cfg = json.loads(data)
            cfg.pop("superseded_direction", None)
            cfg.pop("legacy_import", None)
            cfg.pop("baselines", None)
            cfg["selected_idea"] = None
            cfg["status"] = "baseline_pending_operator_configuration"
            cfg["baseline"]["repo_path"] = CHECKOUT
            cfg["baseline"]["validation_record"] = "reports/third-party/baseline-preflight.json"
            cfg["baseline"]["reproduction_status"] = "pending"
            cfg["data_id"] = "libero-hf-a4336d58"
            cfg["environment_id"] = "THIRD_PARTY_CONTEXTFLOW_PY311"
            cfg["resource_id"] = "THIRD_PARTY_LOCAL_SINGLE_GPU"
            data = encoded(cfg)
            reason = ("Keep question/setting/benchmarks and baseline paper/repo/commit; remove superseded_direction, legacy_import and unrelated baselines deployment history; "
                      "clear selected idea and historical status; replace checkout/preflight paths and synchronize resource IDs with seed jobs. Operator supplies genuine preflight evidence.")
        elif relative == ".mcp.json":
            servers = json.loads(data)["mcpServers"]
            routes = {"codex": ("codex-exec", "CODEX_BIN", "codex"),
                      "antigravity": ("antigravity-exec", "AGY_BIN", "agy"),
                      "claude-review": ("claude-review", "CLAUDE_BIN", "claude")}
            if set(servers) != set(routes):
                raise ValueError("Unknown MCP server; portable sanitization requires explicit mapping")
            portable = {}
            for name, (directory, variable, command) in routes.items():
                env = {variable: command}
                if name == "claude-review":
                    env.update(CLAUDE_REVIEW_TOOLS="Read,Grep,Glob",
                               CLAUDE_REVIEW_STATE_DIR=".aris/project-runtime/claude-review",
                               CLAUDE_REVIEW_DEBUG_LOG=".aris/project-runtime/claude-review-debug.log")
                portable[name] = {"type": "stdio", "command": "python3",
                                  "args": [f"vendor/aris/mcp-servers/{directory}/server.py"], "env": env}
            data = encoded({"mcpServers": portable})
            reason = "Retain three server names and stdio structure; replace interpreter/CLI/bridge/state/log paths with portable values; discard all unrecognized settings/env fields. init generates local routes."
        elif relative in (ENV_ROOT + "/SOURCE_PINS.json", ENV_ROOT + "/source-manifest.json"):
            data = portable_source_pins(root, relative, data)
            reason = "Replace operator-specific checkout prefixes with documented environment placeholders in unfrozen source evidence; source commits and file hashes unchanged."
        else:
            reason = None
        if reason:
            sanitizations.append({"path": relative, "changes": reason, "source_sha256": digest(path.read_bytes())})
        try:
            exemption = audit_path(relative, data, root=root, pinned=pinned)
        except ValueError:
            if relative in FILES or not relative.startswith("docs/"):
                raise
            exclusions.append({"path": relative, "reason": "contains machine-local absolute paths; operator guide governs exported workflow"})
            continue
        if exemption:
            exemptions.append(exemption)
        payload[relative] = data

    # All implementation locations referenced by the v2 jobs must be present.
    required = set(FILES) | {"tools/research.py", "tools/gates.py", "tools/contracts.py",
                             "tools/installation.py", "tests/test_export_third_party.py"}
    for seed in (42, 43, 44):
        job = json.loads(payload[f"experiments/baseline-seed{seed}.json"])
        if job["contract"] != PROTOCOL or job["seed"] != seed:
            raise ValueError(f"Seed {seed} job does not bind baseline v2")
        required.update(job["code_paths"])
        required.add(job["config"])
    if phase == 2:
        jobs = [ref for ref in payload if ref.startswith("experiments/phase2/") and ref.count("/") == 2
                and ref.endswith(".json") and not ref.endswith("job-params.json")]
        if len(jobs) != 60:
            raise ValueError("Phase 2 requires exactly 60 phase-2 job files")
        for ref in jobs:
            job = json.loads(payload[ref])
            if job["contract"] not in selected or job["contract"] not in registry["contracts"]:
                raise ValueError(f"Job references contract missing from selected registry: {ref}")
            required.update(job["code_paths"])
            required.add(job["config"])
        required.update((PHASE2_GUIDE, "tools/review_batch.py", "tests/test_review_batch.py"))
    elif any(phase2_artifact(ref) and ref not in selected for ref in payload):
        raise ValueError("Phase-2 artifact would be included in phase 1")
    missing = {ref for ref in required if ref not in payload and not any(name.startswith(ref + "/") for name in payload)}
    if missing:
        raise ValueError(f"Required export files absent: {sorted(missing)}")
    payload.update({"README.md": ((PHASE2_NOTICE if phase == 2 else "") + README).encode(),
                    ".gitignore": (GITIGNORE + (PHASE2_GITIGNORE if phase == 2 else "")).encode(), "runs/.gitkeep": b""})
    manifest = {
        "schema_version": 1, "exported_at": exported_at, "phase": phase,
        "frozen_protocols": [{"path": ref, **registry["contracts"][ref]} for ref in selected],
        "protocol": {"path": PROTOCOL, "sha256": digest(protocol_bytes), "status": "frozen",
                     "frozen_at": registry["contracts"][PROTOCOL]["frozen_at"]},
        "frozen_protocol": {"path": FROZEN_PROTOCOL, "sha256": digest(frozen_bytes),
                            "frozen_at": registry["contracts"][FROZEN_PROTOCOL]["frozen_at"]},
        "paper": {"path": PAPER, "sha256": PAPER_SHA256},
        "inventory_scope": "All committed payload files except EXPORT_MANIFEST.json itself; Git metadata excluded.",
        "files": [{"path": name, "sha256": digest(data), "bytes": len(data)} for name, data in sorted(payload.items())],
        "sanitizations": sanitizations, "exclusions": exclusions,
        "path_audit": {"scope": "every committed payload file; concrete host paths never exempt",
                       "pinned_vendor_generic_example_exemptions": exemptions},
        "dependencies": {"vendor/aris": "init/doctor/validate verify every upstream-lock entry",
                         "skills": "optional local skills omitted; local-overrides.json has empty lists; native init needs only vendor",
                         "installed_state": "not shipped; operator init generates .claude/.agents/.aris and rebases .mcp.json"},
        "execution": "No training, evaluation, data/weight downloads or external model calls performed by exporter.",
        "determinism": "Sorted payload and hashes; SOURCE_DATE_EPOCH fixes export/Git dates; Git identity comes from git config.",
    }
    payload["EXPORT_MANIFEST.json"] = encoded(manifest)
    # Generated documentation/manifest are committed too, so audit them as well.
    for relative, data in payload.items():
        audit_path(relative, data, root=root, pinned=pinned)
    return dict(sorted(payload.items()))


def git(root: Path, *args: str, env: dict | None = None) -> str:
    result = subprocess.run(["timeout", "600", "git", "-c", "core.hooksPath=/dev/null",
                             "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
                            cwd=root, env=env, capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise ValueError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


STATIC_VERIFY = r'''
import json, pathlib, sys, tempfile
root = pathlib.Path.cwd().resolve()
sys.path.insert(0, str(root / "tools"))
from contracts import verify
from amend_limits import export_protocols, KIND
from runtime import bind_config, snapshot_code, validate_job
registry = json.loads((root / "contracts/.registry.json").read_text())["contracts"]
verification = verify(root)
phase = int(sys.argv[1])
expected = set(export_protocols(root, phase))
if set(registry) != expected:
    raise ValueError("Export registry protocol inventory differs")
jobs = [root / f"experiments/baseline-seed{seed}.json" for seed in (42,43,44)]
if phase == 2:
    jobs.extend(sorted(p for p in (root / "experiments/phase2").glob("*.json") if p.name != "job-params.json"))
for ref in expected:
    amendment = json.loads((root / ref).read_text()).get("amendment", {})
    if amendment.get("kind") == KIND:
        jobs.extend(root / ref for ref in amendment["jobs"].values())
scopes = {}
for path in jobs:
    job = json.loads(path.read_text())
    validate_job(job)
    if job["contract"] not in registry:
        raise ValueError("Job references contract missing from registry: " + str(path.relative_to(root)))
    protocol = json.loads((root / job["contract"]).read_text())
    seeds = protocol["seeds"]
    if isinstance(seeds, dict):
        seeds = seeds["values"]
    if job["seed"] not in seeds:
        raise ValueError("Job seed is not in its frozen protocol")
    config = json.loads((root / job["config"]).read_text())
    bind_config(job, config, protocol)
    reviewed = []
    for ref in job["code_paths"]:
        source = (root / ref).resolve()
        if not source.is_relative_to(root) or not source.exists():
            raise ValueError("Missing/unsafe code_paths member: " + ref)
        reviewed.append(source)
    for element in protocol["method"]["implementation"]:
        ref = element["path"] if isinstance(element, dict) else element
        source = (root / ref).resolve()
        if not source.exists() or not source.is_relative_to(root) or not any(
            source == base or (base.is_dir() and source.is_relative_to(base)) for base in reviewed):
            raise ValueError("Protocol implementation outside job code_paths: " + ref)
    scope = tuple(job["code_paths"])
    if scope not in scopes:
        with tempfile.TemporaryDirectory(prefix="export-code-snapshot-") as temporary:
            entries = snapshot_code(root, pathlib.Path(temporary), list(scope))
            scopes[scope] = {"files": len(entries), "bytes": sum((root / row["path"]).stat().st_size for row in entries)}
print(json.dumps({"contracts": verification["count"], "jobs": len(jobs), "snapshots": list(scopes.values())}))
'''


def verify_export_tree(root: Path, phase: int) -> dict:
    """Read-only export checks, except temporary runtime snapshot copies.

    No resource checks, model imports, real job launches or gate modifications.
    Checks run in the staged tree, never against the owner's installed state.
    """
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("PYTHONPATH", None)
    commands = [["timeout", "600", sys.executable, "-B", "-c", STATIC_VERIFY, str(phase)],
                ["timeout", "600", sys.executable, "-B", "tools/research.py", "contract", "verify"]]
    if phase == 2:
        commands.append(["timeout", "600", sys.executable, "-B", "baseline/phase2/materialize_jobs.py", "--check"])
    outputs = []
    for command in commands:
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=600)
        if result.returncode:
            raise ValueError("Export-time verification failed: " + result.stdout.strip() + "\n" + result.stderr.strip())
        outputs.append(result.stdout.strip())
    return {"static": json.loads(outputs[0]), "contract_verify": json.loads(outputs[1]),
            "materialize_check": outputs[2] if phase == 2 else None}


def build(output: Path, *, phase: int, root: Path = ROOT, initialize_git: bool = True,
          exported_at: str | None = None) -> dict:
    """Prepare fully in scratch space, then publish into the empty output."""
    root = root.resolve()
    if output.is_symlink():
        raise ValueError("Output must not be a symlink")
    output = output.resolve()
    if output.is_relative_to(root):
        raise ValueError("Output must be outside this project")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Refusing existing non-empty output directory")
    exported_at = exported_at or timestamp()
    payload = plan(root, exported_at, phase=phase)
    # Ignore Git directory overrides so an inherited shell cannot redirect writes.
    env = {key: value for key, value in os.environ.items() if key not in
           {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
            "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"}}
    if initialize_git:
        author = {key: git(root, "config", "--get", f"user.{key}", env=env) for key in ("name", "email")}
        if not all(author.values()):
            raise ValueError("Configure git user.name and user.email before exporting")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="third-party-export-", dir="/tmp") as temporary:
        stage = Path(temporary)
        for name, data in payload.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            original = root / name
            path.chmod(0o755 if original.is_file() and original.stat().st_mode & 0o111 else 0o644)
        verification = verify_export_tree(stage, phase)
        commit = None
        if initialize_git:
            git(stage, "init", "--initial-branch=main", "--template=", env=env)
            for key, value in author.items():
                git(stage, "config", "--local", f"user.{key}", value, env=env)
            env.update(GIT_AUTHOR_NAME=author["name"], GIT_AUTHOR_EMAIL=author["email"],
                       GIT_COMMITTER_NAME=author["name"], GIT_COMMITTER_EMAIL=author["email"],
                       GIT_AUTHOR_DATE=exported_at, GIT_COMMITTER_DATE=exported_at)
            git(stage, "add", "--force", "--all", "--", ".", env=env)
            git(stage, "commit", "--no-verify", "-m", COMMIT_MESSAGE + ("; phase 2" if phase == 2 else "; phase 1"), env=env)
            commit = git(stage, "rev-parse", "HEAD", env=env)
            if git(stage, "remote", env=env):
                raise ValueError("Unexpected Git remote")
        # Recheck immediately before publication; never replace new user contents.
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError("Output became non-empty during export; refusing replacement")
        try:
            os.replace(stage, output)
        except OSError as exc:
            if exc.errno not in {errno.EXDEV, errno.EROFS, errno.EBUSY}:
                raise
            # A separate volume or writable mount root may prohibit renaming
            # the directory itself while allowing writes inside it. All checks
            # and the commit finish before copying into the empty destination.
            shutil.copytree(stage, output, dirs_exist_ok=True)
    return {"output": str(output), "phase": phase, "files": len(payload),
            "payload_bytes": sum(map(len, payload.values())), "commit": commit,
            "verification": verification}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, type=int, choices=(1, 2))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.output, phase=args.phase), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
