#!/usr/bin/env python3
"""Prepare isolated project research handoffs without dispatching a model."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import uuid

sys.dont_write_bytecode = True

from contracts import ProjectError, atomic_json, load, project_path, sha
from evidence import check_venue_code
from gates import check_baseline, resolve


ROOT = Path(__file__).resolve().parents[1]
LITERATURE_FIELDS = (
    "id", "classification", "source", "locator", "statement", "url", "checked_at",
    "venue", "code_url",
)


def _verified_literature(root: Path) -> list[tuple[dict, Path, str]]:
    """Read evidence records, never candidate pools or generation transcripts."""
    directory = root / "idea-stage/literature"
    index = directory / "evidence.jsonl"
    if not index.is_file():
        raise ProjectError("Proposal requires verified literature in idea-stage/literature/evidence.jsonl")
    records = []
    for line_no, line in enumerate(index.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ProjectError(f"Invalid literature JSON at line {line_no}") from exc
        if not isinstance(row, dict):
            raise ProjectError(f"Literature line {line_no} must be an object")
        if row.get("classification") != "verified":
            continue
        if any(not isinstance(row.get(key), str) or not row[key].strip()
               for key in ("source", "locator", "statement", "url", "checked_at")):
            raise ProjectError(f"Verified literature line {line_no} lacks source, statement or verification")
        check_venue_code(row)
        if not row["url"].startswith(("https://", "http://")):
            raise ProjectError(f"Verified literature line {line_no} lacks a source URL")
        ref = row.get("artifact")
        if not isinstance(ref, str) or not ref:
            raise ProjectError(f"Verified literature line {line_no} lacks an artifact")
        artifact = project_path(root, ref)
        if not artifact.is_relative_to(directory.resolve()) or artifact == index.resolve():
            raise ProjectError("Proposal literature artifacts must be files inside idea-stage/literature/")
        if not artifact.is_file() or artifact.stat().st_size == 0 or sha(artifact) != row.get("artifact_sha256"):
            raise ProjectError(f"Verified literature source missing or stale at line {line_no}")
        records.append(({key: row[key] for key in LITERATURE_FIELDS if key in row}, artifact, row["artifact_sha256"]))
    if not records:
        raise ProjectError("Proposal requires at least one verified literature record")
    return records


def prepare_proposal(root: Path) -> Path:
    """Build a clean proposer context only after accepted baseline reproduction."""
    root = root.resolve()
    research = load(root / "configs/research.json")
    for key in ("question", "setting"):
        if not isinstance(research.get(key), str) or not research[key].strip():
            raise ProjectError(f"Research {key} is unset")
    count = research.get("candidate_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ProjectError("candidate_count must be a positive integer")
    check_baseline(root, research, reproduced=True)
    rows = _verified_literature(root)
    baseline = research["baseline"]
    paper = resolve(root, baseline["paper_source"]).resolve()
    if not paper.is_file() or paper.stat().st_size == 0:
        raise ProjectError("Baseline paper must be a nonempty project file")
    from model_routes import role_route
    route = role_route(root, "idea_proposer")
    budget = load(root / "configs/budget.json")
    policy = load(root / "configs/models.json").get("policy", {})
    folder = root / "handoffs/proposal" / uuid.uuid4().hex[:12]
    files = folder / "files"
    files.mkdir(parents=True)
    entries = []

    def copy_source(source: Path, name: str, expected: str) -> str:
        dest = files / name
        shutil.copyfile(source, dest)
        source_ref = source.relative_to(root).as_posix() if source.is_relative_to(root) else str(source)
        if sha(dest) != expected:
            raise ProjectError(f"Source changed while preparing proposal: {source_ref}")
        entries.append({"path": source_ref,
                        "packaged_path": dest.relative_to(folder).as_posix(), "sha256": sha(dest)})
        return dest.relative_to(folder).as_posix()

    copy_source(paper, "baseline" + paper.suffix, sha(paper))
    literature = []
    for index, (row, artifact, expected) in enumerate(rows):
        packaged = copy_source(artifact, f"literature-{index:03d}" + artifact.suffix, expected)
        literature.append({**row, "artifact": packaged, "artifact_sha256": expected})
    atomic_json(files / "literature.json", literature)
    atomic_json(files / "constraints.json", {
        "question": research["question"], "setting": research["setting"],
        "candidate_count": count,
        "baseline": {"commit": baseline["commit"], "reproduction": "verified_by_project_gate"},
        "resource_ids": {key: research.get(key) for key in ("data_id", "environment_id", "resource_id")},
        "compute_budget": {key: budget.get(key) for key in ("real_enabled", "scopes")},
        "model_budget": {key: policy.get(key) for key in ("max_model_cost_usd", "max_model_wall_seconds")},
    })
    for name in ("literature.json", "constraints.json"):
        path = files / name
        entries.append({"packaged_path": path.relative_to(folder).as_posix(), "sha256": sha(path), "generated": True})
    atomic_json(folder / "manifest.json", {
        "schema_version": 1, "purpose": "idea-proposal", "created_at": datetime.now(timezone.utc).isoformat(),
        "requested_route": route, "actual_identity": None, "files": entries,
        "boundary": "fresh_session_only; baseline and verified literature only; no candidates, histories or rankings",
        "dispatch": "not_dispatched",
    })
    (folder / "REQUEST.md").write_text(
        "# 候选生成交接\n\n仅在新的独立会话/空工作区打开本包 files/ 中的材料。"
        "不要读取项目候选池、旧生成讨论、ranking 或 architect 偏好。"
        "按 constraints.json 的 candidate_count 生成候选，每项填写项目 idea 模板所需的 hypothesis、"
        "description、compatibility、implementation_cost、expected_signal、risks。"
        "literature.json 的 verified 仅表示本项目已有来源核验，不保证科学主张成立。\n\n"
        "本工具没有调用模型。通过 manifest.json 中的 requested_route 发起经授权的 Antigravity 新会话；"
        "仅给出本包输入，不复用生成历史。保存完整原始响应和返回身份依据，"
        "将实际 proposer_identity 写入各候选；未知身份保留 unknown。不要执行训练、pilot 或评审。"
        "候选随后各自创建 idea-review 包，不能把完整候选池交给 reviewer。\n",
        encoding="utf-8",
    )
    return folder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("prepare-proposal")
    args = parser.parse_args(argv)
    try:
        folder = prepare_proposal(args.root)
        print(json.dumps({"status": "PREPARED", "package": str(folder), "dispatched": False}, ensure_ascii=False))
        return 0
    except (ProjectError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
